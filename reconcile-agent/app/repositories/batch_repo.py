from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch import Batch
from app.models.enums import BatchStatus


class BatchRepo:
    @staticmethod
    async def get_by_id(db: AsyncSession, batch_id: uuid.UUID) -> Batch | None:
        stmt = select(Batch).where(Batch.id == batch_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_idempotency_key(db: AsyncSession, idempotency_key: str) -> Batch | None:
        stmt = select(Batch).where(Batch.idempotency_key == idempotency_key)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, idempotency_key: str) -> tuple[Batch, bool]:
        """
        Creates a new batch or returns the existing one if idempotency_key already exists.
        Returns: (Batch, created: bool)
        """
        existing = await BatchRepo.get_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            return existing, False

        new_batch = Batch(
            id=uuid.uuid4(),
            idempotency_key=idempotency_key,
            status=BatchStatus.CREATED,
            started_at=datetime.now(timezone.utc),
        )
        db.add(new_batch)
        try:
            await db.commit()
            await db.refresh(new_batch)
            return new_batch, True
        except IntegrityError:
            await db.rollback()
            existing = await BatchRepo.get_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing, False
            raise

    @staticmethod
    async def update_status(
        db: AsyncSession,
        batch_id: uuid.UUID,
        status: BatchStatus,
        completed: bool = False,
    ) -> Batch | None:
        batch = await BatchRepo.get_by_id(db, batch_id)
        if batch:
            batch.status = status
            if completed or status in (
                BatchStatus.COMPLETED,
                BatchStatus.FAILED_INGESTION,
                BatchStatus.FAILED_RECONCILIATION,
            ):
                batch.completed_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(batch)
        return batch

    @staticmethod
    async def update_data_quality_metrics(
        db: AsyncSession,
        batch_id: uuid.UUID,
        duplicate_count: int,
        skipped_rows: int,
    ) -> Batch | None:
        """Update data quality metrics for a batch (US7, P3)"""
        batch = await BatchRepo.get_by_id(db, batch_id)
        if batch:
            batch.duplicate_ledger_order_ids = duplicate_count
            batch.skipped_rows = skipped_rows
            await db.commit()
            await db.refresh(batch)
        return batch
