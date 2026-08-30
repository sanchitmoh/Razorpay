from __future__ import annotations

import uuid
from typing import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import WebhookEventStatus
from app.models.webhook_event import WebhookEvent


class WebhookEventRepo:
    @staticmethod
    async def create(
        db: AsyncSession,
        razorpay_event_id: str,
        event_type: str,
        payload_json: str,
        status: WebhookEventStatus = WebhookEventStatus.PROCESSED,
    ) -> WebhookEvent:
        event = WebhookEvent(
            id=uuid.uuid4(),
            razorpay_event_id=razorpay_event_id,
            event_type=event_type,
            payload_json=payload_json,
            status=status,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def get_by_event_id(db: AsyncSession, razorpay_event_id: str) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(WebhookEvent.razorpay_event_id == razorpay_event_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def exists(db: AsyncSession, razorpay_event_id: str) -> bool:
        stmt = select(func.count(WebhookEvent.id)).where(WebhookEvent.razorpay_event_id == razorpay_event_id)
        result = await db.execute(stmt)
        count = result.scalar_one_or_none() or 0
        return count > 0

    @staticmethod
    async def get_recent(db: AsyncSession, limit: int = 50) -> Sequence[WebhookEvent]:
        stmt = select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def count_by_status(db: AsyncSession) -> dict[str, int]:
        stmt = select(WebhookEvent.status, func.count(WebhookEvent.id)).group_by(WebhookEvent.status)
        result = await db.execute(stmt)
        return {str(status.value if hasattr(status, "value") else status): count for status, count in result.all()}
