from __future__ import annotations
import uuid
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.db.database import Base
from app.models.enums import BatchStatus

if TYPE_CHECKING:
    from app.models.reconciliation_result import ReconciliationResult

class Batch(Base):
    __tablename__ = "batch"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    status: Mapped[BatchStatus] = mapped_column(sa.Enum(BatchStatus), default=BatchStatus.CREATED)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    
    # Data quality metrics (US7, P3)
    duplicate_ledger_order_ids: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, default=0)
    skipped_rows: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, default=0)

    reconciliation_results: Mapped[list["ReconciliationResult"]] = relationship("ReconciliationResult")
