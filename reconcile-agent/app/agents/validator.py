from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_classifier import LLMClassifierAgent
from app.agents.matcher import MATCHER_VERSION, MatchCandidate
from app.models.enums import Decision, MatchMethod, ReasonCode, ResultScope
from app.models.reconciliation_result import ReconciliationResult
from app.repositories.ledger_repo import LedgerRepo
from app.repositories.reconciliation_result_repo import ReconciliationResultRepo
from app.repositories.settlement_repo import SettlementRepo

logger = logging.getLogger(__name__)


class ValidatorAgent:
    """
    Validation agent acting as the final authority on reconciliation decisions (§5.1, §14).
    Validates candidates, calls LLM classifier only on ambiguous residual narration cases,
    and deterministically re-verifies any LLM-extracted signals before persistence.
    Cleans up prior reconciliation results on batch retry to prevent double-counting.
    """

    def __init__(self, llm_classifier: LLMClassifierAgent | None = None) -> None:
        self.llm_classifier = llm_classifier or LLMClassifierAgent()

    async def validate_and_persist(
        self,
        candidates: Sequence[MatchCandidate],
        batch_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[ReconciliationResult]:
        results: list[ReconciliationResult] = []

        for c in candidates:
            decision = c.proposed_decision
            match_method = c.proposed_match_method
            reason_code = c.proposed_reason_code
            settlement_id = c.settlement_id
            payment_id = c.payment_id
            ledger_entry_id = c.ledger_entry_id
            bank_entry_id = c.bank_entry_id
            scope = c.result_scope

            # Check if ambiguous candidate has narration text needing LLM assistance (§5.1, L-4)
            extraction = None
            if c.needs_llm and c.narration:
                record_id = c.payment_id or str(c.bank_entry_id or "orphan")
                try:
                    extraction = await self.llm_classifier.extract_from_narration(
                        narration=c.narration,
                        record_id=record_id,
                    )
                except (TimeoutError, asyncio.TimeoutError, ConnectionError, ValueError) as e:
                    logger.warning("LLM extraction failed or timed out for record %s: %s", record_id, str(e))
                except Exception as e:
                    logger.warning("LLM extraction error for record %s: %s", record_id, str(e))

            if extraction and extraction.confidence in ("high", "medium"):
                # Deterministically verify LLM extracted candidate against DB (§5.1)
                if extraction.candidate_utr and not settlement_id:
                    settlement = await SettlementRepo.get_by_utr(
                        db, batch_id, extraction.candidate_utr
                    )
                    if settlement:
                        settlement_id = settlement.id
                        decision = Decision.MATCH
                        match_method = MatchMethod.LLM_ASSISTED_NARRATION.value
                        reason_code = None

                if extraction.candidate_order_id and not ledger_entry_id:
                    ledger_entry = await LedgerRepo.get_by_order_id(
                        db, batch_id, extraction.candidate_order_id
                    )
                    if ledger_entry:
                        ledger_entry_id = ledger_entry.id
                        decision = Decision.MATCH
                        match_method = MatchMethod.LLM_ASSISTED_NARRATION.value
                        reason_code = None

            results.append(
                ReconciliationResult(
                    id=uuid.uuid4(),
                    batch_id=batch_id,
                    result_scope=scope,
                    payment_id=payment_id,
                    settlement_id=settlement_id,
                    bank_entry_id=bank_entry_id,
                    ledger_entry_id=ledger_entry_id,
                    decision=decision,
                    match_method=match_method,
                    reason_code=reason_code,
                    matcher_version=MATCHER_VERSION,
                    expected_amount_paise=c.expected_amount_paise,
                    actual_amount_paise=c.actual_amount_paise,
                    difference_paise=c.difference_paise,
                )
            )

        # Clean up any prior/stale reconciliation results for this batch before persisting
        await ReconciliationResultRepo.delete_by_batch(db, batch_id)
        await ReconciliationResultRepo.bulk_insert(db, results)
        logger.info("Batch %s: Persisted %d reconciliation results", batch_id, len(results))
        return results
