from __future__ import annotations

import pytest
from httpx import AsyncClient
from unittest.mock import patch
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_health_returns_200_with_connected_db(client: AsyncClient):
    """Verify that GET /api/v1/health returns 200 with status ok and connected DB."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert data["version"] == "1.0.0"
    assert "uptime_seconds" in data
    assert "checks" in data
    assert data["checks"]["database"] == "connected"


@pytest.mark.asyncio
async def test_health_includes_request_id_header(client: AsyncClient):
    """Verify that health check responses include X-Request-ID header."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0


@pytest.mark.asyncio
async def test_health_preserves_caller_request_id(client: AsyncClient):
    """Verify that a supplied X-Request-ID header is echoed back."""
    req_id = "test-health-trace-123"
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": req_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == req_id


@pytest.mark.asyncio
async def test_health_reports_degraded_when_db_fails(client: AsyncClient):
    """Verify that if database execution fails, status is degraded and db is disconnected."""
    with patch.object(AsyncSession, "execute", side_effect=RuntimeError("Database failure")):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db"] == "disconnected"


@pytest.mark.asyncio
async def test_health_root_dashboard_redirect_or_html(client: AsyncClient):
    """Verify that GET / returns the dashboard HTML or JSON status."""
    resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cors_headers_present_on_cross_origin_requests(client: AsyncClient):
    """Verify that CORS response headers are properly populated for browser clients."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Origin": "https://dashboard.example.com"},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers

