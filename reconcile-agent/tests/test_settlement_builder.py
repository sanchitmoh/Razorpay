from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.settlement_builder import SettlementBuilderAgent
from app.models.batch import Batch
from app.models.enums import BatchStatus
from app.models.payment import Payment


@pytest.mark.asyncio
async def test_settlement_builder_daily_grouping(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    batch = Batch(id=batch_id, idempotency_key="test_key_1", status=BatchStatus.INGESTED)
    db_session.add(batch)
    await db_session.commit()

    # Create 3 payments on Day 1 and 2 payments on Day 2
    dt1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)

    p1 = Payment(id="pay_001", order_id="order_001", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt1)
    p2 = Payment(id="pay_002", order_id="order_002", amount_paise=20000, fee_paise=400, tax_paise=72, status="captured", captured_at=dt1)
    p3 = Payment(id="pay_003", order_id="order_003", amount_paise=30000, fee_paise=600, tax_paise=108, status="captured", captured_at=dt1)
    p4 = Payment(id="pay_004", order_id="order_004", amount_paise=15000, fee_paise=300, tax_paise=54, status="captured", captured_at=dt2)
    p5 = Payment(id="pay_005", order_id="order_005", amount_paise=25000, fee_paise=500, tax_paise=90, status="captured", captured_at=dt2)

    db_session.add_all([p1, p2, p3, p4, p5])
    await db_session.commit()

    builder = SettlementBuilderAgent()
    settlements, lines = await builder.build(batch_id, [p1, p2, p3, p4, p5], db_session)

    assert len(settlements) == 2
    assert len(lines) == 5

    # Day 1: 10000 + 20000 + 30000 = 60000 gross
    s1 = next(s for s in settlements if s.settlement_date.day == 1)
    assert s1.gross_amount_paise == 60000
    assert s1.fee_paise == 1200
    assert s1.tax_paise == 216
    assert s1.net_amount_paise == 60000 - 1200 - 216
    assert s1.utr == "UTR20260801001"

    # Day 2: 15000 + 25000 = 40000 gross
    s2 = next(s for s in settlements if s.settlement_date.day == 2)
    assert s2.gross_amount_paise == 40000
    assert s2.fee_paise == 800
    assert s2.tax_paise == 144
    assert s2.net_amount_paise == 40000 - 800 - 144
    assert s2.utr == "UTR20260802001"


@pytest.mark.asyncio
async def test_settlement_net_amount_invariant():
    """Verify that Settlement model hard asserts net_amount_paise == gross - fee - tax + adjustment."""
    from app.models.settlement import Settlement
    import datetime

    # Wrong net amount should raise ValueError
    with pytest.raises(ValueError, match="net_amount_paise must strictly equal"):
        Settlement(
            id=uuid.uuid4(),
            batch_id=uuid.uuid4(),
            utr="UTR_TEST_BAD",
            gross_amount_paise=10000,
            fee_paise=200,
            tax_paise=36,
            adjustment_paise=0,
            net_amount_paise=9999,  # Incorrect! (should be 9764)
            settlement_date=datetime.date(2026, 8, 1),
        )
