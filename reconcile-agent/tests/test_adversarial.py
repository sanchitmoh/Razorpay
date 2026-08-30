from __future__ import annotations

import datetime
import os
import uuid
from datetime import date, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ingestion import IngestionAgent
from app.agents.matcher import MatcherAgent
from app.agents.orchestrator import BatchOrchestrator
from app.agents.settlement_builder import SettlementBuilderAgent
from app.core.razorpay_client import RazorpayClient
from app.models.bank_entry import BankEntry
from app.models.batch import Batch
from app.models.enums import BatchStatus, Decision, MatchMethod, ReasonCode, ResultScope
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.models.reconciliation_result import ReconciliationResult
from app.models.settlement import Settlement
from app.models.settlement_line import SettlementLine
from app.repositories.batch_repo import BatchRepo
from app.repositories.reconciliation_result_repo import ReconciliationResultRepo


def _mock_client(payments: list[dict] | None = None) -> AsyncMock:
    mock = AsyncMock(spec=RazorpayClient)
    mock.fetch_captured_payments.return_value = payments or []
    return mock


@pytest.mark.asyncio
async def test_bank_csv_with_utf8_bom_ingests(db_session: AsyncSession):
    """Excel-exported bank CSVs start with a UTF-8 BOM; the header check must not fail on it (H4).
    
    FIXED H4: Before fix, UTF-8 BOM (\\ufeff) at file start caused first column name to appear 
    as "\\ufeffutr" instead of "utr", failing required-column validation → FAILED_INGESTION.
    After fix: CSV parser strips BOM prefix; Excel "Save as CSV UTF-8" exports ingest cleanly.
    """
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_bom_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    # ﻿ prefix as produced by Excel "CSV UTF-8" exports
    bank_csv = "﻿utr,amount_paise,value_date,narration\nUTR_BOM_1,9764,2026-08-01,Settlement credit\n"
    ledger_csv = "order_id,expected_amount_paise\norder_bom_1,10000\n"

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, bank_entries, _ = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv.encode("utf-8"),
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    assert len(bank_entries) == 1
    assert bank_entries[0].utr == "UTR_BOM_1"


@pytest.mark.asyncio
async def test_decimal_paise_rejected_not_truncated(db_session: AsyncSession):
    """A fractional paise value is corrupt data; it must be rejected, never float-truncated (H3).
    
    FIXED H3: Before fix, int(float("10050.9")) → 10050 (silent truncation via float casting).
    After fix: _parse_paise() rejects non-integral decimals with ValueError; only whole numbers 
    or Excel-style "10000.0" accepted. Prevents silent money corruption at CSV trust boundary.
    """
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_dec_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    # "9764.5" would silently become 9764 under int(float(...)); big int must survive exactly
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_DEC_1,9764,2026-08-01,clean\n"
        "UTR_DEC_2,9764.5,2026-08-01,fractional paise\n"
        "UTR_DEC_3,12345678901234,2026-08-01,large but integral\n"
    )
    ledger_csv = "order_id,expected_amount_paise\norder_dec_1,10000\n"

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, bank_entries, _ = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    by_utr = {e.utr: e.amount_paise for e in bank_entries}
    assert "UTR_DEC_2" not in by_utr, "fractional paise row must be rejected, not truncated"
    assert by_utr.get("UTR_DEC_1") == 9764
    assert by_utr.get("UTR_DEC_3") == 12345678901234

