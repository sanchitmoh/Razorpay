from __future__ import annotations
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

class Payment(Base):
    __tablename__ = "payment"

    id: Mapped[str] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(index=True, nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    fee_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tax_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
