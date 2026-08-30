from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_classifier import LLMClassifierAgent, NarrationExtraction
from app.agents.matcher import MatchCandidate
from app.agents.validator import ValidatorAgent
from app.models.batch import Batch
from app.models.enums import BatchStatus, Decision, MatchMethod, ReasonCode, ResultScope
from app.models.settlement import Settlement


@pytest.mark.asyncio
async def test_validator_persists_matches_and_exceptions(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="val_batch_1", status=BatchStatus.RECONCILING))
    await db_session.commit()

    candidates = [
        MatchCandidate(
            payment_id="pay_v1",
            settlement_id=uuid.uuid4(),
            bank_entry_id=uuid.uuid4(),
            ledger_entry_id=uuid.uuid4(),
            result_scope=ResultScope.PAYMENT,
            proposed_decision=Decision.MATCH,
            proposed_match_method=MatchMethod.EXACT_UTR.value,
            proposed_reason_code=None,
        ),
        MatchCandidate(
            payment_id="pay_v2",
            settlement_id=uuid.uuid4(),
            bank_entry_id=None,
            ledger_entry_id=uuid.uuid4(),
            result_scope=ResultScope.PAYMENT,
            proposed_decision=Decision.EXCEPTION,
            proposed_match_method=None,
            proposed_reason_code=ReasonCode.MISSING_BANK_ENTRY.value,
        ),
    ]

    validator = ValidatorAgent()
    results = await validator.validate_and_persist(candidates, batch_id, db_session)

    assert len(results) == 2
    r1 = next(r for r in results if r.payment_id == "pay_v1")
    assert r1.decision == Decision.MATCH
    assert r1.match_method == MatchMethod.EXACT_UTR.value

    r2 = next(r for r in results if r.payment_id == "pay_v2")
    assert r2.decision == Decision.EXCEPTION
    assert r2.reason_code == ReasonCode.MISSING_BANK_ENTRY.value


@pytest.mark.asyncio
async def test_validator_bounded_llm_call(db_session: AsyncSession):
    """Verify that LLM is only invoked on ambiguous narration candidates and cannot write directly without verification."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="val_batch_2", status=BatchStatus.RECONCILING))
    await db_session.commit()

    mock_classifier = AsyncMock(spec=LLMClassifierAgent)
    mock_classifier.extract_from_narration.return_value = NarrationExtraction(
        candidate_order_id="order_extracted_1",
        candidate_utr="UTR_EXTRACTED_1",
        confidence="high",
        reasoning="Found ref in narration",
    )

    validator = ValidatorAgent(llm_classifier=mock_classifier)

    # Candidate with needs_llm = False -> LLM should NOT be called
    c_deterministic = MatchCandidate(
        payment_id="pay_det",
        settlement_id=uuid.uuid4(),
        bank_entry_id=uuid.uuid4(),
        ledger_entry_id=uuid.uuid4(),
        result_scope=ResultScope.PAYMENT,
        proposed_decision=Decision.MATCH,
        proposed_match_method=MatchMethod.EXACT_UTR.value,
        proposed_reason_code=None,
        needs_llm=False,
    )

    await validator.validate_and_persist([c_deterministic], batch_id, db_session)
    mock_classifier.extract_from_narration.assert_not_called()


@pytest.mark.asyncio
async def test_validator_llm_verified_upgrade(db_session: AsyncSession):
    """Verify that when LLM extracts a valid UTR, it is deterministically checked against the DB and upgraded to MATCH."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="val_batch_3", status=BatchStatus.RECONCILING))

    # Add a valid settlement in DB
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_VALID_EXTRACTED",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=9764,
        settlement_date=datetime.date(2026, 8, 1),
    )
    db_session.add(settlement)
    await db_session.commit()

    mock_classifier = AsyncMock(spec=LLMClassifierAgent)
    mock_classifier.extract_from_narration.return_value = NarrationExtraction(
        candidate_order_id=None,
        candidate_utr="UTR_VALID_EXTRACTED",
        confidence="high",
        reasoning="Extracted UTR from narration string",
    )

    validator = ValidatorAgent(llm_classifier=mock_classifier)

    # Candidate has ambiguous narration and needs LLM
    candidate = MatchCandidate(
        payment_id=None,
        settlement_id=None,
        bank_entry_id=uuid.uuid4(),
        ledger_entry_id=None,
        result_scope=ResultScope.ORPHAN_BANK_ENTRY,
        proposed_decision=Decision.EXCEPTION,
        proposed_match_method=None,
        proposed_reason_code=ReasonCode.MISSING_SETTLEMENT.value,
        needs_llm=True,
        narration="Payment ref UTR_VALID_EXTRACTED received",
    )

    results = await validator.validate_and_persist([candidate], batch_id, db_session)
    assert len(results) == 1
    r = results[0]
    # Decision successfully upgraded because UTR_VALID_EXTRACTED was deterministically confirmed in DB!
    assert r.decision == Decision.MATCH
    assert r.match_method == MatchMethod.LLM_ASSISTED_NARRATION.value
    assert r.settlement_id == settlement.id
    assert r.reason_code is None


@pytest.mark.asyncio
async def test_validator_db_error_not_swallowed_as_llm_failure(db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (L-4):
    Verify that database errors during validation (e.g. repo failures) are NOT swallowed
    or misattributed to LLM extraction failures.
    """
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="val_batch_db_err", status=BatchStatus.RECONCILING))
    await db_session.commit()

    mock_classifier = AsyncMock(spec=LLMClassifierAgent)
    mock_classifier.extract_from_narration.return_value = NarrationExtraction(
        candidate_order_id=None,
        candidate_utr="UTR_EXTRACTED_ERR",
        confidence="high",
        reasoning="Extracted UTR",
    )

    validator = ValidatorAgent(llm_classifier=mock_classifier)

    candidate = MatchCandidate(
        payment_id=None,
        settlement_id=None,
        bank_entry_id=uuid.uuid4(),
        ledger_entry_id=None,
        result_scope=ResultScope.ORPHAN_BANK_ENTRY,
        proposed_decision=Decision.EXCEPTION,
        proposed_match_method=None,
        proposed_reason_code=ReasonCode.MISSING_SETTLEMENT.value,
        needs_llm=True,
        narration="Ref UTR_EXTRACTED_ERR",
    )

    with patch("app.repositories.settlement_repo.SettlementRepo.get_by_utr", side_effect=RuntimeError("Database connection dropped")):
        with pytest.raises(RuntimeError, match="Database connection dropped"):
            await validator.validate_and_persist([candidate], batch_id, db_session)

