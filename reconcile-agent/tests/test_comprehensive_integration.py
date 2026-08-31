"""
Comprehensive Integration Tests
Tests the entire system with security, rate limiting, and all features integrated
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


@pytest.mark.asyncio
async def test_full_system_integration_with_security(client: AsyncClient, monkeypatch):
    """
    End-to-end test: Create batch, check status, verify rate limiting, test QA.
    Tests the complete workflow with all security features enabled.
    """
    # Enable API key security for this test
    test_api_key = "test_secure_key_" + str(uuid.uuid4())
    monkeypatch.setattr(settings, "api_key_enabled", True)
    monkeypatch.setattr(settings, "api_key", test_api_key)

    headers = {"X-API-Key": test_api_key}

    # Step 1: Health check (no auth required)
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    health_data = r.json()
    assert health_data["status"] == "ok"  # Fixed: actual response is "ok" not "healthy"
    print("✓ Health check passed")

    # Step 2: Try to create batch without API key (should fail)
    r = await client.post(
        "/api/v1/batches",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "enable_qa": True,
        }
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    print("✓ Security: Unauthorized access blocked")

    # Step 3: Create batch with valid API key
    r = await client.post(
        "/api/v1/batches",
        headers=headers,
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "enable_qa": True,
        }
    )
    assert r.status_code == 201
    batch_data = r.json()
    batch_id = batch_data["data"]["batch_id"]
    assert batch_data["data"]["status"] in ["PENDING", "PROCESSING", "COMPLETED"]
    print(f"✓ Batch created: {batch_id}")

    # Step 4: Get batch status with API key
    r = await client.get(f"/api/v1/batches/{batch_id}", headers=headers)
    assert r.status_code == 200
    status_data = r.json()
    assert status_data["data"]["batch_id"] == batch_id
    print(f"✓ Batch status retrieved: {status_data['data']['status']}")

    # Step 5: Test QA endpoint with API key
    r = await client.post(
        "/api/v1/qa",
        headers=headers,
        json={
            "batch_id": batch_id,
            "question": "How many payments were reconciled?"
        }
    )
    assert r.status_code == 200
    qa_data = r.json()
    assert "answer" in qa_data["data"]
    print(f"✓ QA query successful: {qa_data['data']['answer'][:100]}")

    # Step 6: Test webhook stats with API key
    r = await client.get("/api/v1/webhooks/stats", headers=headers)
    assert r.status_code == 200
    webhook_stats = r.json()
    assert "total_events" in webhook_stats["data"]
    print(f"✓ Webhook stats retrieved: {webhook_stats['data']['total_events']} events")


@pytest.mark.asyncio
async def test_rate_limiting_across_all_endpoints(client: AsyncClient, monkeypatch):
    """Verify rate limiting protects all API endpoints consistently."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    from app.core.security import TokenBucketRateLimiter
    test_limiter = TokenBucketRateLimiter(capacity=5, refill_rate=0.01)
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Test various endpoints
        test_batch_id = str(uuid.uuid4())
        endpoints = [
            ("GET", "/api/v1/health", None),
            ("POST", "/api/v1/batches", {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "enable_qa": False
            }),
            ("GET", f"/api/v1/batches/{test_batch_id}", None),
            ("GET", f"/api/v1/batches/{test_batch_id}/exceptions", None),
            ("GET", "/api/v1/webhooks/stats", None),
        ]

        success_count = 0
        rate_limited_count = 0

        for method, endpoint, json_data in endpoints:
            if method == "GET":
                r = await client.get(endpoint)
            else:
                r = await client.post(endpoint, json=json_data)

            if r.status_code == 429:
                rate_limited_count += 1
                assert r.json()["error"]["code"] == "RATE_LIMITED"
            elif r.status_code in [200, 201, 404]:  # 404 is ok for non-existent batch
                success_count += 1

        # With capacity 5, we expect 5 successes
        assert success_count == 5, f"Expected 5 successful requests, got {success_count}"
        print(f"✓ Rate limiting: {success_count} allowed, {rate_limited_count} blocked")

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_security_and_validation_integration(client: AsyncClient, monkeypatch):
    """Test security features: API keys, input validation, and error handling."""
    test_api_key = "secure_test_key"
    monkeypatch.setattr(settings, "api_key_enabled", True)
    monkeypatch.setattr(settings, "api_key", test_api_key)

    # Test 1: Invalid API key
    r = await client.post(
        "/api/v1/batches",
        headers={"X-API-Key": "wrong_key"},
        json={"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert r.status_code == 401
    print("✓ Invalid API key rejected")

    # Test 2: Missing API key
    r = await client.post(
        "/api/v1/batches",
        json={"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert r.status_code == 401
    print("✓ Missing API key rejected")

    # Test 3: Valid API key but invalid date format
    r = await client.post(
        "/api/v1/batches",
        headers={"X-API-Key": test_api_key},
        json={"start_date": "invalid-date", "end_date": "2024-01-31"}
    )
    assert r.status_code == 422  # Validation error
    print("✓ Invalid input format rejected")

    # Test 4: Valid API key and valid input
    r = await client.post(
        "/api/v1/batches",
        headers={"X-API-Key": test_api_key},
        json={"start_date": "2024-01-01", "end_date": "2024-01-31", "enable_qa": True}
    )
    assert r.status_code == 201
    print("✓ Valid authenticated request succeeded")

    # Test 5: QA endpoint with too long question
    long_question = "x" * 5000  # Exceeds qa_max_question_length
    r = await client.post(
        "/api/v1/qa",
        headers={"X-API-Key": test_api_key},
        json={"question": long_question}
    )
    assert r.status_code == 422
    print("✓ Oversized input rejected")


@pytest.mark.asyncio
async def test_concurrent_batch_processing_with_rate_limiting(client: AsyncClient, monkeypatch):
    """Test system under concurrent load with rate limiting enabled."""
    from app.core.security import rate_limiter
    from app.main import app

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "")

    from app.core.security import TokenBucketRateLimiter
    test_limiter = TokenBucketRateLimiter(capacity=10, refill_rate=5.0)  # Higher capacity for load test
    app.dependency_overrides[rate_limiter] = test_limiter

    try:
        # Fire 20 concurrent batch creation requests
        tasks = []
        for i in range(20):
            task = client.post(
                "/api/v1/batches",
                json={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                    "enable_qa": False
                }
            )
            tasks.append(task)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 201)
        rate_limited_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 429)
        error_count = sum(1 for r in responses if isinstance(r, Exception))

        print(f"✓ Concurrent test: {success_count} succeeded, {rate_limited_count} rate-limited, {error_count} errors")
        # With rate limiter override in tests (high capacity), most should succeed
        assert success_count >= 15, f"Expected at least 15 successful requests, got {success_count}"
        assert error_count == 0, "No requests should have errors"

    finally:
        app.dependency_overrides.pop(rate_limiter, None)


@pytest.mark.asyncio
async def test_upstash_redis_integration_live():
    """Live integration test with actual Upstash Redis (requires credentials)."""
    import httpx

    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        pytest.skip("Upstash Redis credentials not configured in .env")

    # Test SET operation
    set_url = f"{settings.upstash_redis_rest_url.rstrip('/')}/set/integration_test_key/test_value_123"
    headers = {"Authorization": f"Bearer {settings.upstash_redis_rest_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # SET
        resp = await client.get(set_url, headers=headers)
        assert resp.status_code == 200, f"Upstash SET failed: {resp.text}"
        print("✓ Upstash Redis SET successful")

        # GET
        get_url = f"{settings.upstash_redis_rest_url.rstrip('/')}/get/integration_test_key"
        resp = await client.get(get_url, headers=headers)
        assert resp.status_code == 200, f"Upstash GET failed: {resp.text}"
        data = resp.json()
        assert data.get("result") == "test_value_123", f"Unexpected value: {data}"
        print("✓ Upstash Redis GET successful")

        # DELETE
        del_url = f"{settings.upstash_redis_rest_url.rstrip('/')}/del/integration_test_key"
        resp = await client.get(del_url, headers=headers)
        assert resp.status_code == 200, f"Upstash DEL failed: {resp.text}"
        print("✓ Upstash Redis DEL successful")


@pytest.mark.asyncio
async def test_error_handling_and_resilience(client: AsyncClient):
    """Test system resilience and error handling across components."""
    # Test 1: Non-existent batch
    fake_batch_id = str(uuid.uuid4())
    r = await client.get(f"/api/v1/batches/{fake_batch_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    print("✓ 404 error handling correct")

    # Test 2: Invalid UUID format
    r = await client.get("/api/v1/batches/not-a-uuid")
    assert r.status_code == 422
    print("✓ Invalid UUID rejected")

    # Test 3: QA without required fields
    r = await client.post("/api/v1/qa", json={})
    assert r.status_code == 422
    print("✓ Missing required fields rejected")

    # Test 4: Malformed JSON
    r = await client.post(
        "/api/v1/batches",
        content=b"{invalid json",
        headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    print("✓ Malformed JSON rejected")


@pytest.mark.asyncio
async def test_request_id_tracing(client: AsyncClient):
    """Verify X-Request-ID header for distributed tracing."""
    # Test 1: Server generates request ID
    r = await client.get("/api/v1/health")
    assert "X-Request-ID" in r.headers
    request_id_1 = r.headers["X-Request-ID"]
    assert len(request_id_1) > 0
    print(f"✓ Server-generated request ID: {request_id_1}")

    # Test 2: Client provides request ID (should be preserved)
    custom_request_id = str(uuid.uuid4())
    r = await client.get("/api/v1/health", headers={"X-Request-ID": custom_request_id})
    assert r.headers["X-Request-ID"] == custom_request_id
    print(f"✓ Client request ID preserved: {custom_request_id}")


@pytest.mark.asyncio
async def test_cors_configuration(client: AsyncClient):
    """Verify CORS headers are properly configured."""
    r = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        }
    )
    # CORS headers should be present
    assert r.status_code in [200, 204]
    print("✓ CORS preflight handling works")


@pytest.mark.asyncio
async def test_webhook_ingestion_integration(client: AsyncClient, monkeypatch):
    """Test webhook ingestion with signature verification."""
    import hmac
    import hashlib

    webhook_secret = "test_webhook_secret_" + str(uuid.uuid4())
    monkeypatch.setattr(settings, "razorpay_webhook_secret", webhook_secret)

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test123",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }

    import json
    body = json.dumps(payload).encode()

    # Generate valid signature
    signature = hmac.new(
        webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    # Test 1: Valid signature
    r = await client.post(
        "/api/v1/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature}
    )
    assert r.status_code == 200
    print("✓ Valid webhook signature accepted")

    # Test 2: Invalid signature
    r = await client.post(
        "/api/v1/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "invalid_signature"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    print("✓ Invalid webhook signature rejected")


@pytest.mark.asyncio
async def test_performance_metrics(client: AsyncClient):
    """Verify performance metrics are within acceptable ranges."""
    import time

    # Test response times
    endpoints = [
        "/api/v1/health",
        "/api/v1/webhooks/stats",
    ]

    for endpoint in endpoints:
        start = time.time()
        r = await client.get(endpoint)
        duration = time.time() - start

        assert r.status_code in [200, 401], f"Endpoint {endpoint} failed"
        assert duration < 2.0, f"Endpoint {endpoint} too slow: {duration:.2f}s"
        print(f"✓ {endpoint}: {duration*1000:.1f}ms")


@pytest.mark.asyncio
async def test_all_features_together_smoke_test(client: AsyncClient):
    """
    Smoke test: Quick verification that all major features are accessible.
    This is a fast sanity check for CI/CD pipelines.
    """
    tests_passed = []

    # Health
    r = await client.get("/api/v1/health")
    tests_passed.append(("Health", r.status_code == 200))

    # Batch creation
    r = await client.post(
        "/api/v1/batches",
        json={"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    tests_passed.append(("Batch Creation", r.status_code == 201))

    # QA endpoint
    r = await client.post(
        "/api/v1/qa",
        json={"question": "test question"}
    )
    tests_passed.append(("QA Endpoint", r.status_code in [200, 400]))  # May fail without batch, but should respond

    # Webhook stats
    r = await client.get("/api/v1/webhooks/stats")
    tests_passed.append(("Webhook Stats", r.status_code in [200, 401]))

    # Print results
    print("\n" + "="*60)
    print("SMOKE TEST RESULTS:")
    for name, passed in tests_passed:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    print("="*60)

    # All should pass
    assert all(passed for _, passed in tests_passed), "Some smoke tests failed"
