from __future__ import annotations

import uuid
from datetime import date
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BankEntry(Base):
    __tablename__ = "bank_entry"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("batch.id"), nullable=False, index=True)
    utr: Mapped[str] = mapped_column(index=True, nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    value_date: Mapped[date] = mapped_column(nullable=False)
    narration: Mapped[str | None] = mapped_column(nullable=True)
