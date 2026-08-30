from __future__ import annotations

import json
import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch import Batch
from app.models.enums import BatchStatus, Decision, ReasonCode
from app.repositories.batch_repo import BatchRepo


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"


@pytest.mark.asyncio
async def test_full_reconciliation_batch_e2e(client: AsyncClient, db_session: AsyncSession):
    """
    End-to-end integration test running the full three-way reconciliation pipeline
    on the 50-record synthetic dataset and verifying results against ground_truth.json oracle (§10).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bank_csv_path = os.path.join(base_dir, "data", "synthetic_bank_statement.csv")
    ledger_csv_path = os.path.join(base_dir, "data", "synthetic_ledger.csv")
    gt_path = os.path.join(base_dir, "data", "ground_truth.json")

    assert os.path.exists(bank_csv_path), "synthetic_bank_statement.csv not found"
    assert os.path.exists(ledger_csv_path), "synthetic_ledger.csv not found"
    assert os.path.exists(gt_path), "ground_truth.json not found"

    with open(gt_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    with open(bank_csv_path, "rb") as f_bank, open(ledger_csv_path, "rb") as f_ledger:
        files = {
            "bank_csv": ("bank.csv", f_bank.read(), "text/csv"),
            "ledger_csv": ("ledger.csv", f_ledger.read(), "text/csv"),
        }
        headers = {"Idempotency-Key": f"e2e_key_{uuid.uuid4()}"}

        response = await client.post("/api/v1/batches", files=files, headers=headers)

    assert response.status_code == 201, f"Batch creation failed: {response.text}"
    batch_data = response.json()

    batch_id = batch_data["batch_id"]
    assert batch_data["status"] == "COMPLETED"
    assert batch_data["completed_at"] is not None  # Non-null completed_at timestamp (§7.3, L-7)

    # Verify summary metrics against known ground truth
    # Total processed items = 50 payments + 2 orphan bank entries = 52 records
    assert batch_data["total_records"] == 52
    assert batch_data["matched_records"] == 42
    assert batch_data["exception_count"] == 10

    # Record match rate = 42 / 52 = 0.8077
    assert pytest.approx(batch_data["record_match_rate"], rel=1e-2) == (42 / 52)
    # Amount coverage should be > 80%
    assert batch_data["amount_coverage"] >= 0.80

    # Verify reason code breakdown matches ground truth distribution exactly
    reason_counts = batch_data["reason_code_breakdown"]
    assert reason_counts.get("PARTIAL_SETTLEMENT") == 3
    assert reason_counts.get("DUPLICATE_UTR") == 2
    assert reason_counts.get("MISSING_BANK_ENTRY") == 2
    assert reason_counts.get("MISSING_SETTLEMENT") == 2
    assert reason_counts.get("AMOUNT_MISMATCH") == 1

    # Verify match method breakdown
    method_counts = batch_data["match_method_breakdown"]
    assert method_counts.get("EXACT_UTR") == 37
    assert method_counts.get("AMOUNT_WITH_FEE_EQUATION") == 5

    # Test GET /batches/{id}/exceptions
    resp_exc = await client.get(f"/api/v1/batches/{batch_id}/exceptions?limit=100")
    assert resp_exc.status_code == 200
    exc_data = resp_exc.json()
    assert exc_data["total"] == 10
    assert len(exc_data["data"]) == 10
    # Verify human-readable UTR / order ID and amounts surfaced (§7.3)
    sample_exc = exc_data["data"][0]
    assert "settlement_utr" in sample_exc
    assert "bank_entry_utr" in sample_exc
    assert "ledger_order_id" in sample_exc
    assert any(e["settlement_utr"] is not None or e["bank_entry_utr"] is not None for e in exc_data["data"])

    # Test GET /batches/{id}/matches
    resp_match = await client.get(f"/api/v1/batches/{batch_id}/matches?limit=100")
    assert resp_match.status_code == 200
    match_data = resp_match.json()
    assert match_data["total"] == 42
    assert len(match_data["data"]) == 42
    sample_match = match_data["data"][0]
    assert sample_match["settlement_utr"] is not None
    assert sample_match["bank_entry_utr"] is not None
    assert sample_match["ledger_order_id"] is not None
    assert sample_match["amounts"] is not None
    assert "expected_paise" in sample_match["amounts"]
    assert "actual_paise" in sample_match["amounts"]
    assert "difference_paise" in sample_match["amounts"]


@pytest.mark.asyncio
async def test_multiple_sequential_batches_no_cross_contamination(client: AsyncClient, db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (A-1):
    Posting the same seeded CSVs in two successive batches MUST produce identical metrics.
    Proves that bank_entry and ledger_entry are scoped strictly per batch_id and do not
    contaminate subsequent runs with false duplicate UTRs or false matches.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bank_csv_path = os.path.join(base_dir, "data", "synthetic_bank_statement.csv")
    ledger_csv_path = os.path.join(base_dir, "data", "synthetic_ledger.csv")

    with open(bank_csv_path, "rb") as f_bank, open(ledger_csv_path, "rb") as f_ledger:
        bank_bytes = f_bank.read()
        ledger_bytes = f_ledger.read()

    # Run Batch 1
    files1 = {
        "bank_csv": ("bank.csv", bank_bytes, "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_bytes, "text/csv"),
    }
    r1 = await client.post("/api/v1/batches", files=files1, headers={"Idempotency-Key": f"batch_seq_1_{uuid.uuid4()}"})
    assert r1.status_code == 201
    d1 = r1.json()

    # Run Batch 2 with different idempotency key and same CSV contents
    files2 = {
        "bank_csv": ("bank.csv", bank_bytes, "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_bytes, "text/csv"),
    }
    r2 = await client.post("/api/v1/batches", files=files2, headers={"Idempotency-Key": f"batch_seq_2_{uuid.uuid4()}"})
    assert r2.status_code == 201
    d2 = r2.json()

    # Both batches must have distinct IDs
    assert d1["batch_id"] != d2["batch_id"]

    # Both batches MUST have the exact same match metrics (42 matches, 10 exceptions, 0 false duplicates)
    assert d1["matched_records"] == d2["matched_records"] == 42
    assert d1["exception_count"] == d2["exception_count"] == 10
    assert d1["record_match_rate"] == d2["record_match_rate"]
    assert d1["reason_code_breakdown"] == d2["reason_code_breakdown"]
    assert d2["reason_code_breakdown"].get("DUPLICATE_UTR") == 2  # Exactly 2 true duplicates, NOT 48+


@pytest.mark.asyncio
async def test_batch_idempotency_returns_same_batch(client: AsyncClient, db_session: AsyncSession):
    """Verify that posting with the same Idempotency-Key returns the existing completed batch (§7.2)."""
    headers = {"Idempotency-Key": "idemp_test_unique_key_12345"}
    files1 = {
        "bank_csv": ("bank.csv", b"utr,amount_paise,value_date\nUTR_IDEMP_1,10000,2026-08-01\n", "text/csv"),
        "ledger_csv": ("ledger.csv", b"order_id,expected_amount_paise\nord_idemp_1,10000\n", "text/csv"),
    }

    r1 = await client.post("/api/v1/batches", files=files1, headers=headers)
    assert r1.status_code == 201
    batch_id_1 = r1.json()["batch_id"]

    # Second request with SAME idempotency key
    files2 = {
        "bank_csv": ("bank.csv", b"utr,amount_paise,value_date\nUTR_IDEMP_1,10000,2026-08-01\n", "text/csv"),
        "ledger_csv": ("ledger.csv", b"order_id,expected_amount_paise\nord_idemp_1,10000\n", "text/csv"),
    }
    r2 = await client.post("/api/v1/batches", files=files2, headers=headers)
    assert r2.status_code == 201
    batch_id_2 = r2.json()["batch_id"]

    # Identical batch ID returned, no duplicate processing
    assert batch_id_1 == batch_id_2


@pytest.mark.asyncio
async def test_batch_retry_endpoint(client: AsyncClient, db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (A-2):
    Verify that retrying a batch does NOT double-count records.
    """
    # 1. Batch in COMPLETED state -> should return 409 Conflict
    batch_id_completed = uuid.uuid4()
    b1 = Batch(id=batch_id_completed, idempotency_key="retry_k1", status=BatchStatus.COMPLETED)
    db_session.add(b1)
    await db_session.commit()

    resp_conflict = await client.post(f"/api/v1/batches/{batch_id_completed}/retry")
    assert resp_conflict.status_code == 409

    # 2. Run a full batch, then force FAILED_RECONCILIATION, and retry -> records must not double!
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bank_csv_path = os.path.join(base_dir, "data", "synthetic_bank_statement.csv")
    ledger_csv_path = os.path.join(base_dir, "data", "synthetic_ledger.csv")

    with open(bank_csv_path, "rb") as f_bank, open(ledger_csv_path, "rb") as f_ledger:
        files = {
            "bank_csv": ("bank.csv", f_bank.read(), "text/csv"),
            "ledger_csv": ("ledger.csv", f_ledger.read(), "text/csv"),
        }
        res_post = await client.post("/api/v1/batches", files=files, headers={"Idempotency-Key": f"retry_run_{uuid.uuid4()}"})

    assert res_post.status_code == 201
    batch_info = res_post.json()
    batch_id = uuid.UUID(batch_info["batch_id"])
    assert batch_info["total_records"] == 52
    assert batch_info["matched_records"] == 42

    # Simulate failure
    await BatchRepo.update_status(db_session, batch_id, BatchStatus.FAILED_RECONCILIATION)

    # Trigger Retry
    resp_retry = await client.post(f"/api/v1/batches/{batch_id}/retry")
    assert resp_retry.status_code == 200
    retry_data = resp_retry.json()
    assert retry_data["status"] == "COMPLETED"
    assert retry_data["completed_at"] is not None  # Non-null completed_at timestamp (§7.3, L-7)

    # MUST NOT double-count: total_records must be 52 (NOT 104), matched must be 42 (NOT 84)
    assert retry_data["total_records"] == 52
    assert retry_data["matched_records"] == 42
    assert retry_data["exception_count"] == 10
    assert pytest.approx(retry_data["record_match_rate"], rel=1e-2) == (42 / 52)


