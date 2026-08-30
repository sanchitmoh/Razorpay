from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.razorpay_client import RazorpayClient, RazorpayIngestionError
from app.models.bank_entry import BankEntry
from app.models.enums import BatchStatus
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.repositories.bank_entry_repo import BankEntryRepo
from app.repositories.batch_repo import BatchRepo
from app.repositories.ledger_repo import LedgerRepo
from app.repositories.payment_repo import PaymentRepo

logger = logging.getLogger(__name__)


def _parse_paise(raw: str) -> int:
    """Strict integer-paise parse. Fractional values are corrupt data -> ValueError
    (never route money through float; int(float("5000.5")) silently truncates)."""
    s = raw.strip()
    try:
        return int(s)
    except ValueError:
        f = float(s)  # accepts Excel-style "10000.0"; rejects "5000.5"
        if f.is_integer() and abs(f) < 2**53:
            return int(f)
        raise ValueError(f"non-integral paise value {raw!r}") from None


def parse_razorpay_payment_dict(p: dict[str, Any]) -> Payment:
    """
    Convert a raw Razorpay payment entity dict to a Payment ORM model.
    Shared by IngestionAgent (batch pull) and WebhookProcessor (push event).
    """
    # Prefer captured_at timestamp over created_at (§3)
    raw_timestamp = p.get("captured_at") if p.get("captured_at") is not None else p.get("created_at")
    captured_dt = None
    if raw_timestamp is not None:
        if isinstance(raw_timestamp, (int, float)):
            captured_dt = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
        elif isinstance(raw_timestamp, str):
            try:
                captured_dt = datetime.fromisoformat(raw_timestamp)
                if captured_dt.tzinfo is None:
                    captured_dt = captured_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

    return Payment(
        id=p["id"],
        order_id=p.get("order_id") or f"order_{p['id']}",
        amount_paise=int(p["amount"]),
        fee_paise=int(p.get("fee") or 0),
        tax_paise=int(p.get("tax") or 0),
        status=p.get("status", "captured"),
        captured_at=captured_dt,
    )


class IngestionError(Exception):
    """Raised when an unrecoverable ingestion error occurs."""
    pass


