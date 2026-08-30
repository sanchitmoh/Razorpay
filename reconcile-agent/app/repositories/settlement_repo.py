from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settlement import Settlement
from app.models.settlement_line import SettlementLine


class SettlementRepo:
    @staticmethod
    async def bulk_insert_with_lines(
        db: AsyncSession,
        settlements: list[Settlement],
        lines: list[SettlementLine],
    ) -> None:
        db.add_all(settlements)
        db.add_all(lines)
        await db.commit()

    @staticmethod
    async def get_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[Settlement]:
        stmt = select(Settlement).where(Settlement.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_lines_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[SettlementLine]:
        stmt = select(SettlementLine).where(SettlementLine.batch_id == batch_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_utr(db: AsyncSession, batch_id: uuid.UUID, utr: str) -> Settlement | None:
        stmt = select(Settlement).where(
            Settlement.batch_id == batch_id,
            Settlement.utr == utr,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> None:
        from sqlalchemy import delete
        await db.execute(delete(SettlementLine).where(SettlementLine.batch_id == batch_id))
        await db.execute(delete(Settlement).where(Settlement.batch_id == batch_id))
        await db.commit()
