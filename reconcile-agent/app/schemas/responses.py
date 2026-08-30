from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIMetadata(BaseModel):
    """Standard metadata attached to every API response."""

    request_id: str = Field(..., description="Unique request identifier for tracing")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the response",
    )
    version: str = Field(default="1.0.0", description="API version")
    duration_ms: float | None = Field(
        default=None, description="Server-side processing time in milliseconds"
    )


class APIErrorDetail(BaseModel):
    """Structured error detail."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    field: str | None = Field(default=None, description="Field that caused the error, if applicable")


class APIErrorResponse(BaseModel):
    """Standardised error envelope returned by all endpoints."""

    error: APIErrorDetail
    metadata: APIMetadata


class WrappedResponse(BaseModel, Generic[T]):
    """Generic success envelope wrapping any data payload with metadata."""

    data: T
    metadata: APIMetadata


# ---------------------------------------------------------------------------
# Helper to build metadata from a FastAPI Request object
# ---------------------------------------------------------------------------


def build_metadata_from_request(request) -> APIMetadata:
    """
    Construct an ``APIMetadata`` from a Starlette/FastAPI ``Request``.
    Falls back gracefully when middleware hasn't populated state attributes.
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    duration_ms = getattr(request.state, "duration_ms", None)
    return APIMetadata(
        request_id=request_id,
        duration_ms=duration_ms,
    )
