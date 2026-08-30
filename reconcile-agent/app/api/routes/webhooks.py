from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.webhook_processor import WebhookProcessor
from app.core.config import settings
from app.core.security import rate_limiter, verify_api_key
from app.db.database import get_db
from app.repositories.webhook_event_repo import WebhookEventRepo
from app.schemas.responses import APIMetadata, build_metadata_from_request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_razorpay_webhook_signature(
    request_body: bytes,
    signature_header: str,
    webhook_secret: str,
) -> bool:
    """
    Constant-time verification of Razorpay HMAC-SHA256 signature (§12.4).
    Fails closed: returns False if secret or signature is missing.
    """
    if not webhook_secret or not signature_header:
        return False

    expected_signature = hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=request_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


class WebhookResponse(BaseModel):
    status: str = "received"
    event_id: str | None = None
    event_type: str | None = None
    payment_ingested: bool = False
    batch_triggered: bool = False
    batch_id: str | None = None
    metadata: APIMetadata | None = None


class WebhookStatsResponse(BaseModel):
    total_events: int
    counts_by_status: dict[str, int]
    recent_events: list[dict[str, Any]]
    metadata: APIMetadata | None = None


@router.post(
    "/razorpay",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter)],
    summary="Receive and process Razorpay webhook notifications (§12.4)",
)
async def handle_razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # 1. Fail closed if webhook secret is not configured (§12.4, VULN-001)
    if not settings.razorpay_webhook_secret:
        logger.error("Webhook received but RAZORPAY_WEBHOOK_SECRET is unconfigured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "UNCONFIGURED_WEBHOOK_SECRET",
                    "message": "Webhook endpoint unconfigured: RAZORPAY_WEBHOOK_SECRET is not set",
                }
            },
        )

    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # 2. Verify HMAC-SHA256 signature (constant-time check)
    is_valid = verify_razorpay_webhook_signature(
        request_body=body,
        signature_header=signature,
        webhook_secret=settings.razorpay_webhook_secret,
    )
    if not is_valid:
        logger.warning(
            "Invalid or missing webhook signature received from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_SIGNATURE",
                    "message": "Invalid webhook signature",
                }
            },
        )

    # 3. Parse JSON payload
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception as e:
        logger.error("Failed to parse webhook JSON body: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MALFORMED_JSON",
                    "message": "Malformed JSON body",
                }
            },
        )

    # 4. Process event through WebhookProcessor
    processor = WebhookProcessor()
    event_rec, is_new_payment = await processor.process_event(payload, db)

    # 5. Check micro-batch trigger
    batch_triggered = False
    batch_id_str = None
    if is_new_payment:
        triggered, report, micro_batch_id = await processor.maybe_trigger_micro_batch(db)
        if triggered and micro_batch_id:
            batch_triggered = True
            batch_id_str = str(micro_batch_id)

    meta = build_metadata_from_request(request)
    return WebhookResponse(
        status="received",
        event_id=event_rec.razorpay_event_id,
        event_type=event_rec.event_type,
        payment_ingested=is_new_payment,
        batch_triggered=batch_triggered,
        batch_id=batch_id_str,
        metadata=meta,
    )


@router.get(
    "/stats",
    response_model=WebhookStatsResponse,
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Get webhook ingestion statistics",
)
async def get_webhook_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    counts = await WebhookEventRepo.count_by_status(db)
    recent = await WebhookEventRepo.get_recent(db, limit=10)
    total = sum(counts.values())

    recent_list = [
        {
            "id": str(e.id),
            "event_id": e.razorpay_event_id,
            "event_type": e.event_type,
            "status": e.status.value if hasattr(e.status, "value") else str(e.status),
            "received_at": e.received_at.isoformat() if e.received_at else None,
        }
        for e in recent
    ]

    meta = build_metadata_from_request(request)
    return WebhookStatsResponse(
        total_events=total,
        counts_by_status=counts,
        recent_events=recent_list,
        metadata=meta,
    )