@pytest.mark.asyncio
async def test_ledger_decimal_paise_rejected_not_truncated(db_session: AsyncSession):
    """Same trust-boundary rule for ledger expected amounts (H3)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_ldec_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    bank_csv = "utr,amount_paise,value_date\nUTR_LDEC_1,10000,2026-08-01\n"
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "order_ldec_1,10000\n"
        "order_ldec_2,5000.5\n"
        "order_ldec_3,99999999999999\n"
    )

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, _, ledger_entries = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    by_order = {e.order_id: e.expected_amount_paise for e in ledger_entries}
    assert "order_ldec_2" not in by_order, "fractional paise row must be rejected"
    assert by_order.get("order_ldec_1") == 10000
    assert by_order.get("order_ldec_3") == 99999999999999


@pytest.mark.asyncio
async def test_retry_without_files_refuses_not_fabricates(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Retry of FAILED_INGESTION with no uploads and no fixture gate must 400,
    never silently reconcile stale synthetic files from disk as if they were the
    operator's data (H1).
    
    FIXED H1: Before fix, retry endpoint would fall back to reading data/synthetic_*.csv from 
    disk when no files provided, marking batch COMPLETED with fabricated results in prod path.
    After fix: Returns 400 MISSING_INPUT_DATA unless USE_FIXTURES=1 explicitly enables test mode.
    """
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_retry_h1_{uuid.uuid4()}", status=BatchStatus.FAILED_INGESTION))
    await db_session.commit()

    # Simulate production: no fixture/demo fallback permitted
    monkeypatch.setenv("USE_FIXTURES", "0")

    resp = await client.post(f"/api/v1/batches/{batch_id}/retry")

    assert resp.status_code == 400, (
        f"expected refusal, got {resp.status_code}: {resp.text[:200]}"
    )
    assert resp.json()["detail"]["error"]["code"] == "MISSING_INPUT_DATA"


@pytest.mark.asyncio
async def test_retry_settlement_rebuild_does_not_leak_other_batches(client: AsyncClient, db_session: AsyncSession):
    """Rebuilding settlements on retry must never pull payments belonging to other
    batches — the DB payment table is global (H2).
    
    FIXED H2: Before fix, retry of FAILED_RECONCILIATION batch with missing settlements could 
    rebuild from PaymentRepo.get_all(), contaminating batch with other batches' payments.
    After fix: Retry refuses (400 MISSING_INGESTED_DATA) when bank_entries or settlements missing; 
    requires fresh file upload to re-run full pipeline with proper batch_id isolation.
    """
    from datetime import date

    from app.models.bank_entry import BankEntry

    # Batch A: honest full run -> populates the global payments table
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "data", "synthetic_bank_statement.csv"), "rb") as fb, \
         open(os.path.join(base_dir, "data", "synthetic_ledger.csv"), "rb") as fl:
        files_a = {
            "bank_csv": ("bank.csv", fb.read(), "text/csv"),
            "ledger_csv": ("ledger.csv", fl.read(), "text/csv"),
        }
    r_a = await client.post("/api/v1/batches", files=files_a, headers={"Idempotency-Key": f"adv_h2_a_{uuid.uuid4()}"})
    assert r_a.status_code == 201

    # Batch B: crashed between ingestion and settlement build
    batch_b = uuid.uuid4()
    db_session.add(Batch(id=batch_b, idempotency_key=f"adv_h2_b_{uuid.uuid4()}", status=BatchStatus.FAILED_RECONCILIATION))
    await db_session.commit()
    db_session.add(BankEntry(
        id=uuid.uuid4(),
        batch_id=batch_b,
        utr="UTR_H2_ONLY_B",
        amount_paise=12345,
        value_date=date(2026, 8, 1),
        narration=None,
    ))
    await db_session.commit()

    resp = await client.post(f"/api/v1/batches/{batch_b}/retry")

    # Verify the fix: batch has bank_entries but missing settlements → retry must refuse
    assert resp.status_code == 400, (
        f"expected refusal when settlements missing (H2 fix), got {resp.status_code}: {resp.text[:300]}"
    )
    assert resp.json()["detail"]["error"]["code"] == "MISSING_INGESTED_DATA", (
        "Expected MISSING_INGESTED_DATA error code when retry lacks complete ingestion artifacts"
    )


# ==============================================================================
# US10: Deterministic Retry of Mid-Crash Batches
# ==============================================================================