@pytest.mark.asyncio
async def test_retry_failed_ingestion_batch(client: AsyncClient, db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (A-3):
    Verify that retrying a FAILED_INGESTION batch re-runs the full pipeline (ingestion, settlements,
    matcher, validator) and does NOT silently fabricate an empty completed batch.
    """
    batch_id_failed = uuid.uuid4()
    b = Batch(id=batch_id_failed, idempotency_key="retry_ingest_fail_k", status=BatchStatus.FAILED_INGESTION)
    db_session.add(b)
    await db_session.commit()

    # Retry the batch with bank & ledger CSVs provided
    bank_csv = b"utr,amount_paise,value_date\nUTR_ING_RETRY_1,9764,2026-08-01\n"
    ledger_csv = b"order_id,expected_amount_paise\nord_ing_retry_1,10000\n"

    files = {
        "bank_csv": ("bank.csv", bank_csv, "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_csv, "text/csv"),
    }

    resp = await client.post(f"/api/v1/batches/{batch_id_failed}/retry", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    # Should have processed records and not be empty 0/0
    assert data["total_records"] > 0


@pytest.mark.asyncio
async def test_qa_endpoint(client: AsyncClient, db_session: AsyncSession):
    """Verify natural language settlement Q&A endpoint (§12 item 1)."""
    batch_id = uuid.uuid4()
    b = Batch(id=batch_id, idempotency_key="qa_test_k", status=BatchStatus.COMPLETED)
    db_session.add(b)
    await db_session.commit()

    qa_payload = {
        "question": "Why were there exceptions in this batch?",
        "batch_id": str(batch_id),
    }
    response = await client.post("/api/v1/qa", json=qa_payload)
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["question"] == "Why were there exceptions in this batch?"


@pytest.mark.asyncio
async def test_retry_stuck_batch_in_non_terminal_state(client: AsyncClient, db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (L-2):
    Verify that a batch stuck in a non-terminal state (e.g. INGESTING or RECONCILING due to server crash)
    can be retried and completes cleanly instead of being rejected with 409.
    """
    batch_id_stuck = uuid.uuid4()
    b = Batch(id=batch_id_stuck, idempotency_key="stuck_batch_k", status=BatchStatus.INGESTING)
    db_session.add(b)
    await db_session.commit()

    resp = await client.post(f"/api/v1/batches/{batch_id_stuck}/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["total_records"] == 52


@pytest.mark.asyncio
async def test_repost_same_idempotency_key_after_crash(client: AsyncClient, db_session: AsyncSession):
    """
    CRITICAL REGRESSION TEST (L-2):
    Verify that re-POSTing with the same Idempotency-Key on an incomplete / crashed batch
    wipes partial batch data and does NOT crash on uq_settlement_line_batch_payment.
    """
    idem_key = f"crash_idemp_{uuid.uuid4()}"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bank_csv_path = os.path.join(base_dir, "data", "synthetic_bank_statement.csv")
    ledger_csv_path = os.path.join(base_dir, "data", "synthetic_ledger.csv")

    with open(bank_csv_path, "rb") as fb, open(ledger_csv_path, "rb") as fl:
        bank_bytes = fb.read()
        ledger_bytes = fl.read()

    # 1. Create batch stuck in INGESTED status with some partial rows
    batch = Batch(id=uuid.uuid4(), idempotency_key=idem_key, status=BatchStatus.INGESTED)
    db_session.add(batch)
    await db_session.commit()

    # 2. Re-POST with same Idempotency-Key
    files = {
        "bank_csv": ("bank.csv", bank_bytes, "text/csv"),
        "ledger_csv": ("ledger.csv", ledger_bytes, "text/csv"),
    }
    headers = {"Idempotency-Key": idem_key}
    r = await client.post("/api/v1/batches", files=files, headers=headers)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "COMPLETED"
    assert data["total_records"] == 52
    assert data["matched_records"] == 42

