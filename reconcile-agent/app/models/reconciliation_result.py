from __future__ import annotations
import uuid
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.enums import ResultScope, Decision

class ReconciliationResult(Base):
    __tablename__ = "reconciliation_result"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("batch.id"), nullable=False)
    result_scope: Mapped[ResultScope] = mapped_column(sa.Enum(ResultScope), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(sa.ForeignKey("payment.id"), nullable=True)
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("settlement.id"), nullable=True)
    bank_entry_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("bank_entry.id"), nullable=True)
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("ledger_entry.id"), nullable=True)
    decision: Mapped[Decision] = mapped_column(sa.Enum(Decision), nullable=False)
    match_method: Mapped[str | None] = mapped_column(nullable=True)
    reason_code: Mapped[str | None] = mapped_column(nullable=True)
    matcher_version: Mapped[str] = mapped_column(default="v1", nullable=False)
    expected_amount_paise: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    actual_amount_paise: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    difference_paise: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