@pytest.mark.asyncio
async def test_mid_crash_batch_retry_produces_identical_results(
    client: AsyncClient, db_session: AsyncSession
):
    """Batch that crashed mid-reconciliation can be retried deterministically 
    with same files and produces identical results (US10).
    
    Scenario: Batch completes ingestion + settlement build, crashes during matching/validation.
    Status = FAILED_RECONCILIATION. Retry with original files should produce same match count,
    same exceptions, same reason codes (deterministic, reproducible results).
    """
    from app.models.batch import Batch
    from app.repositories.batch_repo import BatchRepo

    # Step 1: Create a batch and ingest successfully
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_US10_1,9764,2026-08-01,First settlement\n"
        "UTR_US10_2,9764,2026-08-01,Second settlement\n"
    )
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "order_us10_1,10000\n"
        "order_us10_2,10000\n"
    )

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    
    # First run: complete successfully
    resp1 = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"us10_run1_{uuid.uuid4()}"})
    assert resp1.status_code == 201
    data1 = resp1.json()
    batch_id_1 = data1["batch_id"]
    
    # Capture first run metrics
    original_status = data1["status"]
    original_matched = data1["matched_records"]
    original_exceptions = data1["exception_count"]
    original_record_match_rate = data1["record_match_rate"]
    
    assert original_status == "COMPLETED"
    
    # Step 2: Simulate a crash scenario - create a fresh batch, mark as FAILED_RECONCILIATION
    # This simulates a batch that completed ingestion but crashed during reconciliation
    batch_id_crashed = uuid.uuid4()
    db_session.add(Batch(
        id=batch_id_crashed,
        idempotency_key=f"us10_crashed_{uuid.uuid4()}",
        status=BatchStatus.FAILED_RECONCILIATION
    ))
    await db_session.commit()
    
    # Retry the crashed batch with same files (full re-run via retry endpoint)
    files_retry = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp_retry = await client.post(f"/api/v1/batches/{batch_id_crashed}/retry", files=files_retry)
    assert resp_retry.status_code == 200
    data_retry = resp_retry.json()
    
    # Step 3: Verify determinism - retry produces identical metrics
    assert data_retry["status"] == original_status
    assert data_retry["matched_records"] == original_matched, (
        f"Retry matched_records ({data_retry['matched_records']}) must equal "
        f"original ({original_matched}) for deterministic reconciliation"
    )
    assert data_retry["exception_count"] == original_exceptions, (
        f"Retry exception_count ({data_retry['exception_count']}) must equal "
        f"original ({original_exceptions}) for deterministic reconciliation"
    )
    assert abs(data_retry["record_match_rate"] - original_record_match_rate) < 0.001, (
        f"Retry record_match_rate ({data_retry['record_match_rate']}) must equal "
        f"original ({original_record_match_rate}) for deterministic reconciliation"
    )
    
    # Verify reason code breakdown is identical (if any exceptions exist)
    if original_exceptions > 0:
        original_reasons = data1.get("reason_code_breakdown", {})
        retry_reasons = data_retry.get("reason_code_breakdown", {})
        assert original_reasons == retry_reasons, (
            f"Retry reason codes {retry_reasons} must match original {original_reasons}"
        )


# ==============================================================================
# P8: Duplicate order_id in Ledger CSV (Last-Wins, Silent)
# ==============================================================================