class IngestionAgent:
    def __init__(self, razorpay_client: RazorpayClient | None = None) -> None:
        self.razorpay_client = razorpay_client or RazorpayClient()

    async def run(
        self,
        batch_id: uuid.UUID,
        bank_csv_content: str | bytes,
        ledger_csv_content: str | bytes,
        db: AsyncSession,
    ) -> tuple[list[Payment], list[BankEntry], list[LedgerEntry]]:
        """
        Executes ingestion for a batch:
          1. Sets batch status -> INGESTING
          2. Pulls captured payments from Razorpay
          3. Parses bank statement CSV with row-level error handling (scoped to batch_id)
          4. Parses ledger CSV with row-level error handling (scoped to batch_id)
          5. Tracks data quality metrics (duplicates, skipped rows)
          6. Sets batch status -> INGESTED
        """
        await BatchRepo.update_status(db, batch_id, BatchStatus.INGESTING)

        try:
            # 1. Fetch Razorpay Payments
            try:
                raw_payments = await self.razorpay_client.fetch_captured_payments()
            except RazorpayIngestionError as e:
                logger.error("Failed to fetch payments from Razorpay: %s", str(e))
                await BatchRepo.update_status(db, batch_id, BatchStatus.FAILED_INGESTION)
                raise IngestionError(f"Razorpay API ingestion failure: {str(e)}") from e

            payment_models: list[Payment] = [parse_razorpay_payment_dict(p) for p in raw_payments]

            await PaymentRepo.bulk_upsert(db, payment_models)
            logger.info("Ingested %d payments into database.", len(payment_models))

            # 2. Ingest Bank CSV
            bank_entries, bank_skipped = self._parse_bank_csv(bank_csv_content, batch_id)
            await BankEntryRepo.bulk_insert(db, bank_entries)
            logger.info("Ingested %d bank entries into database for batch %s.", len(bank_entries), batch_id)

            # 3. Ingest Ledger CSV
            ledger_entries, ledger_skipped, duplicate_count = self._parse_ledger_csv(ledger_csv_content, batch_id)
            await LedgerRepo.bulk_insert(db, ledger_entries)
            logger.info("Ingested %d ledger entries into database for batch %s.", len(ledger_entries), batch_id)

            # 4. Update data quality metrics
            total_skipped = bank_skipped + ledger_skipped
            await BatchRepo.update_data_quality_metrics(db, batch_id, duplicate_count, total_skipped)
            if duplicate_count > 0:
                logger.warning("Batch %s: %d duplicate order_ids in ledger CSV", batch_id, duplicate_count)
            if total_skipped > 0:
                logger.warning("Batch %s: %d rows skipped (malformed/missing data)", batch_id, total_skipped)

            await BatchRepo.update_status(db, batch_id, BatchStatus.INGESTED)
            return payment_models, bank_entries, ledger_entries

        except IngestionError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during batch ingestion: %s", str(e))
            await BatchRepo.update_status(db, batch_id, BatchStatus.FAILED_INGESTION)
            raise IngestionError(f"Unexpected ingestion failure: {str(e)}") from e

    def _parse_bank_csv(self, content: str | bytes, batch_id: uuid.UUID) -> tuple[list[BankEntry], int]:
        """Parse bank CSV and return (entries, skipped_count)"""
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        if text.startswith('\ufeff'):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text.strip()))

        required_cols = {"utr", "amount_paise", "value_date"}
        if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
            missing = required_cols - set(reader.fieldnames or [])
            raise IngestionError(f"Bank CSV missing required columns: {missing}")

        entries: list[BankEntry] = []
        skipped_count = 0
        
        for row_idx, row in enumerate(reader, start=1):
            try:
                utr = (row.get("utr") or "").strip()
                if not utr:
                    logger.warning("Row %d: missing UTR, skipping", row_idx)
                    skipped_count += 1
                    continue
                amount = _parse_paise(row["amount_paise"])
                v_date = date.fromisoformat(row["value_date"].strip())
                narration = (row.get("narration") or "").strip() or None

                entries.append(
                    BankEntry(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        utr=utr,
                        amount_paise=amount,
                        value_date=v_date,
                        narration=narration,
                    )
                )
            except (ValueError, KeyError) as e:
                logger.warning("Row %d malformed in Bank CSV (%s), skipping row.", row_idx, str(e))
                skipped_count += 1
                continue

        return entries, skipped_count

    def _parse_ledger_csv(self, content: str | bytes, batch_id: uuid.UUID) -> tuple[list[LedgerEntry], int, int]:
        """Parse ledger CSV and return (entries, skipped_count, duplicate_count)"""
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        if text.startswith('\ufeff'):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text.strip()))

        required_cols = {"order_id", "expected_amount_paise"}
        if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
            missing = required_cols - set(reader.fieldnames or [])
            raise IngestionError(f"Ledger CSV missing required columns: {missing}")

        entries: list[LedgerEntry] = []
        skipped_count = 0
        seen_order_ids: set[str] = set()
        duplicate_count = 0
        
        for row_idx, row in enumerate(reader, start=1):
            try:
                order_id = (row.get("order_id") or "").strip()
                if not order_id:
                    logger.warning("Row %d: missing order_id, skipping", row_idx)
                    skipped_count += 1
                    continue
                
                # Track duplicates (US7)
                if order_id in seen_order_ids:
                    duplicate_count += 1
                    logger.debug("Row %d: duplicate order_id '%s'", row_idx, order_id)
                else:
                    seen_order_ids.add(order_id)
                
                amount = _parse_paise(row["expected_amount_paise"])
                cust_ref = (row.get("customer_ref") or "").strip() or None
                inv_date_str = (row.get("invoice_date") or "").strip()
                inv_date = date.fromisoformat(inv_date_str) if inv_date_str else None

                entries.append(
                    LedgerEntry(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        order_id=order_id,
                        expected_amount_paise=amount,
                        customer_ref=cust_ref,
                        invoice_date=inv_date,
                    )
                )
            except (ValueError, KeyError) as e:
                logger.warning("Row %d malformed in Ledger CSV (%s), skipping row.", row_idx, str(e))
                skipped_count += 1
                continue

        return entries, skipped_count, duplicate_count
