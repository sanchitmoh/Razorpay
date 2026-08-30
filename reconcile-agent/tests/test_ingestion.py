from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ingestion import IngestionAgent, IngestionError
from app.core.razorpay_client import RazorpayClient
from app.models.batch import Batch
from app.models.enums import BatchStatus


@pytest.mark.asyncio
async def test_ingestion_parses_valid_csvs(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="ingest_test_1", status=BatchStatus.CREATED))
    await db_session.commit()

    mock_client = AsyncMock(spec=RazorpayClient)
    mock_client.fetch_captured_payments.return_value = [
        {
            "id": "pay_test_001",
            "order_id": "order_test_001",
            "amount": 10000,
            "fee": 200,
            "tax": 36,
            "status": "captured",
            "captured_at": "2026-08-01T10:00:00Z",
        }
    ]

    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR20260801001,9764,2026-08-01,Razorpay Settlement Credit\n"
    )
    ledger_csv = (
        "order_id,expected_amount_paise,customer_ref,invoice_date\n"
        "order_test_001,10000,CUST_001,2026-08-01\n"
    )

    agent = IngestionAgent(razorpay_client=mock_client)
    payments, bank_entries, ledger_entries = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    assert len(payments) == 1
    assert len(bank_entries) == 1
    assert len(ledger_entries) == 1
    assert payments[0].id == "pay_test_001"
    assert bank_entries[0].utr == "UTR20260801001"
    assert ledger_entries[0].order_id == "order_test_001"


@pytest.mark.asyncio
async def test_ingestion_skips_malformed_csv_row(db_session: AsyncSession):
    """Verify that a single malformed row does not crash the entire batch (§6)."""
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="ingest_test_2", status=BatchStatus.CREATED))
    await db_session.commit()

    mock_client = AsyncMock(spec=RazorpayClient)
    mock_client.fetch_captured_payments.return_value = []

    # Second row has non-numeric amount_paise (corrupted)
    bank_csv = (
        "utr,amount_paise,value_date,narration\n"
        "UTR_VALID_1,10000,2026-08-01,Valid row\n"
        "UTR_CORRUPT,INVALID_AMOUNT,2026-08-01,Corrupted row\n"
        "UTR_VALID_2,20000,2026-08-01,Valid row 2\n"
    )
    ledger_csv = (
        "order_id,expected_amount_paise\n"
        "ord_1,10000\n"
    )

    agent = IngestionAgent(razorpay_client=mock_client)
    _, bank_entries, _ = await agent.run(
        batch_id=batch_id,
        bank_csv_content=bank_csv,
        ledger_csv_content=ledger_csv,
        db=db_session,
    )

    # Valid rows parsed, corrupt row skipped
    assert len(bank_entries) == 2
    assert bank_entries[0].utr == "UTR_VALID_1"
    assert bank_entries[1].utr == "UTR_VALID_2"


@pytest.mark.asyncio
async def test_ingestion_missing_required_column_raises_error(db_session: AsyncSession):
    batch_id = uuid.uuid4()
    db_session.add(Batch(id=batch_id, idempotency_key="ingest_test_3", status=BatchStatus.CREATED))
    await db_session.commit()

    mock_client = AsyncMock(spec=RazorpayClient)
    mock_client.fetch_captured_payments.return_value = []

    # Missing amount_paise column
    bad_bank_csv = "utr,value_date\nUTR_1,2026-08-01\n"
    good_ledger_csv = "order_id,expected_amount_paise\nord_1,10000\n"

    agent = IngestionAgent(razorpay_client=mock_client)
    with pytest.raises(IngestionError, match="missing required columns"):
        await agent.run(
            batch_id=batch_id,
            bank_csv_content=bad_bank_csv,
            ledger_csv_content=good_ledger_csv,
            db=db_session,
        )


def test_parse_payment_prefers_captured_at_over_created_at():
    """Verify that parse_razorpay_payment_dict prefers captured_at over created_at (§3, L-3)."""
    from app.agents.ingestion import parse_razorpay_payment_dict
    from datetime import datetime, timezone

    p_dict = {
        "id": "pay_cap_pref",
        "order_id": "order_cap_pref",
        "amount": 50000,
        "created_at": 1700000000,  # 2023-11-14
        "captured_at": 1720000000,  # 2024-07-03
    }
    model = parse_razorpay_payment_dict(p_dict)
    assert model.captured_at == datetime.fromtimestamp(1720000000, tz=timezone.utc)