@pytest.mark.asyncio
async def test_duplicate_ledger_order_id_last_wins_documented(db_session: AsyncSession):
    """Duplicate order_id rows in ledger CSV: both rows ingest into DB, matcher map is last-wins (P8).
    
    PINNED P8: Duplicate order_ids are absorbed silently via dict comprehension (last row wins).
    This is deterministic but order-dependent. US7 requests visibility; future enhancement could
    add `duplicate_ledger_order_ids` count to BatchSummaryResponse for operator awareness.
    """
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_dup_ledger_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    # Payment expecting 10000 paise
    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_dup_ord_1", order_id="ord_dup_key", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    
    # Duplicate ledger entries with conflicting amounts
    ledger1 = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_dup_key", expected_amount_paise=10000)
    ledger2 = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_dup_key", expected_amount_paise=99999)
    
    net = 10000 - 200 - 36
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_DUP_LEDGER",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=0,
        net_amount_paise=net,
        settlement_date=date(2026, 8, 1),
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
        utr="UTR_DUP_LEDGER",
        amount_paise=net,
        value_date=date(2026, 8, 1),
    )
    db_session.add_all([payment, ledger1, ledger2, settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    # Matcher uses dict comprehension over order_ids -> one entry wins deterministically
    assert candidates[0].payment_id == "pay_dup_ord_1"


# ==============================================================================
# US7: Duplicate Order ID Visibility in Batch Summary
# ==============================================================================

@pytest.mark.asyncio
async def test_duplicate_order_ids_visible_in_batch_summary(client: AsyncClient, db_session: AsyncSession):
    """Duplicate order_ids are counted and surfaced in batch summary API response (US7)."""
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_US7_1,9764,2026-08-01,Settlement 1\n"
        "UTR_US7_2,9764,2026-08-01,Settlement 2\n"
    )
    # Ledger has 2 duplicate order_ids
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "order_us7_dup,10000\n"
        "order_us7_dup,10500\n"
        "order_us7_unique,10000\n"
    )

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_us7_{uuid.uuid4()}"})
    assert resp.status_code == 201
    data = resp.json()
    
    # Verify duplicate count is surfaced
    assert "duplicate_ledger_order_ids" in data
    assert data["duplicate_ledger_order_ids"] == 1, "Should count 1 duplicate (order_us7_dup appears twice)"


# ==============================================================================
# P3: Skipped Row Visibility in Batch Summary
# ==============================================================================

@pytest.mark.asyncio
async def test_skipped_rows_visible_in_batch_summary(client: AsyncClient, db_session: AsyncSession):
    """Skipped/malformed CSV rows are counted and surfaced in batch summary (P3 visibility)."""
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_P3_VALID,9764,2026-08-01,Valid\n"
        "UTR_P3_BAD,CORRUPT_AMOUNT,2026-08-01,Bad amount\n"
        ",5000,2026-08-01,Missing UTR\n"
    )
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "order_p3_1,10000\n"
        ",15000\n"
        "order_p3_bad,NOT_A_NUMBER\n"
    )

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_p3vis_{uuid.uuid4()}"})
    assert resp.status_code == 201
    data = resp.json()
    
    # Verify skipped row count is surfaced
    assert "skipped_rows" in data
    # 2 bank rows skipped + 2 ledger rows skipped = 4 total
    assert data["skipped_rows"] == 4, "Should count 4 skipped rows (2 bank + 2 ledger)"


# ==============================================================================
# Combined: Both Metrics Together
# ==============================================================================

@pytest.mark.asyncio
async def test_data_quality_metrics_in_clean_batch(client: AsyncClient, db_session: AsyncSession):
    """Clean batch with no duplicates or skipped rows shows zeros for data quality metrics."""
    bank_csv = "utr,amount_paise,value_date\nUTR_CLEAN_1,9764,2026-08-01\n"
    ledger_csv = "order_id,expected_amount_paise\norder_clean_1,10000\n"

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_clean_{uuid.uuid4()}"})
    assert resp.status_code == 201
    data = resp.json()
    
    # Clean batch should show zeros
    assert data["duplicate_ledger_order_ids"] == 0
    assert data["skipped_rows"] == 0


# ==============================================================================
# H6: Stable Pagination with ORDER BY
# ==============================================================================

