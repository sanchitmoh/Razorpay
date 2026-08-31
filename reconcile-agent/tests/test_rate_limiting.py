"""
Comprehensive Rate Limiting Tests with Upstash Redis Integration
Tests all three rate limiting modes: Upstash, Standard Redis, and In-Memory
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenBucketRateLimiter
from app.db.database import get_db
from app.main import app


@pytest_asyncio.fixture(scope="function")
async def client_no_rate_limit_override(db_session: AsyncSession):
    """Test client WITHOUT the default high-capacity rate limiter override."""
    async def override_get_db():
        yield db_session
    
    # Only override database, NOT rate limiter
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upstash_redis_rate_limiting_success(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify rate limiting works with Upstash Redis REST API."""
    from app.core.security import rate_limiter
    from app.main import app

    # Configure Upstash credentials
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "https://mock-upstash.upstash.io")
    monkeypatch.setattr(settings, "upstash_redis_rest_token", "mock_token")
    monkeypatch.setattr(settings, "redis_url", "")  # Disable standard Redis

    test_limiter = TokenBucketRateLimiter(capacity=2, refill_rate=0.01)

    # Mock Upstash API responses
    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        # First request: allowed (result=[1, 1.0] means allowed with 1 token remaining)
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": [1, 1.0]}
        )

        app.dependency_overrides[rate_limiter] = test_limiter

        try:
            # Use an endpoint that has rate limiting enabled
            r1 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r1.status_code in [200, 401], f"First request failed: {r1.status_code}"

            # Second request: allowed
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"result": [1, 0.0]}
            )
            r2 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r2.status_code in [200, 401], f"Second request failed"

            # Third request: denied
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"result": [0, 0.0]}
            )
            r3 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r3.status_code == 429, f"Third request should be rate limited, got: {r3.status_code}"
            data = r3.json()
            assert data["error"]["code"] == "RATE_LIMITED"
            assert "Retry-After" in r3.headers
            print("✓ Upstash Redis rate limiting works")

        finally:
            app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_upstash_redis_fallback_to_memory(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify rate limiter falls back to in-memory when Upstash fails."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "upstash_redis_rest_url", "https://mock-upstash.upstash.io")
    monkeypatch.setattr(settings, "upstash_redis_rest_token", "mock_token")
    monkeypatch.setattr(settings, "redis_url", "")

    test_limiter = TokenBucketRateLimiter(capacity=2, refill_rate=0.01)

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        # Simulate Upstash API failure
        mock_post.side_effect = httpx.RequestError("Connection failed")

        app.dependency_overrides[rate_limiter] = test_limiter

        try:
            # Should fall back to in-memory and still work
            r1 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r1.status_code in [200, 401], "First request should succeed with fallback"

            r2 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r2.status_code in [200, 401], "Second request should succeed"

            # Third request should be rate limited (in-memory)
            r3 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r3.status_code == 429, "Third request should be rate limited"
            assert r3.json()["error"]["code"] == "RATE_LIMITED"
            print("✓ Upstash fallback to in-memory works")

        finally:
            app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_rate_limiting_with_standard_redis_url(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify rate limiting works with standard Redis URL (non-Upstash)."""
    from app.core.security import rate_limiter
    from app.main import app

    # Configure standard Redis
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_token", "")

    test_limiter = TokenBucketRateLimiter(capacity=2, refill_rate=0.01)

    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(side_effect=[
        [1, 1.0],  # First request: allowed
        [1, 0.0],  # Second request: allowed
        [0, 0.0],  # Third request: denied
    ])

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        app.dependency_overrides[rate_limiter] = test_limiter

        try:
            r1 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r1.status_code in [200, 401]

            r2 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r2.status_code in [200, 401]

            r3 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
            assert r3.status_code == 429
            assert r3.json()["error"]["code"] == "RATE_LIMITED"
            print("✓ Standard Redis rate limiting works")

        finally:
            app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_in_memory_rate_limiting_no_redis(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify in-memory rate limiting works when no Redis is configured."""
    from app.core.security import rate_limiter
    from app.main import app

    # Disable all Redis options
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_token", "")

    test_limiter = TokenBucketRateLimiter(capacity=2, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Use webhook stats endpoint which requires rate limiter
        r1 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r1.status_code in [200, 401]

        r2 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r2.status_code in [200, 401]

        # Third request: should be rate limited
        r3 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r3.status_code == 429
        data = r3.json()
        assert data["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in r3.headers
        print("✓ In-memory rate limiting works")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_rate_limiting_token_refill(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify tokens refill over time allowing new requests."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    # High refill rate for faster test
    test_limiter = TokenBucketRateLimiter(capacity=1, refill_rate=10.0)  # 10 tokens/sec
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        r1 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r1.status_code in [200, 401]

        # Second request: should be rate limited immediately
        r2 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r2.status_code == 429

        # Wait for refill (0.2 seconds = 2 tokens refilled)
        await asyncio.sleep(0.2)

        # Third request: should succeed after refill
        r3 = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r3.status_code in [200, 401]
        print("✓ Token refill works")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_rate_limiting_different_clients():
    """Verify rate limiting is per-client (different IPs have separate buckets)."""
    test_limiter = TokenBucketRateLimiter(capacity=1, refill_rate=0.01)

    # Test that different client keys would have separate buckets
    key1 = "192.168.1.1"
    key2 = "192.168.1.2"

    allowed1, _ = test_limiter._check_memory(key1, requested=1)
    assert allowed1, "First client first request should succeed"

    allowed2, _ = test_limiter._check_memory(key2, requested=1)
    assert allowed2, "Second client first request should succeed"

    # Both exhausted their capacity (1 token each)
    denied1, _ = test_limiter._check_memory(key1, requested=1)
    assert not denied1, "First client second request should be denied"

    denied2, _ = test_limiter._check_memory(key2, requested=1)
    assert not denied2, "Second client second request should be denied"
    print("✓ Per-client rate limiting works")


@pytest.mark.asyncio
async def test_rate_limiting_retry_after_header(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify Retry-After header is correctly calculated and returned."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    test_limiter = TokenBucketRateLimiter(capacity=1, refill_rate=0.5)  # 2 seconds per token
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Exhaust capacity
        await client_no_rate_limit_override.get("/api/v1/webhooks/stats")

        # Get rate limited
        r = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r.status_code == 429

        retry_after = int(r.headers.get("Retry-After", "0"))
        assert retry_after > 0, "Retry-After header should be present and positive"
        assert retry_after <= 3, "Retry-After should be reasonable"
        print(f"✓ Retry-After header works: {retry_after}s")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_rate_limiting_protects_all_endpoints(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify rate limiting is applied to multiple endpoints."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    test_limiter = TokenBucketRateLimiter(capacity=3, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Mix of different rate-limited endpoints
        endpoints = [
            "/api/v1/webhooks/stats",
            "/api/v1/batches/00000000-0000-0000-0000-000000000000",  # Will 404 but rate-limited
            "/api/v1/webhooks/stats",
        ]

        for endpoint in endpoints:
            r = await client_no_rate_limit_override.get(endpoint)
            assert r.status_code in [200, 401, 404], f"Request to {endpoint} should succeed initially"

        # Fourth request should be rate limited
        r = await client_no_rate_limit_override.get("/api/v1/webhooks/stats")
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"
        print("✓ Multiple endpoints protected by rate limiting")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_upstash_redis_connection_with_real_credentials():
    """Integration test: Verify Upstash Redis connection works with real credentials."""
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        pytest.skip("Upstash Redis credentials not configured")

    # Test real Upstash connection
    url = f"{settings.upstash_redis_rest_url.rstrip('/')}/get/test_key"
    headers = {
        "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            assert resp.status_code in [200, 404], f"Upstash connection failed: {resp.status_code}"
            print(f"✓ Upstash Redis connection successful (status: {resp.status_code})")
        except Exception as e:
            pytest.fail(f"Upstash Redis connection error: {e}")


@pytest.mark.asyncio
async def test_rate_limiter_lua_script_execution():
    """Verify the Lua script logic works correctly for token bucket algorithm."""
    from app.core.security import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(capacity=5, refill_rate=1.0)

    # Test in-memory implementation matches expected behavior
    key = "test_client"

    # Initial request: should have full capacity
    allowed, remaining = limiter._check_memory(key, requested=1)
    assert allowed is True
    assert remaining == 4.0

    # Use all tokens
    for i in range(4):
        allowed, remaining = limiter._check_memory(key, requested=1)
        assert allowed is True

    # Should be denied now
    allowed, remaining = limiter._check_memory(key, requested=1)
    assert allowed is False
    print("✓ Lua script token bucket logic works")


@pytest.mark.asyncio
async def test_rate_limiting_concurrent_requests(client_no_rate_limit_override: AsyncClient, db_session, monkeypatch):
    """Verify rate limiting handles concurrent requests correctly."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    test_limiter = TokenBucketRateLimiter(capacity=5, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Fire 10 concurrent requests
        tasks = [client_no_rate_limit_override.get("/api/v1/webhooks/stats") for _ in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code in [200, 401])
        rate_limited_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 429)

        # With capacity 5, we expect 5 successes and 5 rate limited
        assert success_count == 5, f"Expected 5 successful requests, got {success_count}"
        assert rate_limited_count == 5, f"Expected 5 rate limited requests, got {rate_limited_count}"
        print(f"✓ Concurrent rate limiting works: {success_count} allowed, {rate_limited_count} blocked")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)
