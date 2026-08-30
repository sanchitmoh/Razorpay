from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check — confirms service, database, and system status",
)
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Health check — returns service status, uptime, DB connectivity, and component health."""
    db_status = "disconnected"
    overall_status = "ok"

    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        overall_status = "degraded"
        db_status = "disconnected"

    start_time = getattr(request.app.state, "start_time", None)
    uptime = round(time.time() - start_time, 2) if start_time else None

    return HealthResponse(
        status=overall_status,
        db=db_status,
        version="1.0.0",
        uptime_seconds=uptime,
        checks={
            "database": db_status,
            "api": "operational",
        },
    )