@pytest.mark.asyncio
async def test_pagination_exceptions_stable_across_pages(client: AsyncClient, db_session: AsyncSession):
    """Paginated /exceptions has deterministic ORDER BY; paging does not drop or duplicate rows (H6)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_h6_exc_{uuid.uuid4()}", status=BatchStatus.COMPLETED))

    # Seed 7 exception records
    res_ids = []
    for i in range(7):
        r_id = uuid.uuid4()
        res_ids.append(r_id)
        db_session.add(
            ReconciliationResult(
                id=r_id,
                batch_id=batch_id,
                result_scope=ResultScope.PAYMENT,
                payment_id=f"pay_h6_{i}",
                decision=Decision.EXCEPTION,
                reason_code=ReasonCode.MISSING_BANK_ENTRY.value,
                matcher_version="v1",
                expected_amount_paise=10000,
                actual_amount_paise=0,
                difference_paise=10000,
            )
        )
    await db_session.commit()

    # Query with page size 2
    seen_ids = []
    offset = 0
    while True:
        resp = await client.get(f"/api/v1/batches/{batch_id}/exceptions?limit=2&offset={offset}")
        assert resp.status_code == 200
        page = resp.json()
        assert page["total"] == 7
        data = page["data"]
        if not data:
            break
        for item in data:
            seen_ids.append(item["result_id"])
        offset += len(data)

    assert len(seen_ids) == 7
    assert len(set(seen_ids)) == 7, "Pagination must not duplicate any result_id across pages"


@pytest.mark.asyncio
async def test_pagination_matches_stable_across_pages(client: AsyncClient, db_session: AsyncSession):
    """Paginated /matches has deterministic ORDER BY; paging covers all rows without duplicates (H6)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_h6_mat_{uuid.uuid4()}", status=BatchStatus.COMPLETED))

    # Seed 6 match records
    res_ids = []
    for i in range(6):
        r_id = uuid.uuid4()
        res_ids.append(r_id)
        db_session.add(
            ReconciliationResult(
                id=r_id,
                batch_id=batch_id,
                result_scope=ResultScope.PAYMENT,
                payment_id=f"pay_h6_match_{i}",
                decision=Decision.MATCH,
                match_method=MatchMethod.EXACT_UTR.value,
                matcher_version="v1",
                expected_amount_paise=9764,
                actual_amount_paise=9764,
                difference_paise=0,
            )
        )
    await db_session.commit()

    seen_ids = []
    offset = 0
    while True:
        resp = await client.get(f"/api/v1/batches/{batch_id}/matches?limit=2&offset={offset}")
        assert resp.status_code == 200
        page = resp.json()
        assert page["total"] == 6
        data = page["data"]
        if not data:
            break
        for item in data:
            seen_ids.append(item["result_id"])
        offset += len(data)

    assert len(seen_ids) == 6
    assert len(set(seen_ids)) == 6, "Pagination must not duplicate any match result_id"


# ==============================================================================
# P1: Zero / Negative Payment Amount Fail-Closed Poison Pill
# ==============================================================================

@pytest.mark.asyncio
async def test_zero_amount_payment_fails_batch(db_session: AsyncSession):
    """Payment with amount_paise <= 0 fails settlement build, fail-closed (P1)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_p1_zero_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    p = Payment(id="pay_zero", order_id="ord_zero", amount_paise=0, fee_paise=0, tax_paise=0, status="captured")
    db_session.add(p)
    await db_session.commit()

    builder = SettlementBuilderAgent()
    with pytest.raises(ValueError, match="non-positive allocation"):
        await builder.build(batch_id, [p], db_session)


@pytest.mark.asyncio
async def test_negative_amount_payment_fails_batch(db_session: AsyncSession):
    """Payment with amount_paise < 0 fails settlement build, fail-closed (P1)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_p1_neg_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    p = Payment(id="pay_neg", order_id="ord_neg", amount_paise=-5000, fee_paise=0, tax_paise=0, status="captured")
    db_session.add(p)
    await db_session.commit()

    builder = SettlementBuilderAgent()
    with pytest.raises(ValueError, match="non-positive allocation"):
        await builder.build(batch_id, [p], db_session)


# ==============================================================================
# P2: Null captured_at Groups Under Today's Date
# ==============================================================================

