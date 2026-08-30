from __future__ import annotations
import uuid
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

class SettlementLine(Base):
    __tablename__ = "settlement_line"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("batch.id"), nullable=False)
    settlement_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("settlement.id"), nullable=False)
    payment_id: Mapped[str] = mapped_column(sa.ForeignKey("payment.id"), nullable=False)
    allocated_amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("batch_id", "payment_id", name="uq_settlement_line_batch_payment"),
        sa.CheckConstraint("allocated_amount_paise > 0", name="ck_positive_allocation"),
    )
