from __future__ import annotations

import hashlib
import hmac
import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.payment import Payment
from app.models.webhook_event import WebhookEvent
from app.models.enums import WebhookEventStatus, BatchStatus
from app.repositories.payment_repo import PaymentRepo
from app.repositories.webhook_event_repo import WebhookEventRepo
from app.agents.ingestion import parse_razorpay_payment_dict

TEST_SECRET = "test_webhook_secret_123"


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


def make_payment_captured_payload(payment_id: str, order_id: str, amount_paise: int, event_id: str | None = None) -> dict:
    return {
        "entity": "event",
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": order_id,
                    "fee": 236,
                    "tax": 36,
                    "created_at": 1718000000,
                }
            }
        },
        "created_at": 1718000000,
    }


@pytest.mark.asyncio
async def test_webhook_secret_unset_returns_503(client: AsyncClient, monkeypatch):
    """Verify that if RAZORPAY_WEBHOOK_SECRET is unset, requests are rejected with 503 (fail closed, VULN-001)."""
    # Patch settings in the webhooks module where it's actually used
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", "")

    payload = make_payment_captured_payload("pay_test_unset", "order_test_unset", 10000)
    response = await client.post(
        "/api/v1/webhooks/razorpay",
        json=payload,
        headers={"X-Razorpay-Signature": "some_sig"},
    )
    assert response.status_code == 503
    assert "RAZORPAY_WEBHOOK_SECRET is not set" in response.text


@pytest.mark.asyncio
async def test_webhook_valid_signature_accepted(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify that a valid HMAC signature returns 200 and logs PROCESSED event."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)

    event_id = f"evt_valid_{uuid.uuid4().hex[:8]}"
    pay_id = f"pay_wh_{uuid.uuid4().hex[:8]}"
    payload = make_payment_captured_payload(pay_id, "order_wh_1", 10000, event_id=event_id)
    payload_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(payload_bytes, TEST_SECRET)

    response = await client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["event_id"] == event_id
    assert data["payment_ingested"] is True

    # Verify event stored in DB
    event_rec = await WebhookEventRepo.get_by_event_id(db_session, event_id)
    assert event_rec is not None
    assert event_rec.status == WebhookEventStatus.PROCESSED

    # Verify payment upserted in DB
    payment = await PaymentRepo.get_by_id(db_session, pay_id)
    assert payment is not None
    assert payment.amount_paise == 10000
    assert payment.fee_paise == 236


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify that an invalid HMAC signature returns 401 and writes nothing to DB."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)

    event_id = f"evt_invalid_{uuid.uuid4().hex[:8]}"
    pay_id = f"pay_inv_{uuid.uuid4().hex[:8]}"
    payload = make_payment_captured_payload(pay_id, "order_wh_inv", 5000, event_id=event_id)
    payload_bytes = json.dumps(payload).encode("utf-8")
    bad_sig = "invalid_signature_hash_value"

    response = await client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": bad_sig, "Content-Type": "application/json"},
    )

    assert response.status_code == 401

    # Verify DB has no record
    event_rec = await WebhookEventRepo.get_by_event_id(db_session, event_id)
    assert event_rec is None
    payment = await PaymentRepo.get_by_id(db_session, pay_id)
    assert payment is None


@pytest.mark.asyncio
async def test_webhook_duplicate_event_idempotent(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify sending same razorpay_event_id twice logs SKIPPED_DUPLICATE and does not duplicate payments."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)

    event_id = f"evt_dup_{uuid.uuid4().hex[:8]}"
    pay_id = f"pay_dup_{uuid.uuid4().hex[:8]}"
    payload = make_payment_captured_payload(pay_id, "order_dup", 15000, event_id=event_id)
    payload_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(payload_bytes, TEST_SECRET)

    headers = {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}

    # First call
    r1 = await client.post("/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["payment_ingested"] is True

    # Second call with same event_id
    r2 = await client.post("/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["payment_ingested"] is False

    # Check that payments table has exactly 1 row for pay_id
    stmt = select(func.count(Payment.id)).where(Payment.id == pay_id)
    count = (await db_session.execute(stmt)).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_webhook_unhandled_event_type_logged(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify non-captured events (e.g. payment.failed) are logged as SKIPPED_UNHANDLED without creating payments."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)

    event_id = f"evt_unhandled_{uuid.uuid4().hex[:8]}"
    payload = {
        "event_id": event_id,
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_failed_{uuid.uuid4().hex[:8]}",
                    "amount": 20000,
                    "status": "failed",
                }
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(payload_bytes, TEST_SECRET)

    resp = await client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["payment_ingested"] is False

    event_rec = await WebhookEventRepo.get_by_event_id(db_session, event_id)
    assert event_rec is not None
    assert event_rec.status == WebhookEventStatus.SKIPPED_UNHANDLED


@pytest.mark.asyncio
async def test_webhook_payment_upsert_matches_ingestion():
    """Verify that parse_razorpay_payment_dict parses raw payloads identically for batch and webhook."""
    raw_dict = {
        "id": "pay_shared_test",
        "order_id": "order_shared_test",
        "amount": 50000,
        "fee": 1180,
        "tax": 180,
        "status": "captured",
        "created_at": 1718000000,
    }

    model = parse_razorpay_payment_dict(raw_dict)
    assert model.id == "pay_shared_test"
    assert model.order_id == "order_shared_test"
    assert model.amount_paise == 50000
    assert model.fee_paise == 1180
    assert model.tax_paise == 180
    assert model.status == "captured"


@pytest.mark.asyncio
async def test_webhook_below_threshold_no_batch(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify that if unreconciled payment count is below threshold, no micro-batch is triggered."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)
    monkeypatch.setattr("app.agents.webhook_processor.settings.webhook_micro_batch_threshold", 5)

    # Send 2 events (< 5)
    for i in range(2):
        p_id = f"pay_below_{i}_{uuid.uuid4().hex[:6]}"
        payload = make_payment_captured_payload(p_id, f"order_{i}", 10000)
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = compute_signature(payload_bytes, TEST_SECRET)

        resp = await client.post(
            "/api/v1/webhooks/razorpay",
            content=payload_bytes,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json()["batch_triggered"] is False


@pytest.mark.asyncio
async def test_webhook_micro_batch_triggers_at_threshold(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Verify that reaching webhook_micro_batch_threshold triggers automatic micro-batch reconciliation."""
    monkeypatch.setattr("app.api.routes.webhooks.settings.razorpay_webhook_secret", TEST_SECRET)
    monkeypatch.setattr("app.agents.webhook_processor.settings.webhook_micro_batch_threshold", 3)

    # Send 3 payments -> 3rd triggers micro-batch
    last_resp = None
    for i in range(3):
        p_id = f"pay_micro_{i}_{uuid.uuid4().hex[:6]}"
        payload = make_payment_captured_payload(p_id, f"order_micro_{i}", 10000)
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = compute_signature(payload_bytes, TEST_SECRET)

        last_resp = await client.post(
            "/api/v1/webhooks/razorpay",
            content=payload_bytes,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert last_resp.status_code == 200

    data = last_resp.json()
    assert data["batch_triggered"] is True
    assert data["batch_id"] is not None

    # Check stats endpoint
    stats_resp = await client.get("/api/v1/webhooks/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_events"] >= 3
