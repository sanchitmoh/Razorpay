from __future__ import annotations
import uuid
from datetime import date
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

class Settlement(Base):
    __tablename__ = "settlement"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("batch.id"), nullable=False)
    razorpay_settlement_id: Mapped[str | None] = mapped_column(nullable=True)
    utr: Mapped[str] = mapped_column(index=True, nullable=False)
    gross_amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    fee_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tax_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    adjustment_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    net_amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    settlement_date: Mapped[date] = mapped_column(nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.net_amount_paise != (self.gross_amount_paise - self.fee_paise - self.tax_paise + self.adjustment_paise):
            raise ValueError("net_amount_paise must strictly equal gross_amount_paise - fee_paise - tax_paise + adjustment_paise")
