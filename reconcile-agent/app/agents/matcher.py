from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_entry import BankEntry
from app.models.enums import Decision, MatchMethod, ReasonCode, ResultScope
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.models.settlement import Settlement
from app.models.settlement_line import SettlementLine
from app.repositories.bank_entry_repo import BankEntryRepo
from app.repositories.ledger_repo import LedgerRepo
from app.repositories.payment_repo import PaymentRepo
from app.repositories.settlement_repo import SettlementRepo

logger = logging.getLogger(__name__)

MATCHER_VERSION = "v1"
ROUNDING_TOLERANCE_PAISE = 200  # ₹2.00 rounding band allowance (§14)


@dataclass
class MatchCandidate:
    payment_id: str | None
    settlement_id: uuid.UUID | None
    bank_entry_id: uuid.UUID | None
    ledger_entry_id: uuid.UUID | None
    result_scope: ResultScope
    proposed_decision: Decision
    proposed_match_method: str | None
    proposed_reason_code: str | None
    expected_amount_paise: int | None = None
    actual_amount_paise: int | None = None
    difference_paise: int | None = None
    needs_llm: bool = False
    narration: str | None = None


class MatcherAgent:
    """
    Three-stage reconciliation matcher operating at the Payment grain (§4, §14):
      Stage 1: Identity match (Settlement UTR <-> Bank UTR, Payment order_id <-> Ledger order_id)
      Stage 2: Amount equation match (Gross - Fees - Tax + Adj vs Bank Amount, with classified bands)
      Stage 3: Residual & Orphan Bank Entry detection
    All queries are strictly scoped to the batch_id to avoid cross-batch contamination.
    """

    async def run_match(
        self,
        batch_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[MatchCandidate]:
        # 1. Fetch data strictly for this batch (§4, §11)
        settlements = await SettlementRepo.get_by_batch(db, batch_id)
        settlement_lines = await SettlementRepo.get_lines_by_batch(db, batch_id)
        all_bank_entries = await BankEntryRepo.get_by_batch(db, batch_id)
        duplicate_utrs = await BankEntryRepo.find_duplicate_utrs(db, batch_id)
        
        # Build indexes for fast lookups
        settlement_map = {s.id: s for s in settlements}
        settlement_by_utr = {s.utr: s for s in settlements}
        
        # Group bank entries by UTR
        bank_by_utr: dict[str, list[BankEntry]] = {}
        for be in all_bank_entries:
            bank_by_utr.setdefault(be.utr, []).append(be)

        # Get unique payment IDs
        payment_ids = [line.payment_id for line in settlement_lines]
        payments = await PaymentRepo.get_by_ids(db, payment_ids)
        payment_map = {p.id: p for p in payments}

        # Fetch ledger entries for all order IDs within this batch
        order_ids = [p.order_id for p in payments if p.order_id]
        ledger_entries = await LedgerRepo.get_by_order_ids(db, batch_id, order_ids)
        ledger_by_order = {l.order_id: l for l in ledger_entries}

        # Track which bank entries are matched
        matched_bank_entry_ids: set[uuid.UUID] = set()
        candidates: list[MatchCandidate] = []

        # 2. Iterate through each Payment allocated via SettlementLine (Payment grain §4)
        for line in settlement_lines:
            payment = payment_map.get(line.payment_id)
            if not payment:
                continue

            settlement = settlement_map.get(line.settlement_id)
            ledger_entry = ledger_by_order.get(payment.order_id)
            ledger_entry_id = ledger_entry.id if ledger_entry else None

            if not settlement:
                # Missing settlement record
                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=None,
                        bank_entry_id=None,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.MISSING_SETTLEMENT.value,
                    )
                )
                continue

            utr = settlement.utr
            bank_matches = bank_by_utr.get(utr, [])

            # Check 1: Duplicate UTR in bank statements for this batch (§6, L-5)
            if utr in duplicate_utrs or len(bank_matches) > 1:
                for be in bank_matches:
                    matched_bank_entry_ids.add(be.id)
                first_be = bank_matches[0] if bank_matches else None
                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=first_be.id if first_be else None,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.DUPLICATE_UTR.value,
                    )
                )
                continue

            # Check 2: Missing Bank Entry for this settlement
            if not bank_matches:
                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=None,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.MISSING_BANK_ENTRY.value,
                    )
                )
                continue

            # Check 3: Unique Bank Entry found -> Stage 2 Amount Equation Check (§14)
            bank_entry = bank_matches[0]
            matched_bank_entry_ids.add(bank_entry.id)

            expected_net = (
                settlement.gross_amount_paise
                - settlement.fee_paise
                - settlement.tax_paise
                + settlement.adjustment_paise
            )
            actual_amount = bank_entry.amount_paise
            diff = actual_amount - expected_net

            # Check ledger side match (§4, §14 - Three-way match requires ledger amount equality)
            has_ledger_entry = ledger_entry is not None
            ledger_amount_matches = (
                has_ledger_entry
                and ledger_entry.expected_amount_paise == payment.amount_paise
            )

            if diff == 0:
                # Exact bank amount match
                if not has_ledger_entry:
                    decision = Decision.EXCEPTION
                    reason = ReasonCode.UNRESOLVED_AMBIGUOUS.value
                    method = None
                elif not ledger_amount_matches:
                    decision = Decision.EXCEPTION
                    reason = ReasonCode.AMOUNT_MISMATCH.value
                    method = None
                else:
                    decision = Decision.MATCH
                    reason = None
                    method = MatchMethod.EXACT_UTR.value

                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=bank_entry.id,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=decision,
                        proposed_match_method=method,
                        proposed_reason_code=reason,
                        expected_amount_paise=expected_net,
                        actual_amount_paise=actual_amount,
                        difference_paise=diff if (has_ledger_entry and ledger_amount_matches) else (payment.amount_paise - (ledger_entry.expected_amount_paise if ledger_entry else 0)),
                    )
                )
            elif abs(diff) <= ROUNDING_TOLERANCE_PAISE:
                # Within rounding allowance (§14) -> ROUNDING_MATCH
                if not has_ledger_entry:
                    decision = Decision.EXCEPTION
                    reason = ReasonCode.UNRESOLVED_AMBIGUOUS.value
                    method = None
                elif not ledger_amount_matches:
                    decision = Decision.EXCEPTION
                    reason = ReasonCode.AMOUNT_MISMATCH.value
                    method = None
                else:
                    decision = Decision.MATCH
                    reason = None
                    method = MatchMethod.AMOUNT_WITH_FEE_EQUATION.value

                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=bank_entry.id,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=decision,
                        proposed_match_method=method,
                        proposed_reason_code=reason,
                        expected_amount_paise=expected_net,
                        actual_amount_paise=actual_amount,
                        difference_paise=diff if (has_ledger_entry and ledger_amount_matches) else (payment.amount_paise - (ledger_entry.expected_amount_paise if ledger_entry else 0)),
                    )
                )
            elif 0 < actual_amount < (expected_net - ROUNDING_TOLERANCE_PAISE):
                # Shortfall -> PARTIAL_SETTLEMENT
                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=bank_entry.id,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.PARTIAL_SETTLEMENT.value,
                        expected_amount_paise=expected_net,
                        actual_amount_paise=actual_amount,
                        difference_paise=diff,
                    )
                )
            else:
                # Unexplained variance -> AMOUNT_MISMATCH
                candidates.append(
                    MatchCandidate(
                        payment_id=payment.id,
                        settlement_id=settlement.id,
                        bank_entry_id=bank_entry.id,
                        ledger_entry_id=ledger_entry_id,
                        result_scope=ResultScope.PAYMENT,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.AMOUNT_MISMATCH.value,
                        expected_amount_paise=expected_net,
                        actual_amount_paise=actual_amount,
                        difference_paise=diff,
                    )
                )

        # 3. Stage 3: Detect Orphan Bank Entries strictly for this batch
        for be in all_bank_entries:
            if be.id not in matched_bank_entry_ids and be.utr not in settlement_by_utr:
                needs_llm = bool(be.narration)
                candidates.append(
                    MatchCandidate(
                        payment_id=None,
                        settlement_id=None,
                        bank_entry_id=be.id,
                        ledger_entry_id=None,
                        result_scope=ResultScope.ORPHAN_BANK_ENTRY,
                        proposed_decision=Decision.EXCEPTION,
                        proposed_match_method=None,
                        proposed_reason_code=ReasonCode.MISSING_SETTLEMENT.value,
                        expected_amount_paise=0,
                        actual_amount_paise=be.amount_paise,
                        difference_paise=be.amount_paise,
                        needs_llm=needs_llm,
                        narration=be.narration,
                    )
                )

        logger.info(
            "Batch %s: Matcher produced %d candidate decisions",
            batch_id,
            len(candidates),
        )
        return candidates
