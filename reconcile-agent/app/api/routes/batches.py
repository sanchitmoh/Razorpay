from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import BatchOrchestrator
from app.agents.reporter import ReporterAgent
from app.core.config import settings
from app.core.security import rate_limiter, verify_api_key
from app.db.database import get_db
from app.models.enums import BatchStatus
from app.repositories.bank_entry_repo import BankEntryRepo
from app.repositories.batch_repo import BatchRepo
from app.repositories.reconciliation_result_repo import ReconciliationResultRepo
from app.repositories.settlement_repo import SettlementRepo
from app.schemas.batch import (
    AmountDetail,
    BatchSummaryResponse,
    ExceptionListItem,
    MatchListItem,
    PaginatedResponse,
)
from app.schemas.responses import build_metadata_from_request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batches", tags=["batches"])


def validate_uploaded_csv(file: UploadFile, content: bytes, field_name: str) -> None:
    """Validates uploaded CSV file size and extension."""
    if not content or len(content.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "EMPTY_FILE",
                    "message": f"Uploaded file for '{field_name}' is empty.",
                    "field": field_name,
                }
            },
        )
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "message": f"Uploaded file '{file.filename or field_name}' exceeds maximum allowed size of {settings.max_upload_size_bytes} bytes ({settings.max_upload_size_bytes // (1024 * 1024)}MB).",
                    "field": field_name,
                }
            },
        )
    filename = (file.filename or "").lower()
    if filename and not filename.endswith((".csv", ".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_FILE_TYPE",
                    "message": f"Invalid file type for '{field_name}'. Expected a CSV file (.csv).",
                    "field": field_name,
                }
            },
        )


@router.post(
    "",
    response_model=BatchSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Trigger a reconciliation batch run",
)
async def create_and_run_batch(
    request: Request,
    bank_csv: UploadFile = File(..., description="Bank statement CSV file"),
    ledger_csv: UploadFile = File(..., description="Internal ledger/order CSV file"),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
):
    key = idempotency_key or str(uuid.uuid4())
    batch, is_new = await BatchRepo.create(db, key)

    bank_bytes = await bank_csv.read()
    ledger_bytes = await ledger_csv.read()

    validate_uploaded_csv(bank_csv, bank_bytes, "bank_csv")
    validate_uploaded_csv(ledger_csv, ledger_bytes, "ledger_csv")

    meta = build_metadata_from_request(request)

    if not is_new and batch.status == BatchStatus.COMPLETED:
        # Return existing completed batch summary (§7.2)
        reporter = ReporterAgent()
        report = await reporter.generate_report(batch.id, db)
        return BatchSummaryResponse(
            batch_id=batch.id,
            status=batch.status.value,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            record_match_rate=report.record_match_rate,
            amount_coverage=report.amount_coverage,
            total_records=report.total_records,
            matched_records=report.matched_records,
            exception_count=report.exception_count,
            reason_code_breakdown=report.reason_code_breakdown,
            match_method_breakdown=report.match_method_breakdown,
            duplicate_ledger_order_ids=batch.duplicate_ledger_order_ids,
            skipped_rows=batch.skipped_rows,
            metadata=meta,
        )

    orchestrator = BatchOrchestrator()
    try:
        report = await orchestrator.run_pipeline(
            batch_id=batch.id,
            bank_csv_content=bank_bytes,
            ledger_csv_content=ledger_bytes,
            db=db,
        )
        updated_batch = await BatchRepo.get_by_id(db, batch.id)
        return BatchSummaryResponse(
            batch_id=batch.id,
            status=updated_batch.status.value if updated_batch else BatchStatus.COMPLETED.value,
            started_at=updated_batch.started_at if updated_batch else batch.started_at,
            completed_at=updated_batch.completed_at if updated_batch else None,
            record_match_rate=report.record_match_rate,
            amount_coverage=report.amount_coverage,
            total_records=report.total_records,
            matched_records=report.matched_records,
            exception_count=report.exception_count,
            reason_code_breakdown=report.reason_code_breakdown,
            match_method_breakdown=report.match_method_breakdown,
            duplicate_ledger_order_ids=updated_batch.duplicate_ledger_order_ids if updated_batch else 0,
            skipped_rows=updated_batch.skipped_rows if updated_batch else 0,
            metadata=meta,
        )
    except Exception as e:
        logger.exception("Batch execution failed: %s", str(e))
        updated_batch = await BatchRepo.get_by_id(db, batch.id)
        current_status = updated_batch.status.value if updated_batch else BatchStatus.FAILED_RECONCILIATION.value
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": current_status,
                    "message": f"Reconciliation batch failed: {str(e)}",
                    "batch_id": str(batch.id),
                }
            },
        )


