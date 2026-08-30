from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ingestion import IngestionAgent, IngestionError
from app.agents.matcher import MatcherAgent
from app.agents.reporter import BatchReport, ReporterAgent
from app.agents.settlement_builder import SettlementBuilderAgent
from app.agents.validator import ValidatorAgent
from app.models.enums import BatchStatus
from app.repositories.bank_entry_repo import BankEntryRepo
from app.repositories.batch_repo import BatchRepo
from app.repositories.ledger_repo import LedgerRepo
from app.repositories.reconciliation_result_repo import ReconciliationResultRepo
from app.repositories.settlement_repo import SettlementRepo

logger = logging.getLogger(__name__)


class BatchOrchestrator:
    """
    Coordinates the full reconciliation pipeline across all service agents:
      Ingestion -> Settlement Builder -> Matcher -> Validator -> Reporter
    """

    def __init__(
        self,
        ingestion_agent: IngestionAgent | None = None,
        settlement_builder: SettlementBuilderAgent | None = None,
        matcher_agent: MatcherAgent | None = None,
        validator_agent: ValidatorAgent | None = None,
        reporter_agent: ReporterAgent | None = None,
    ) -> None:
        self.ingestion = ingestion_agent or IngestionAgent()
        self.settlement_builder = settlement_builder or SettlementBuilderAgent()
        self.matcher = matcher_agent or MatcherAgent()
        self.validator = validator_agent or ValidatorAgent()
        self.reporter = reporter_agent or ReporterAgent()

    async def cleanup_batch_data(self, batch_id: uuid.UUID, db: AsyncSession) -> None:
        """Atomically wipes any partial batch-scoped data to ensure clean idempotency / retry (§2, §6)."""
        await ReconciliationResultRepo.delete_by_batch(db, batch_id)
        await SettlementRepo.delete_by_batch(db, batch_id)
        await BankEntryRepo.delete_by_batch(db, batch_id)
        await LedgerRepo.delete_by_batch(db, batch_id)

    async def run_pipeline(
        self,
        batch_id: uuid.UUID,
        bank_csv_content: str | bytes,
        ledger_csv_content: str | bytes,
        db: AsyncSession,
    ) -> BatchReport:
        logger.info("Starting reconciliation pipeline for batch %s", batch_id)

        # 0. Ensure clean slate for this batch ID (cleans up any partial data from prior crashed/stuck runs)
        await self.cleanup_batch_data(batch_id, db)

        # 1. Ingestion: Pull payments and parse CSVs
        try:
            await BatchRepo.update_status(db, batch_id, BatchStatus.INGESTING)
            payments, bank_entries, ledger_entries = await self.ingestion.run(
                batch_id=batch_id,
                bank_csv_content=bank_csv_content,
                ledger_csv_content=ledger_csv_content,
                db=db,
            )
        except Exception:
            # Batch status already marked FAILED_INGESTION inside ingestion agent
            raise

        # 2. Settlement Construction: Group payments by calendar day
        try:
            settlements, lines = await self.settlement_builder.build(
                batch_id=batch_id,
                payments=payments,
                db=db,
            )
        except Exception as e:
            logger.exception("Settlement builder failed for batch %s: %s", batch_id, str(e))
            await BatchRepo.update_status(db, batch_id, BatchStatus.FAILED_RECONCILIATION)
            raise

        # 3. Matching & Validation
        try:
            await BatchRepo.update_status(db, batch_id, BatchStatus.RECONCILING)
            candidates = await self.matcher.run_match(batch_id=batch_id, db=db)
            await self.validator.validate_and_persist(
                candidates=candidates,
                batch_id=batch_id,
                db=db,
            )
            report = await self.reporter.generate_report(batch_id=batch_id, db=db)
            await BatchRepo.update_status(db, batch_id, BatchStatus.COMPLETED, completed=True)
            logger.info("Reconciliation pipeline completed successfully for batch %s", batch_id)
            return report

        except Exception as e:
            logger.exception("Reconciliation failed for batch %s: %s", batch_id, str(e))
            await BatchRepo.update_status(db, batch_id, BatchStatus.FAILED_RECONCILIATION)
            raise
