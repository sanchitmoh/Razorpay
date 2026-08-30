from __future__ import annotations

import datetime
import uuid
from datetime import timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.matcher import MatcherAgent
from app.models.bank_entry import BankEntry
from app.models.batch import Batch
from app.models.enums import BatchStatus, Decision, MatchMethod, ReasonCode, ResultScope
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.models.settlement import Settlement
from app.models.settlement_line import SettlementLine


@pytest.mark.asyncio
async def test_matcher_exact_match(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_exact", status=BatchStatus.INGESTED))

    # Payment + Ledger entry
    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_exact_1", order_id="ord_exact_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_exact_1", expected_amount_paise=10000)
    db_session.add_all([payment, ledger])

    # Settlement
    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_EXACT_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    # Bank Entry
    bank = BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_EXACT_001",
        amount_paise=net,
        value_date=datetime.date(2026, 8, 1),
    )
    db_session.add_all([settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.MATCH
    assert c.proposed_match_method == MatchMethod.EXACT_UTR.value
    assert c.proposed_reason_code is None
    assert c.difference_paise == 0


@pytest.mark.asyncio
async def test_matcher_rounding_match(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_round", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_rnd_1", order_id="ord_rnd_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_rnd_1", expected_amount_paise=10000)
    
    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_RND_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    # Bank Entry has ₹1.50 difference (+150 paise)
    bank = BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_RND_001",
        amount_paise=net + 150,
        value_date=datetime.date(2026, 8, 1),
    )
    db_session.add_all([payment, ledger, settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.MATCH
    assert c.proposed_match_method == MatchMethod.AMOUNT_WITH_FEE_EQUATION.value
    assert c.difference_paise == 150


@pytest.mark.asyncio
async def test_matcher_partial_settlement(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_partial", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_part_1", order_id="ord_part_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_part_1", expected_amount_paise=10000)

    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_PART_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    # Bank Entry receives only 80% of net
    bank = BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_PART_001",
        amount_paise=int(net * 0.80),
        value_date=datetime.date(2026, 8, 1),
    )
    db_session.add_all([payment, ledger, settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.PARTIAL_SETTLEMENT.value


@pytest.mark.asyncio
async def test_matcher_duplicate_utr(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_dup", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_dup_1", order_id="ord_dup_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_dup_1", expected_amount_paise=10000)

    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_DUP_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    # Two Bank Entries with identical UTR
    b1 = BankEntry(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DUP_001", amount_paise=net, value_date=datetime.date(2026, 8, 1))
    b2 = BankEntry(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DUP_001", amount_paise=net, value_date=datetime.date(2026, 8, 1))
    db_session.add_all([payment, ledger, settlement, line, b1, b2])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.DUPLICATE_UTR.value
    # Crucial (L-5): Duplicate bank entry (b2) MUST NOT resurface as an orphan bank entry
    assert not any(cand.result_scope == ResultScope.ORPHAN_BANK_ENTRY for cand in candidates)


@pytest.mark.asyncio
async def test_matcher_missing_bank_entry(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_missing_b", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_mb_1", order_id="ord_mb_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_mb_1", expected_amount_paise=10000)

    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_MISSING_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    # NO bank entry added for UTR_MISSING_001
    db_session.add_all([payment, ledger, settlement, line])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.MISSING_BANK_ENTRY.value


@pytest.mark.asyncio
async def test_matcher_orphan_bank_entry(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_orphan", status=BatchStatus.INGESTED))

    # Bank entry with no payment or settlement behind it
    orphan = BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_ORPHAN_001",
        amount_paise=50000,
        value_date=datetime.date(2026, 8, 1),
        narration="Unsolicited Credit",
    )
    db_session.add(orphan)
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.result_scope == ResultScope.ORPHAN_BANK_ENTRY
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.MISSING_SETTLEMENT.value
    assert c.payment_id is None
    assert c.settlement_id is None
    assert c.bank_entry_id == orphan.id


@pytest.mark.asyncio
async def test_matcher_ledger_amount_mismatch(db_session: AsyncSession):
    """Verify that a payment with bank match but ledger expected amount mismatch fails as EXCEPTION / AMOUNT_MISMATCH (L-1)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="batch_ledger_mismatch", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_lm_1", order_id="ord_lm_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    # Ledger expects 12000 paise instead of 10000 paise
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_lm_1", expected_amount_paise=12000)

    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_LM_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=datetime.date(2026, 8, 1),
    )
    line = SettlementLine(
        id=uuid.uuid4(),
        batch_id=batch_id,
        settlement_id=settlement.id,
        payment_id=payment.id,
        allocated_amount_paise=10000,
    )
    bank = BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_LM_001",
        amount_paise=net,
        value_date=datetime.date(2026, 8, 1),
    )
    db_session.add_all([payment, ledger, settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.AMOUNT_MISMATCH.value

