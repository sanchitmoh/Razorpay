from __future__ import annotations

import hashlib
import hmac
import json
import uuid
import pytest
from httpx import AsyncClient

from app.core.config import settings

TEST_WEBHOOK_SECRET = "whsec_test_secret_for_security_tests"


def compute_sig(data: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_stats_requires_api_key_when_enabled(client: AsyncClient, monkeypatch):
    """Verify that /webhooks/stats endpoint enforces API key auth when enabled."""
    monkeypatch.setattr(settings, "api_key_enabled", True)
    monkeypatch.setattr(settings, "api_key", "valid_stats_key")

    # Unauthenticated -> 401
    r_unauth = await client.get("/api/v1/webhooks/stats")
    assert r_unauth.status_code == 401
    assert r_unauth.json()["error"]["code"] == "UNAUTHORIZED"

    # Authenticated -> 200 with metadata
    r_auth = await client.get("/api/v1/webhooks/stats", headers={"X-API-Key": "valid_stats_key"})
    assert r_auth.status_code == 200
    data = r_auth.json()
    assert "total_events" in data
    assert "metadata" in data


@pytest.mark.asyncio
async def test_webhook_constant_time_signature_verification():
    """Verify that verify_razorpay_webhook_signature fails closed on empty or wrong secrets."""
    from app.api.routes.webhooks import verify_razorpay_webhook_signature

    body = b'{"test": 123}'
    valid_sig = compute_sig(body, "my_secret")

    # Valid
    assert verify_razorpay_webhook_signature(body, valid_sig, "my_secret") is True
    # Invalid signature
    assert verify_razorpay_webhook_signature(body, "wrong_sig", "my_secret") is False
    # Empty secret
    assert verify_razorpay_webhook_signature(body, valid_sig, "") is False
    # Empty signature header
    assert verify_razorpay_webhook_signature(body, "", "my_secret") is False


@pytest.mark.asyncio
async def test_webhook_malformed_json_returns_400_with_metadata(client: AsyncClient, monkeypatch):
    """Verify that sending unparseable JSON returns 400 Bad Request with error metadata."""
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)
    bad_json = b"{not-valid-json-string"
    sig = compute_sig(bad_json, TEST_WEBHOOK_SECRET)

    resp = await client.post(
        "/api/v1/webhooks/razorpay",
        content=bad_json,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "MALFORMED_JSON"
    assert "metadata" in data


@pytest.mark.asyncio
async def test_webhook_response_includes_metadata_and_request_id(client: AsyncClient, monkeypatch):
    """Verify that successful webhook ingestion returns APIMetadata with request_id and timing."""
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)
    payload = {
        "event_id": f"evt_meta_{uuid.uuid4().hex[:8]}",
        "event": "payment.authorized",
        "payload": {},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_sig(payload_bytes, TEST_WEBHOOK_SECRET)

    resp = await client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "metadata" in data
    assert data["metadata"]["request_id"] is not None
    assert "X-Request-ID" in resp.headers


@pytest.mark.asyncio
async def test_webhook_rate_limiter_protects_endpoint(client: AsyncClient, monkeypatch):
    """Verify that token bucket rate limiter protects webhook ingestion endpoint against flooding."""
    from app.core.security import TokenBucketRateLimiter, rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)
    test_limiter = TokenBucketRateLimiter(capacity=1, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        payload = {"event_id": "evt_flood_1", "event": "dummy"}
        body = json.dumps(payload).encode("utf-8")
        sig = compute_sig(body, TEST_WEBHOOK_SECRET)

        # 1st request -> 200
        r1 = await client.post("/api/v1/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
        assert r1.status_code == 200

        # 2nd request -> 429 Rate limited
        r2 = await client.post("/api/v1/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
        assert r2.status_code == 429
        assert r2.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        app.dependency_overrides.pop(rate_limiter, None)