@pytest.mark.asyncio
async def test_null_captured_at_groups_under_today(db_session: AsyncSession):
    """Payments with captured_at=None group under date.today() (P2)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_p2_null_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    p = Payment(id="pay_no_cap", order_id="ord_no_cap", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=None)
    db_session.add(p)
    await db_session.commit()

    builder = SettlementBuilderAgent()
    settlements, lines = await builder.build(batch_id, [p], db_session)

    assert len(settlements) == 1
    assert settlements[0].settlement_date == date.today()
    assert len(lines) == 1


# ==============================================================================
# P3: Malformed CSV Rows Skipped Silently
# ==============================================================================

@pytest.mark.asyncio
async def test_malformed_csv_rows_skipped_batch_completes(client: AsyncClient, db_session: AsyncSession):
    """Malformed CSV rows in bank and ledger are dropped silently; valid rows reconcile (P3)."""
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_P3_VALID_1,9764,2026-08-01,Valid row 1\n"
        "UTR_P3_CORRUPT,INVALID_AMOUNT,2026-08-01,Corrupted row\n"
        ",5000,2026-08-01,Missing UTR row\n"
    )
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "order_p3_1,10000\n"
        ",10000\n"
        "order_p3_bad,NOT_A_NUMBER\n"
    )

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_p3_{uuid.uuid4()}"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"


# ==============================================================================
# P4: Negative Bank Amounts Ingest as Orphan Exceptions
# ==============================================================================

@pytest.mark.asyncio
async def test_negative_bank_amount_ingests_as_orphan_exception(db_session: AsyncSession):
    """Negative bank amounts (reversals/debits) ingest and become orphan exceptions (P4)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_p4_neg_bank_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    bank_csv = "utr,amount_paise,value_date,narration\nUTR_REV_1,-5000,2026-08-01,Chargeback reversal\n"
    ledger_csv = "order_id,expected_amount_paise\norder_dummy,10000\n"

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, bank_entries, _ = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    assert len(bank_entries) == 1
    assert bank_entries[0].amount_paise == -5000

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.result_scope == ResultScope.ORPHAN_BANK_ENTRY
    assert c.proposed_decision == Decision.EXCEPTION
    assert c.proposed_reason_code == ReasonCode.MISSING_SETTLEMENT.value
    assert c.actual_amount_paise == -5000


# ==============================================================================
# P5: Difference Paise Semantics
# ==============================================================================

