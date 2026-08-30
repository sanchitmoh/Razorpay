from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment


class PaymentRepo:
    @staticmethod
    async def get_by_id(db: AsyncSession, payment_id: str) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids(db: AsyncSession, payment_ids: list[str]) -> list[Payment]:
        if not payment_ids:
            return []
        stmt = select(Payment).where(Payment.id.in_(payment_ids))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def bulk_upsert(db: AsyncSession, payments: list[Payment]) -> list[Payment]:
        for p in payments:
            existing = await PaymentRepo.get_by_id(db, p.id)
            if existing is None:
                db.add(p)
            else:
                existing.order_id = p.order_id
                existing.amount_paise = p.amount_paise
                existing.fee_paise = p.fee_paise
                existing.tax_paise = p.tax_paise
                existing.status = p.status
                existing.captured_at = p.captured_at
        await db.commit()
        return payments

    @staticmethod
    async def get_all_captured(db: AsyncSession) -> list[Payment]:
        stmt = select(Payment).where(Payment.status == "captured")
        result = await db.execute(stmt)
        return list(result.scalars().all())
