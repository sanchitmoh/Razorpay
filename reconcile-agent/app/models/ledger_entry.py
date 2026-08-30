from __future__ import annotations

import uuid
from datetime import date
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("batch.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(index=True, nullable=False)
    expected_amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    customer_ref: Mapped[str | None] = mapped_column(nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(nullable=True)
