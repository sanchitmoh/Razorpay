from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RazorpayIngestionError(Exception):
    """Raised when fetching payments from Razorpay API persistently fails."""
    pass


class RazorpayClient:
    """Async client for interacting with Razorpay Payments API in test mode (§7.1)."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        base_url: str = "https://api.razorpay.com/v1",
        timeout: float = 15.0,
    ) -> None:
        self.key_id = key_id or settings.razorpay_key_id
        self.key_secret = key_secret or settings.razorpay_key_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def fetch_captured_payments(
        self,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        max_records: int | None = None,
        use_fixture_fallback: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Fetch all captured payments from Razorpay API with pagination handling (§7.1).
        Fixture fallback is strictly gated behind USE_FIXTURES=1 for testing (§10.1).
        """
        if settings.use_fixtures == "1":
            if use_fixture_fallback:
                fixture_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "tests",
                    "fixtures",
                    "razorpay_payments_50_mixed.json",
                )
                if os.path.exists(fixture_path):
                    logger.info("Using local Razorpay fixture from %s", fixture_path)
                    with open(fixture_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return data.get("items", [])

        if not (self.key_id and self.key_secret):
            raise RazorpayIngestionError(
                "Razorpay API credentials missing. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env, "
                "or set USE_FIXTURES=1 for testing."
            )

        all_items: list[dict[str, Any]] = []
        count = 100
        skip = 0

        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.key_id, self.key_secret),
            timeout=self.timeout,
        ) as client:
            while True:
                params: dict[str, Any] = {
                    "count": count,
                    "skip": skip,
                }
                if from_timestamp is not None:
                    params["from"] = from_timestamp
                if to_timestamp is not None:
                    params["to"] = to_timestamp

                attempts = 0
                max_retries = 2
                response_data = None

                while attempts <= max_retries:
                    try:
                        response = await client.get("/payments", params=params)
                        if response.status_code == 200:
                            response_data = response.json()
                            break
                        elif response.status_code in (429, 500, 502, 503, 504):
                            attempts += 1
                            if attempts > max_retries:
                                raise RazorpayIngestionError(
                                    f"Razorpay API error HTTP {response.status_code}: {response.text}"
                                )
                            await asyncio.sleep(0.5 * (2 ** attempts))
                        else:
                            raise RazorpayIngestionError(
                                f"Razorpay API request failed with status {response.status_code}: {response.text}"
                            )
                    except httpx.RequestError as exc:
                        attempts += 1
                        if attempts > max_retries:
                            raise RazorpayIngestionError(
                                f"Razorpay API network request error: {str(exc)}"
                            ) from exc
                        await asyncio.sleep(0.5 * (2 ** attempts))

                if response_data is None:
                    raise RazorpayIngestionError("Failed to retrieve payments from Razorpay API.")

                items = response_data.get("items", [])
                captured_items = [p for p in items if p.get("status") == "captured"]
                all_items.extend(captured_items)

                if len(items) < count or (max_records and len(all_items) >= max_records):
                    break

                skip += len(items)

        if max_records:
            all_items = all_items[:max_records]

        return all_items

    async def fetch_payment_by_id(self, payment_id: str) -> dict[str, Any] | None:
        """
        Fetch a single payment by ID for drill-down on an exception (§7.1: GET /v1/payments/:id).
        """
        if settings.use_fixtures == "1":
            fixture_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "tests",
                "fixtures",
                "razorpay_payments_50_mixed.json",
            )
            if os.path.exists(fixture_path):
                with open(fixture_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("items", []):
                        if item.get("id") == payment_id:
                            return item
            return None

        if not (self.key_id and self.key_secret):
            raise RazorpayIngestionError("Razorpay API credentials missing.")

        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.key_id, self.key_secret),
            timeout=self.timeout,
        ) as client:
            resp = await client.get(f"/payments/{payment_id}")
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                return None
            else:
                raise RazorpayIngestionError(f"Error fetching payment {payment_id}: {resp.text}")

    async def create_order(
        self,
        amount_paise: int,
        receipt: str,
        currency: str = "INR",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create an order in Razorpay test mode (POST /v1/orders).
        """
        if not (self.key_id and self.key_secret):
            raise RazorpayIngestionError("Razorpay credentials required to create live test orders.")

        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": notes or {},
        }

        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.key_id, self.key_secret),
            timeout=self.timeout,
        ) as client:
            resp = await client.post("/orders", json=payload)
            if resp.status_code in (200, 201):
                return resp.json()
            raise RazorpayIngestionError(f"Failed to create order: {resp.text}")
