from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_entry import BankEntry


class BankEntryRepo:
    @staticmethod
    async def bulk_insert(db: AsyncSession, entries: list[BankEntry]) -> None:
        db.add_all(entries)
        await db.commit()

    @staticmethod
    async def get_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[BankEntry]:
        stmt = select(BankEntry).where(BankEntry.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all(db: AsyncSession, batch_id: uuid.UUID | None = None) -> list[BankEntry]:
        stmt = select(BankEntry)
        if batch_id is not None:
            stmt = stmt.where(BankEntry.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_utrs(db: AsyncSession, batch_id: uuid.UUID, utrs: list[str]) -> list[BankEntry]:
        if not utrs:
            return []
        stmt = select(BankEntry).where(
            BankEntry.batch_id == batch_id,
            BankEntry.utr.in_(utrs),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def find_duplicate_utrs(db: AsyncSession, batch_id: uuid.UUID) -> set[str]:
        """Finds any UTRs that appear more than once in the bank statements for a specific batch."""
        stmt = (
            select(BankEntry.utr)
            .where(BankEntry.batch_id == batch_id)
            .group_by(BankEntry.utr)
            .having(func.count(BankEntry.id) > 1)
        )
        result = await db.execute(stmt)
        return set(result.scalars().all())

    @staticmethod
    async def delete_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> None:
        from sqlalchemy import delete
        await db.execute(delete(BankEntry).where(BankEntry.batch_id == batch_id))
        await db.commit()