@pytest.mark.asyncio
async def test_difference_paise_bank_variance_vs_ledger_mismatch(db_session: AsyncSession):
    """difference_paise reflects bank variance when within rounding tolerance, or payment-ledger difference on mismatch (P5)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_p5_diff_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    # Case A: Bank variance of +150 paise
    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    p_a = Payment(id="pay_diff_a", order_id="ord_diff_a", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    l_a = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_diff_a", expected_amount_paise=10000)
    net_a = 10000 - 200 - 36
    s_a = Settlement(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DIFF_A", gross_amount_paise=10000, fee_paise=200, tax_paise=36, adjustment_paise=0, net_amount_paise=net_a, settlement_date=date(2026, 8, 1))
    line_a = SettlementLine(id=uuid.uuid4(), batch_id=batch_id, settlement_id=s_a.id, payment_id=p_a.id, allocated_amount_paise=10000)
    b_a = BankEntry(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DIFF_A", amount_paise=net_a + 150, value_date=date(2026, 8, 1))

    # Case B: Ledger amount mismatch (ledger expects 8000 instead of 10000)
    p_b = Payment(id="pay_diff_b", order_id="ord_diff_b", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    l_b = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_diff_b", expected_amount_paise=8000)
    net_b = 10000 - 200 - 36
    s_b = Settlement(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DIFF_B", gross_amount_paise=10000, fee_paise=200, tax_paise=36, adjustment_paise=0, net_amount_paise=net_b, settlement_date=date(2026, 8, 1))
    line_b = SettlementLine(id=uuid.uuid4(), batch_id=batch_id, settlement_id=s_b.id, payment_id=p_b.id, allocated_amount_paise=10000)
    b_b = BankEntry(id=uuid.uuid4(), batch_id=batch_id, utr="UTR_DIFF_B", amount_paise=net_b, value_date=date(2026, 8, 1))

    db_session.add_all([p_a, l_a, s_a, line_a, b_a, p_b, l_b, s_b, line_b, b_b])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    cand_a = next(c for c in candidates if c.payment_id == "pay_diff_a")
    cand_b = next(c for c in candidates if c.payment_id == "pay_diff_b")

    # Bank variance of +150
    assert cand_a.proposed_decision == Decision.MATCH
    assert cand_a.difference_paise == 150

    # Ledger mismatch: difference is payment (10000) - ledger (8000) = 2000
    assert cand_b.proposed_decision == Decision.EXCEPTION
    assert cand_b.proposed_reason_code == ReasonCode.AMOUNT_MISMATCH.value
    assert cand_b.difference_paise == 2000


# ==============================================================================
# P6: Empty / Header-Only CSVs Complete with Honest Exceptions
# ==============================================================================

@pytest.mark.asyncio
async def test_empty_bank_and_ledger_csv_honest_zeros(client: AsyncClient, db_session: AsyncSession):
    """Empty (header-only) CSVs complete cleanly with 0 matches and honest exception counts (P6)."""
    bank_csv = "utr,amount_paise,value_date,narration\n"
    ledger_csv = "order_id,expected_amount_paise\n"

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_empty_{uuid.uuid4()}"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["matched_records"] == 0


# ==============================================================================
# US8: Unicode Narration Preserved End-to-End
# ==============================================================================

@pytest.mark.asyncio
async def test_unicode_narration_preserved_end_to_end(client: AsyncClient, db_session: AsyncSession):
    """Regional unicode text in narration survives ingestion and is queryable (US8)."""
    unicode_narration = "रेज़रपे सेटलमेंट ट्रांसफर — मुंबई शाखा"
    bank_csv = f"utr,amount_paise,value_date,narration\nUTR_UNICODE_1,50000,2026-08-01,{unicode_narration}\n"
    ledger_csv = "order_id,expected_amount_paise\norder_u1,50000\n"

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_unicode_{uuid.uuid4()}"})
    assert resp.status_code == 201

    # Verify BankEntry in DB has exact unicode
    stmt = select(BankEntry).where(BankEntry.utr == "UTR_UNICODE_1")
    be = (await db_session.execute(stmt)).scalar_one()
    assert be.narration == unicode_narration


# ==============================================================================
# Beyond-PRD Edge Cases: CRLF, Extra Columns, Trim, BigInt, SQL Injection, Adj
# ==============================================================================

@pytest.mark.asyncio
async def test_crlf_line_endings_in_bank_and_ledger_csv(client: AsyncClient, db_session: AsyncSession):
    """Windows-style CRLF (\\r\\n) CSV line endings parse smoothly."""
    bank_crlf = "utr,amount_paise,value_date,narration\r\nUTR_CRLF_1,9764,2026-08-01,CRLF test\r\n"
    ledger_crlf = "order_id,expected_amount_paise\r\norder_crlf_1,10000\r\n"

    files = {
        "bank_csv": ("bank.csv", bank_crlf.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_crlf.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_crlf_{uuid.uuid4()}"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_extra_unknown_columns_in_csv_ignored(client: AsyncClient, db_session: AsyncSession):
    """Extra unexpected columns in CSV are safely ignored without crashing ingestion."""
    bank_extra = "utr,amount_paise,value_date,narration,extra_col_1,bank_branch_code\nUTR_EXT_1,9764,2026-08-01,Extra cols,BONUS_DATA,HDFC0001\n"
    ledger_extra = "order_id,expected_amount_paise,customer_notes,shipping_zip\norder_ext_1,10000,Handle with care,560001\n"

    files = {
        "bank_csv": ("bank.csv", bank_extra.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_extra.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_extra_cols_{uuid.uuid4()}"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_whitespace_padded_fields_trimmed(db_session: AsyncSession):
    """Whitespace around UTRs and Order IDs is trimmed before storing in DB."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_trim_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    bank_csv = "utr,amount_paise,value_date,narration\n  UTR_PADDED_001  ,9764,  2026-08-01  ,  Padded test  \n"
    ledger_csv = "order_id,expected_amount_paise\n  order_padded_001  ,10000\n"

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, bank_entries, ledger_entries = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    assert bank_entries[0].utr == "UTR_PADDED_001"
    assert ledger_entries[0].order_id == "order_padded_001"


