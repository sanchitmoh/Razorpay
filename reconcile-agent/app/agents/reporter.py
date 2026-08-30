from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Decision, ResultScope
from app.models.payment import Payment
from app.models.reconciliation_result import ReconciliationResult
from app.models.settlement_line import SettlementLine

logger = logging.getLogger(__name__)


@dataclass
class BatchReport:
    batch_id: uuid.UUID
    total_records: int
    matched_records: int
    exception_count: int
    record_match_rate: float
    amount_coverage: float
    total_payment_amount_paise: int
    matched_payment_amount_paise: int
    reason_code_breakdown: dict[str, int] = field(default_factory=dict)
    match_method_breakdown: dict[str, int] = field(default_factory=dict)
    scope_breakdown: dict[str, int] = field(default_factory=dict)


class ReporterAgent:
    """
    Computes reconciliation accuracy and coverage metrics for a batch (§10).
    Dual metric: record_match_rate AND amount_coverage (anchored on Payment gross amount).
    """

    async def generate_report(
        self,
        batch_id: uuid.UUID,
        db: AsyncSession,
    ) -> BatchReport:
        # 1. Fetch all reconciliation results for the batch
        res_stmt = select(ReconciliationResult).where(ReconciliationResult.batch_id == batch_id)
        results = list((await db.execute(res_stmt)).scalars().all())

        # 2. Fetch all payments linked to this batch via settlement lines
        line_stmt = select(SettlementLine).where(SettlementLine.batch_id == batch_id)
        lines = list((await db.execute(line_stmt)).scalars().all())
        payment_ids = [line.payment_id for line in lines]

        payments: list[Payment] = []
        if payment_ids:
            pay_stmt = select(Payment).where(Payment.id.in_(payment_ids))
            payments = list((await db.execute(pay_stmt)).scalars().all())

        payment_amount_map = {p.id: p.amount_paise for p in payments}
        total_payment_amount = sum(payment_amount_map.values())

        total_records = len(results)
        matched_records = sum(1 for r in results if r.decision == Decision.MATCH)
        exception_count = sum(1 for r in results if r.decision == Decision.EXCEPTION)

        # Compute amount coverage on Payment gross amount (§10)
        matched_payment_amount = 0
        reason_breakdown: dict[str, int] = {}
        method_breakdown: dict[str, int] = {}
        scope_breakdown: dict[str, int] = {}

        for r in results:
            # Scope breakdown
            scope_key = r.result_scope.value if hasattr(r.result_scope, "value") else str(r.result_scope)
            scope_breakdown[scope_key] = scope_breakdown.get(scope_key, 0) + 1

            if r.decision == Decision.MATCH:
                if r.payment_id and r.payment_id in payment_amount_map:
                    matched_payment_amount += payment_amount_map[r.payment_id]
                if r.match_method:
                    method_breakdown[r.match_method] = method_breakdown.get(r.match_method, 0) + 1
            elif r.decision == Decision.EXCEPTION:
                if r.reason_code:
                    reason_breakdown[r.reason_code] = reason_breakdown.get(r.reason_code, 0) + 1

        record_match_rate = (matched_records / total_records) if total_records > 0 else 0.0
        amount_coverage = (
            (matched_payment_amount / total_payment_amount) if total_payment_amount > 0 else 0.0
        )

        report = BatchReport(
            batch_id=batch_id,
            total_records=total_records,
            matched_records=matched_records,
            exception_count=exception_count,
            record_match_rate=round(record_match_rate, 4),
            amount_coverage=round(amount_coverage, 4),
            total_payment_amount_paise=total_payment_amount,
            matched_payment_amount_paise=matched_payment_amount,
            reason_code_breakdown=reason_breakdown,
            match_method_breakdown=method_breakdown,
            scope_breakdown=scope_breakdown,
        )

        logger.info(
            "Batch %s summary: record_match_rate=%.2f%%, amount_coverage=%.2f%% (matched %d/%d records)",
            batch_id,
            record_match_rate * 100,
            amount_coverage * 100,
            matched_records,
            total_records,
        )
        return report
