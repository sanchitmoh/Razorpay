from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from app.schemas.responses import APIMetadata

T = TypeVar("T")


class AmountDetail(BaseModel):
    expected_paise: int
    actual_paise: int
    difference_paise: int


class BatchSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: uuid.UUID
    status: Literal[
        "CREATED",
        "INGESTING",
        "INGESTED",
        "RECONCILING",
        "COMPLETED",
        "FAILED_INGESTION",
        "FAILED_RECONCILIATION",
    ]
    started_at: datetime
    completed_at: datetime | None = None
    record_match_rate: float | None = None
    amount_coverage: float | None = None
    total_records: int | None = None
    matched_records: int | None = None
    exception_count: int | None = None
    reason_code_breakdown: dict[str, int] | None = None
    match_method_breakdown: dict[str, int] | None = None
    duplicate_ledger_order_ids: int | None = None  # US7: visibility for duplicate order_ids
    skipped_rows: int | None = None  # P3: visibility for malformed CSV rows
    metadata: APIMetadata | None = None


class ExceptionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: uuid.UUID
    result_scope: Literal["PAYMENT", "ORPHAN_BANK_ENTRY"]
    payment_id: str | None = None
    settlement_id: uuid.UUID | None = None
    bank_entry_id: uuid.UUID | None = None
    ledger_entry_id: uuid.UUID | None = None
    settlement_utr: str | None = None
    bank_entry_utr: str | None = None
    ledger_order_id: str | None = None
    decision: Literal["EXCEPTION"] = "EXCEPTION"
    reason_code: Literal[
        "PARTIAL_SETTLEMENT",
        "DUPLICATE_UTR",
        "MISSING_BANK_ENTRY",
        "MISSING_SETTLEMENT",
        "AMOUNT_MISMATCH",
        "UNRESOLVED_AMBIGUOUS",
    ] | str | None = None
    match_method: str | None = None
    matcher_version: str = "v1"
    amounts: AmountDetail | None = None


class MatchListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: uuid.UUID
    result_scope: Literal["PAYMENT"] = "PAYMENT"
    payment_id: str
    settlement_id: uuid.UUID | None = None
    bank_entry_id: uuid.UUID | None = None
    ledger_entry_id: uuid.UUID | None = None
    settlement_utr: str | None = None
    bank_entry_utr: str | None = None
    ledger_order_id: str | None = None
    decision: Literal["MATCH"] = "MATCH"
    match_method: Literal[
        "EXACT_UTR",
        "ORDER_ID_EXACT",
        "AMOUNT_WITH_FEE_EQUATION",
        "LLM_ASSISTED_NARRATION",
    ] | str | None = None
    matcher_version: str = "v1"
    amounts: AmountDetail | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    total: int
    limit: int
    offset: int
    metadata: APIMetadata | None = None
