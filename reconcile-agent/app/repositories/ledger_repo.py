from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_entry import LedgerEntry


class LedgerRepo:
    @staticmethod
    async def bulk_insert(db: AsyncSession, entries: list[LedgerEntry]) -> None:
        db.add_all(entries)
        await db.commit()

    @staticmethod
    async def get_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[LedgerEntry]:
        stmt = select(LedgerEntry).where(LedgerEntry.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_order_id(db: AsyncSession, batch_id: uuid.UUID, order_id: str) -> LedgerEntry | None:
        stmt = select(LedgerEntry).where(
            LedgerEntry.batch_id == batch_id,
            LedgerEntry.order_id == order_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_order_ids(db: AsyncSession, batch_id: uuid.UUID, order_ids: list[str]) -> list[LedgerEntry]:
        if not order_ids:
            return []
        stmt = select(LedgerEntry).where(
            LedgerEntry.batch_id == batch_id,
            LedgerEntry.order_id.in_(order_ids),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all(db: AsyncSession, batch_id: uuid.UUID | None = None) -> list[LedgerEntry]:
        stmt = select(LedgerEntry)
        if batch_id is not None:
            stmt = stmt.where(LedgerEntry.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> None:
        from sqlalchemy import delete
        await db.execute(delete(LedgerEntry).where(LedgerEntry.batch_id == batch_id))
        await db.commit()
