from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ingestion import parse_razorpay_payment_dict
from app.agents.orchestrator import BatchOrchestrator
from app.agents.reporter import BatchReport
from app.core.config import settings
from app.models.enums import BatchStatus, WebhookEventStatus
from app.models.payment import Payment
from app.models.reconciliation_result import ReconciliationResult
from app.models.webhook_event import WebhookEvent
from app.repositories.batch_repo import BatchRepo
from app.repositories.payment_repo import PaymentRepo
from app.repositories.webhook_event_repo import WebhookEventRepo

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """
    Handles Razorpay push notifications (webhooks):
      1. Idempotent processing of payment.captured events
      2. Logging to webhook_event audit table
      3. Threshold-based micro-batch trigger for near-real-time reconciliation (§12.4)
    """

    async def process_event(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> tuple[WebhookEvent, bool]:
        """
        Processes a raw webhook payload:
          - Extracts event ID and event type
          - Deduplicates against webhook_event table
          - Upserts Payment if event is payment.captured
          - Returns (event_record, is_new_captured_payment)
        """
        event_id = payload.get("event_id") or payload.get("id") or str(uuid.uuid4())
        event_type = payload.get("event") or "unknown"
        payload_str = json.dumps(payload)

        # 1. Dedup check
        if await WebhookEventRepo.exists(db, event_id):
            logger.info("Duplicate webhook event %s received, skipping.", event_id)
            existing = await WebhookEventRepo.get_by_event_id(db, event_id)
            return existing or WebhookEvent(
                id=uuid.uuid4(),
                razorpay_event_id=event_id,
                event_type=event_type,
                payload_json=payload_str,
                status=WebhookEventStatus.SKIPPED_DUPLICATE,
            ), False

        # 2. Check if event is payment.captured
        if event_type != "payment.captured":
            logger.info("Webhook event %s is unhandled type '%s', recording as skipped.", event_id, event_type)
            event_rec = await WebhookEventRepo.create(
                db=db,
                razorpay_event_id=event_id,
                event_type=event_type,
                payload_json=payload_str,
                status=WebhookEventStatus.SKIPPED_UNHANDLED,
            )
            return event_rec, False

        # 3. Extract and upsert payment entity
        try:
            payment_data = payload.get("payload", {}).get("payment", {}).get("entity")
            if not payment_data:
                # Top level fallback
                payment_data = payload.get("payment") or payload

            payment_model = parse_razorpay_payment_dict(payment_data)
            await PaymentRepo.bulk_upsert(db, [payment_model])

            event_rec = await WebhookEventRepo.create(
                db=db,
                razorpay_event_id=event_id,
                event_type=event_type,
                payload_json=payload_str,
                status=WebhookEventStatus.PROCESSED,
            )
            logger.info("Successfully ingested payment %s via webhook %s", payment_model.id, event_id)
            return event_rec, True

        except Exception as e:
            logger.exception("Failed to process payment entity from webhook %s: %s", event_id, str(e))
            event_rec = await WebhookEventRepo.create(
                db=db,
                razorpay_event_id=event_id,
                event_type=event_type,
                payload_json=payload_str,
                status=WebhookEventStatus.FAILED,
            )
            return event_rec, False

    async def maybe_trigger_micro_batch(
        self,
        db: AsyncSession,
    ) -> tuple[bool, BatchReport | None, uuid.UUID | None]:
        """
        Evaluates whether accumulated unreconciled payments meet the micro-batch threshold.
        If threshold reached, triggers a batch reconciliation run using available bank & ledger datasets.
        """
        threshold = settings.webhook_micro_batch_threshold
        if threshold <= 0:
            return False, None, None

        # Count unreconciled payments (payments with no reconciliation_result)
        subq = select(ReconciliationResult.payment_id).where(ReconciliationResult.payment_id.is_not(None))
        stmt = select(func.count(Payment.id)).where(Payment.id.not_in(subq))
        res = await db.execute(stmt)
        unreconciled_count = res.scalar_one_or_none() or 0

        logger.info("Unreconciled payments count: %d (threshold: %d)", unreconciled_count, threshold)

        if unreconciled_count < threshold:
            return False, None, None

        # Threshold reached: Load bank and ledger data
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        bank_csv_path = os.path.join(base_dir, "data", "synthetic_bank_statement.csv")
        ledger_csv_path = os.path.join(base_dir, "data", "synthetic_ledger.csv")

        if not os.path.exists(bank_csv_path) or not os.path.exists(ledger_csv_path):
            logger.warning("Cannot trigger micro-batch: bank or ledger CSV files not found in data/")
            return False, None, None

        with open(bank_csv_path, "rb") as fb, open(ledger_csv_path, "rb") as fl:
            bank_bytes = fb.read()
            ledger_bytes = fl.read()

        # Create new micro-batch
        idempotency_key = f"webhook_micro_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        batch, _ = await BatchRepo.create(db, idempotency_key)

        logger.info("Triggering webhook micro-batch %s for %d unreconciled payments", batch.id, unreconciled_count)
        orchestrator = BatchOrchestrator()
        try:
            report = await orchestrator.run_pipeline(
                batch_id=batch.id,
                bank_csv_content=bank_bytes,
                ledger_csv_content=ledger_bytes,
                db=db,
            )
            return True, report, batch.id
        except Exception as e:
            logger.exception("Webhook micro-batch %s failed: %s", batch.id, str(e))
            return False, None, batch.id