@pytest.mark.asyncio
async def test_very_large_integral_paise_values(db_session: AsyncSession):
    """Very large paise amounts (up to BigInteger limits) ingest accurately without float corruption."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_bigint_{uuid.uuid4()}", status=BatchStatus.CREATED))
    await db_session.commit()

    large_amount = 9007199254740991  # 2^53 - 1 (exact integer representation in 64-bit systems)
    bank_csv = f"utr,amount_paise,value_date\nUTR_BIG_1,{large_amount},2026-08-01\n"
    ledger_csv = f"order_id,expected_amount_paise\norder_big_1,{large_amount}\n"

    agent = IngestionAgent(razorpay_client=_mock_client())
    _, bank_entries, ledger_entries = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    assert bank_entries[0].amount_paise == large_amount
    assert ledger_entries[0].expected_amount_paise == large_amount


@pytest.mark.asyncio
async def test_sql_injection_in_narration_safe(client: AsyncClient, db_session: AsyncSession):
    """Hostile SQL injection strings in narration fields do not corrupt database."""
    hostile_narration = "'; DROP TABLE payment; DROP TABLE batch; --"
    bank_csv = f"utr,amount_paise,value_date,narration\nUTR_SQLI_1,10000,2026-08-01,{hostile_narration}\n"
    ledger_csv = "order_id,expected_amount_paise\norder_sqli_1,10000\n"

    files = {
        "bank_csv": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv.encode("utf-8"), "text/csv"),
    }
    resp = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"adv_sqli_{uuid.uuid4()}"})
    assert resp.status_code == 201

    # Ensure tables still exist and query succeeds
    stmt = select(BankEntry).where(BankEntry.utr == "UTR_SQLI_1")
    be = (await db_session.execute(stmt)).scalar_one()
    assert be.narration == hostile_narration


@pytest.mark.asyncio
async def test_settlement_with_nonzero_adjustment(db_session: AsyncSession):
    """Settlement net amount correctly accounts for adjustment_paise in equation match."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key=f"adv_adj_{uuid.uuid4()}", status=BatchStatus.INGESTED))

    dt = datetime.datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    payment = Payment(id="pay_adj_1", order_id="ord_adj_1", amount_paise=10000, fee_paise=200, tax_paise=36, status="captured", captured_at=dt)
    ledger = LedgerEntry(id=uuid.uuid4(), batch_id=batch_id, order_id="ord_adj_1", expected_amount_paise=10000)

    # Net with adjustment of +500 paise: 10000 - 200 - 36 + 500 = 10264
    adjustment = 500
    net = 10000 - 200 - 36 + adjustment
    settlement = Settlement(
        id=uuid.uuid4(),
        batch_id=batch_id,
        utr="UTR_ADJ_001",
        gross_amount_paise=10000,
        fee_paise=200,
        tax_paise=36,
        adjustment_paise=adjustment,
        net_amount_paise=net,
        settlement_date=date(2026, 8, 1),
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
        utr="UTR_ADJ_001",
        amount_paise=net,
        value_date=date(2026, 8, 1),
    )
    db_session.add_all([payment, ledger, settlement, line, bank])
    await db_session.commit()

    matcher = MatcherAgent()
    candidates = await matcher.run_match(batch_id, db_session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.proposed_decision == Decision.MATCH
    assert c.proposed_match_method == MatchMethod.EXACT_UTR.value
    assert c.difference_paise == 0

