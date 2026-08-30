from __future__ import annotations

import io
import uuid
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.batch import Batch


@pytest.mark.asyncio
async def test_batch_create_rejects_empty_bank_file(client: AsyncClient):
    """Verify that uploading an empty CSV file is rejected with 400 Bad Request."""
    files = {
        "bank_csv": ("bank.csv", io.BytesIO(b""), "text/csv"),
        "ledger_csv": ("ledger.csv", io.BytesIO(b"order_id,expected_amount_paise\nord1,1000"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "EMPTY_FILE"
    assert "metadata" in data


@pytest.mark.asyncio
async def test_batch_create_rejects_oversized_file(client: AsyncClient, monkeypatch):
    """Verify that uploads exceeding max_upload_size_bytes return 413 Payload Too Large."""
    monkeypatch.setattr(settings, "max_upload_size_bytes", 100)  # Low limit for testing
    large_csv = b"utr,amount_paise,value_date\n" + (b"UTR123,1000,2026-08-01\n" * 10)
    files = {
        "bank_csv": ("bank.csv", io.BytesIO(large_csv), "text/csv"),
        "ledger_csv": ("ledger.csv", io.BytesIO(b"order_id,expected_amount_paise\nord1,1000"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files)
    assert resp.status_code == 413
    data = resp.json()
    assert data["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_batch_create_rejects_invalid_file_extension(client: AsyncClient):
    """Verify that non-CSV extensions (e.g. .exe, .pdf) are rejected with 400."""
    files = {
        "bank_csv": ("malicious_payload.exe", io.BytesIO(b"binary data"), "application/octet-stream"),
        "ledger_csv": ("ledger.csv", io.BytesIO(b"order_id,expected_amount_paise\nord1,1000"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVALID_FILE_TYPE"


@pytest.mark.asyncio
async def test_batch_create_requires_api_key_when_enabled(client: AsyncClient, monkeypatch):
    """Verify that batch creation is protected when API key auth is enabled."""
    monkeypatch.setattr(settings, "api_key_enabled", True)
    monkeypatch.setattr(settings, "api_key", "valid_secret_key")

    files = {
        "bank_csv": ("bank.csv", io.BytesIO(b"utr,amount_paise\nU1,100"), "text/csv"),
        "ledger_csv": ("ledger.csv", io.BytesIO(b"order_id,expected_amount_paise\nord1,100"), "text/csv"),
    }
    # Without header -> 401
    r_unauth = await client.post("/api/v1/batches", files=files)
    assert r_unauth.status_code == 401
    assert r_unauth.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_batch_get_invalid_uuid_returns_422(client: AsyncClient):
    """Verify that requesting a batch with malformed UUID returns 422 with structured error."""
    resp = await client.get("/api/v1/batches/not-a-uuid")
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "metadata" in data


@pytest.mark.asyncio
async def test_batch_get_nonexistent_returns_404_with_metadata(client: AsyncClient):
    """Verify that requesting an unknown batch returns 404 with standard error format and metadata."""
    random_uuid = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/batches/{random_uuid}")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "NOT_FOUND"
    assert "metadata" in data
    assert data["metadata"]["request_id"] is not None


@pytest.mark.asyncio
async def test_batch_exceptions_pagination_bounds(client: AsyncClient, seeded_batch: Batch):
    """Verify that pagination limits enforce validation bounds (limit > 200 is rejected)."""
    # Over max limit (200) -> 422
    r_over = await client.get(f"/api/v1/batches/{seeded_batch.id}/exceptions?limit=500")
    assert r_over.status_code == 422

    # Negative offset -> 422
    r_neg = await client.get(f"/api/v1/batches/{seeded_batch.id}/exceptions?offset=-1")
    assert r_neg.status_code == 422

    # Valid pagination -> 200 with metadata
    r_valid = await client.get(f"/api/v1/batches/{seeded_batch.id}/exceptions?limit=10&offset=0")
    assert r_valid.status_code == 200
    data = r_valid.json()
    assert "data" in data
    assert "total" in data
    assert "metadata" in data


@pytest.mark.asyncio
async def test_batch_matches_pagination_valid(client: AsyncClient, seeded_batch: Batch):
    """Verify that matches endpoint returns valid paginated response with metadata."""
    resp = await client.get(f"/api/v1/batches/{seeded_batch.id}/matches?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert "metadata" in data
    assert len(data["data"]) >= 1


@pytest.mark.asyncio
async def test_batch_retry_completed_returns_409(client: AsyncClient, seeded_batch: Batch):
    """Verify that attempting to retry an already completed batch returns 409 Conflict."""
    resp = await client.post(f"/api/v1/batches/{seeded_batch.id}/retry")
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"]["code"] == "INVALID_STATE"
    assert "metadata" in data


@pytest.mark.asyncio
async def test_batch_rate_limiter_fires(client: AsyncClient):
    """Verify that the token bucket rate limiter protects batch endpoints."""
    from app.core.security import TokenBucketRateLimiter, rate_limiter
    from app.main import app

    test_limiter = TokenBucketRateLimiter(capacity=1, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        random_uuid = str(uuid.uuid4())
        # 1st call -> 404 (not found, but allowed through rate limiter)
        r1 = await client.get(f"/api/v1/batches/{random_uuid}")
        assert r1.status_code == 404

        # 2nd call -> 429 Rate limited
        r2 = await client.get(f"/api/v1/batches/{random_uuid}")
        assert r2.status_code == 429
        assert r2.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        app.dependency_overrides.pop(rate_limiter, None)
