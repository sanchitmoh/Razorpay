from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.settlement import Settlement
from app.models.settlement_line import SettlementLine
from app.repositories.settlement_repo import SettlementRepo

logger = logging.getLogger(__name__)


class SettlementBuilderAgent:
    """
    Groups payments into synthetic Settlements per the domain grouping rule (§3).
    Since Razorpay's test mode has no live settlement data, we deterministically
    group payments captured on the same calendar day into one synthetic Settlement.
    """

    @staticmethod
    def group_payments_by_day(
        payments: Sequence[Payment],
    ) -> dict[date, list[Payment]]:
        grouped: dict[date, list[Payment]] = defaultdict(list)
        for p in payments:
            if p.captured_at is not None:
                p_date = p.captured_at.astimezone(timezone.utc).date()
            else:
                p_date = date.today()
            grouped[p_date].append(p)
        return dict(grouped)

    async def build(
        self,
        batch_id: uuid.UUID,
        payments: Sequence[Payment],
        db: AsyncSession,
    ) -> tuple[list[Settlement], list[SettlementLine]]:
        """
        Groups payments by calendar day, builds Settlement and SettlementLine records,
        and persists them atomically into PostgreSQL / SQLite.
        """
        grouped = self.group_payments_by_day(payments)
        settlements: list[Settlement] = []
        settlement_lines: list[SettlementLine] = []

        for p_date, day_payments in sorted(grouped.items(), key=lambda x: x[0]):
            gross = sum(p.amount_paise for p in day_payments)
            fee = sum(p.fee_paise for p in day_payments)
            tax = sum(p.tax_paise for p in day_payments)
            adjustment = 0
            net = gross - fee - tax + adjustment

            # Format UTR deterministically to match synthetic bank statement (§3)
            utr_date_str = p_date.strftime("%Y%m%d")
            utr = f"UTR{utr_date_str}001"

            settlement_id = uuid.uuid4()
            settlement = Settlement(
                id=settlement_id,
                batch_id=batch_id,
                razorpay_settlement_id=f"setl_synth_{utr}",
                utr=utr,
                gross_amount_paise=gross,
                fee_paise=fee,
                tax_paise=tax,
                adjustment_paise=adjustment,
                net_amount_paise=net,
                settlement_date=p_date,
            )
            settlements.append(settlement)

            for p in day_payments:
                if p.amount_paise <= 0:
                    raise ValueError(f"Payment {p.id} has non-positive allocation: {p.amount_paise}")

                line = SettlementLine(
                    id=uuid.uuid4(),
                    batch_id=batch_id,
                    settlement_id=settlement_id,
                    payment_id=p.id,
                    allocated_amount_paise=p.amount_paise,
                )
                settlement_lines.append(line)

        await SettlementRepo.bulk_insert_with_lines(db, settlements, settlement_lines)
        logger.info(
            "Batch %s: Built %d settlements with %d settlement lines",
            batch_id,
            len(settlements),
            len(settlement_lines),
        )
        return settlements, settlement_lines
