from __future__ import annotations

import uuid
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.enums import WebhookEventStatus


class WebhookEvent(Base):
    __tablename__ = "webhook_event"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    razorpay_event_id: Mapped[str] = mapped_column(sa.String, unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    payload_json: Mapped[str] = mapped_column(sa.Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    status: Mapped[WebhookEventStatus] = mapped_column(sa.Enum(WebhookEventStatus), default=WebhookEventStatus.PROCESSED)
