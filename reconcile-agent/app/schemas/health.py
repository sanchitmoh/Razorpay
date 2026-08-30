from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Enriched health-check response with version and component status."""

    status: str = Field(..., description="Overall service status: ok | degraded")
    db: str = Field(..., description="Database connection status")
    version: str = Field(default="1.0.0", description="API version")
    uptime_seconds: float | None = Field(
        default=None, description="Seconds since the service started"
    )
    checks: dict[str, str] | None = Field(
        default=None,
        description="Per-component health check results",
    )
