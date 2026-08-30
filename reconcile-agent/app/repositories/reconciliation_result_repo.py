from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_entry import BankEntry
from app.models.enums import Decision
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.models.reconciliation_result import ReconciliationResult
from app.models.settlement import Settlement


class ReconciliationResultRepo:
    @staticmethod
    async def bulk_insert(
        db: AsyncSession,
        results: list[ReconciliationResult],
    ) -> None:
        db.add_all(results)
        await db.commit()

    @staticmethod
    async def delete_by_batch(
        db: AsyncSession,
        batch_id: uuid.UUID,
    ) -> None:
        """Deletes all reconciliation result records for a given batch (§11)."""
        stmt = delete(ReconciliationResult).where(
            ReconciliationResult.batch_id == batch_id
        )
        await db.execute(stmt)
        await db.commit()

    @staticmethod
    async def get_by_batch(
        db: AsyncSession,
        batch_id: uuid.UUID,
    ) -> list[ReconciliationResult]:
        stmt = select(ReconciliationResult).where(
            ReconciliationResult.batch_id == batch_id
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_exceptions_paginated(
        db: AsyncSession,
        batch_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[ReconciliationResult, str | None, str | None, str | None]], int]:
        count_stmt = (
            select(func.count(ReconciliationResult.id))
            .where(
                ReconciliationResult.batch_id == batch_id,
                ReconciliationResult.decision == Decision.EXCEPTION,
            )
        )
        total = (await db.execute(count_stmt)).scalar_one() or 0

        query = (
            select(
                ReconciliationResult,
                Settlement.utr.label("settlement_utr"),
                BankEntry.utr.label("bank_entry_utr"),
                func.coalesce(LedgerEntry.order_id, Payment.order_id).label("ledger_order_id"),
            )
            .outerjoin(Settlement, ReconciliationResult.settlement_id == Settlement.id)
            .outerjoin(BankEntry, ReconciliationResult.bank_entry_id == BankEntry.id)
            .outerjoin(LedgerEntry, ReconciliationResult.ledger_entry_id == LedgerEntry.id)
            .outerjoin(Payment, ReconciliationResult.payment_id == Payment.id)
            .where(
                ReconciliationResult.batch_id == batch_id,
                ReconciliationResult.decision == Decision.EXCEPTION,
            )
            .order_by(ReconciliationResult.id)
            .limit(limit)
            .offset(offset)
        )
        items = (await db.execute(query)).all()
        return [(row[0], row[1], row[2], row[3]) for row in items], total

    @staticmethod
    async def get_matches_paginated(
        db: AsyncSession,
        batch_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[ReconciliationResult, str | None, str | None, str | None]], int]:
        count_stmt = (
            select(func.count(ReconciliationResult.id))
            .where(
                ReconciliationResult.batch_id == batch_id,
                ReconciliationResult.decision == Decision.MATCH,
            )
        )
        total = (await db.execute(count_stmt)).scalar_one() or 0

        query = (
            select(
                ReconciliationResult,
                Settlement.utr.label("settlement_utr"),
                BankEntry.utr.label("bank_entry_utr"),
                func.coalesce(LedgerEntry.order_id, Payment.order_id).label("ledger_order_id"),
            )
            .outerjoin(Settlement, ReconciliationResult.settlement_id == Settlement.id)
            .outerjoin(BankEntry, ReconciliationResult.bank_entry_id == BankEntry.id)
            .outerjoin(LedgerEntry, ReconciliationResult.ledger_entry_id == LedgerEntry.id)
            .outerjoin(Payment, ReconciliationResult.payment_id == Payment.id)
            .where(
                ReconciliationResult.batch_id == batch_id,
                ReconciliationResult.decision == Decision.MATCH,
            )
            .order_by(ReconciliationResult.id)
            .limit(limit)
            .offset(offset)
        )
        items = (await db.execute(query)).all()
        return [(row[0], row[1], row[2], row[3]) for row in items], total

    @staticmethod
    async def get_summary(
        db: AsyncSession,
        batch_id: uuid.UUID,
    ) -> dict[str, Any]:
        results = await ReconciliationResultRepo.get_by_batch(db, batch_id)
        total_records = len(results)
        matched_records = sum(1 for r in results if r.decision == Decision.MATCH)
        exception_count = sum(1 for r in results if r.decision == Decision.EXCEPTION)
        
        return {
            "total_records": total_records,
            "matched_records": matched_records,
            "exception_count": exception_count,
            "record_match_rate": (matched_records / total_records) if total_records > 0 else 0.0,
        }