@router.get(
    "/{batch_id}",
    response_model=BatchSummaryResponse,
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Get status and reconciliation summary of a batch",
)
async def get_batch_summary(
    batch_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    batch = await BatchRepo.get_by_id(db, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Batch {batch_id} not found"}},
        )

    reporter = ReporterAgent()
    report = await reporter.generate_report(batch.id, db)
    meta = build_metadata_from_request(request)

    return BatchSummaryResponse(
        batch_id=batch.id,
        status=batch.status.value,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        record_match_rate=report.record_match_rate,
        amount_coverage=report.amount_coverage,
        total_records=report.total_records,
        matched_records=report.matched_records,
        exception_count=report.exception_count,
        reason_code_breakdown=report.reason_code_breakdown,
        match_method_breakdown=report.match_method_breakdown,
        duplicate_ledger_order_ids=batch.duplicate_ledger_order_ids,
        skipped_rows=batch.skipped_rows,
        metadata=meta,
    )


@router.get(
    "/{batch_id}/exceptions",
    response_model=PaginatedResponse[ExceptionListItem],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Get paginated list of exceptions with reason codes",
)
async def get_batch_exceptions(
    batch_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    batch = await BatchRepo.get_by_id(db, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Batch {batch_id} not found"}},
        )

    items, total = await ReconciliationResultRepo.get_exceptions_paginated(
        db=db,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )

    data = []
    for item, s_utr, b_utr, l_order_id in items:
        amounts = None
        if item.expected_amount_paise is not None and item.actual_amount_paise is not None and item.difference_paise is not None:
            amounts = AmountDetail(
                expected_paise=item.expected_amount_paise,
                actual_paise=item.actual_amount_paise,
                difference_paise=item.difference_paise,
            )
        data.append(
            ExceptionListItem(
                result_id=item.id,
                result_scope=item.result_scope.value if hasattr(item.result_scope, "value") else str(item.result_scope),
                payment_id=item.payment_id,
                settlement_id=item.settlement_id,
                bank_entry_id=item.bank_entry_id,
                ledger_entry_id=item.ledger_entry_id,
                settlement_utr=s_utr,
                bank_entry_utr=b_utr,
                ledger_order_id=l_order_id,
                decision="EXCEPTION",
                reason_code=item.reason_code,
                match_method=item.match_method,
                matcher_version=item.matcher_version,
                amounts=amounts,
            )
        )

    meta = build_metadata_from_request(request)
    return PaginatedResponse(data=data, total=total, limit=limit, offset=offset, metadata=meta)


@router.get(
    "/{batch_id}/matches",
    response_model=PaginatedResponse[MatchListItem],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Get paginated list of successful matches",
)
async def get_batch_matches(
    batch_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    batch = await BatchRepo.get_by_id(db, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Batch {batch_id} not found"}},
        )

    items, total = await ReconciliationResultRepo.get_matches_paginated(
        db=db,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )

    data = []
    for item, s_utr, b_utr, l_order_id in items:
        amounts = None
        if item.expected_amount_paise is not None and item.actual_amount_paise is not None and item.difference_paise is not None:
            amounts = AmountDetail(
                expected_paise=item.expected_amount_paise,
                actual_paise=item.actual_amount_paise,
                difference_paise=item.difference_paise,
            )
        data.append(
            MatchListItem(
                result_id=item.id,
                result_scope="PAYMENT",
                payment_id=item.payment_id or "",
                settlement_id=item.settlement_id,
                bank_entry_id=item.bank_entry_id,
                ledger_entry_id=item.ledger_entry_id,
                settlement_utr=s_utr,
                bank_entry_utr=b_utr,
                ledger_order_id=l_order_id,
                decision="MATCH",
                match_method=item.match_method,
                matcher_version=item.matcher_version,
                amounts=amounts,
            )
        )

    meta = build_metadata_from_request(request)
    return PaginatedResponse(data=data, total=total, limit=limit, offset=offset, metadata=meta)


@router.post(
    "/{batch_id}/retry",
    response_model=BatchSummaryResponse,
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Retry a failed batch run",
)
async def retry_failed_batch(
    batch_id: uuid.UUID,
    request: Request,
    bank_csv: UploadFile | None = File(default=None, description="Optional bank CSV if retrying from ingestion failure"),
    ledger_csv: UploadFile | None = File(default=None, description="Optional ledger CSV if retrying from ingestion failure"),
    db: AsyncSession = Depends(get_db),
):
    batch = await BatchRepo.get_by_id(db, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Batch {batch_id} not found"}},
        )

    if batch.status == BatchStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": f"Cannot retry completed batch. Status is already '{batch.status.value}'.",
                }
            },
        )

    orchestrator = BatchOrchestrator()

    if batch.status in (
        BatchStatus.FAILED_INGESTION,
        BatchStatus.CREATED,
        BatchStatus.INGESTING,
        BatchStatus.INGESTED,
    ):
        bank_bytes = await bank_csv.read() if bank_csv else None
        ledger_bytes = await ledger_csv.read() if ledger_csv else None

        if bank_csv and bank_bytes:
            validate_uploaded_csv(bank_csv, bank_bytes, "bank_csv")
        if ledger_csv and ledger_bytes:
            validate_uploaded_csv(ledger_csv, ledger_bytes, "ledger_csv")

        if not (bank_bytes and ledger_bytes):
            from pathlib import Path
            fixture_fallback_allowed = os.getenv("USE_FIXTURES", "0") == "1"
            project_root = Path(__file__).resolve().parents[3]
            b_path = project_root / "data" / "synthetic_bank_statement.csv"
            l_path = project_root / "data" / "synthetic_ledger.csv"
            if (
                fixture_fallback_allowed
                and b_path.exists()
                and l_path.exists()
            ):
                logger.warning(
                    "Batch %s retry: using synthetic demo CSVs (USE_FIXTURES=1)", batch_id
                )
                bank_bytes = b_path.read_bytes()
                ledger_bytes = l_path.read_bytes()
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": {
                            "code": "MISSING_INPUT_DATA",
                            "message": "Cannot retry FAILED_INGESTION batch without bank_csv and ledger_csv files.",
                        }
                    },
                )

        report = await orchestrator.run_pipeline(
            batch_id=batch.id,
            bank_csv_content=bank_bytes,
            ledger_csv_content=ledger_bytes,
            db=db,
        )
    else:
        bank_entries = await BankEntryRepo.get_by_batch(db, batch_id)
        settlements = await SettlementRepo.get_by_batch(db, batch_id)

        if bank_entries and settlements:
            await BatchRepo.update_status(db, batch_id, BatchStatus.RECONCILING)
            candidates = await orchestrator.matcher.run_match(batch_id, db)
            await orchestrator.validator.validate_and_persist(candidates, batch_id, db)
            report = await orchestrator.reporter.generate_report(batch_id, db)
            await BatchRepo.update_status(db, batch_id, BatchStatus.COMPLETED, completed=True)
        else:
            bank_bytes = await bank_csv.read() if bank_csv else None
            ledger_bytes = await ledger_csv.read() if ledger_csv else None
            if bank_csv and bank_bytes:
                validate_uploaded_csv(bank_csv, bank_bytes, "bank_csv")
            if ledger_csv and ledger_bytes:
                validate_uploaded_csv(ledger_csv, ledger_bytes, "ledger_csv")

            if bank_bytes and ledger_bytes:
                report = await orchestrator.run_pipeline(
                    batch_id=batch.id,
                    bank_csv_content=bank_bytes,
                    ledger_csv_content=ledger_bytes,
                    db=db,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": {
                            "code": "MISSING_INGESTED_DATA",
                            "message": "Batch ingestion artifacts are incomplete. Provide bank_csv and ledger_csv to re-run the full pipeline.",
                        }
                    },
                )

    meta = build_metadata_from_request(request)
    updated_batch = await BatchRepo.get_by_id(db, batch.id)
    return BatchSummaryResponse(
        batch_id=batch.id,
        status=updated_batch.status.value if updated_batch else BatchStatus.COMPLETED.value,
        started_at=updated_batch.started_at if updated_batch else batch.started_at,
        completed_at=updated_batch.completed_at if updated_batch else None,
        record_match_rate=report.record_match_rate,
        amount_coverage=report.amount_coverage,
        total_records=report.total_records,
        matched_records=report.matched_records,
        exception_count=report.exception_count,
        reason_code_breakdown=report.reason_code_breakdown,
        match_method_breakdown=report.match_method_breakdown,
        duplicate_ledger_order_ids=updated_batch.duplicate_ledger_order_ids if updated_batch else 0,
        skipped_rows=updated_batch.skipped_rows if updated_batch else 0,
        metadata=meta,
    )
