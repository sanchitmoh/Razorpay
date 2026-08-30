# PRD: Adversarial Test Suite — Real-World Parameters & Edge Cases

## Problem Statement

The 34 existing tests pass on happy paths and fixture data. Real reconciliation runs
against real bank exports, real Razorpay payloads, and messy operator behavior will hit
inputs no fixture models: Excel-exported CSVs, decimal amounts in paise columns,
duplicate ledger rows, crashed batches retried without files, multi-batch databases.
We do not know which of these break correctness today. Silent money loss (a dropped
bank row, a truncated amount) is worse than a crash and must be surfaced.

## Solution

An adversarial test suite (`tests/test_adversarial.py`) that feeds the pipeline
realistic hostile inputs through public interfaces only (CSV upload endpoints, agent
entry points, HTTP API contracts). Every failure is either a confirmed bug (fixed at
root cause, red-green) or a pinned design decision (documented here).

## Fixed Defects (verified & resolved)

| ID | Original Defect | Fix | Severity |
|----|-----------------|-----|----------|
| H1 | `POST /batches/{id}/retry` with no files silently fell back to `data/synthetic_*.csv` from disk and marked batch COMPLETED — fabricated results in prod path | Now refuses retry without files (400 MISSING_INPUT_DATA) unless `USE_FIXTURES=1` env var explicitly enables test-mode fallback | High |
| H2 | Retry of FAILED_RECONCILIATION batch missing settlements would rebuild from global `Payment` table — cross-batch contamination risk | Now refuses retry when ingestion artifacts (bank_entries, settlements) incomplete; requires fresh upload with files (400 MISSING_INGESTED_DATA) | High |
| H3 | `int(float(row["amount_paise"]))` truncated decimals ("10050.9" → 10050) — silent money corruption at trust boundary | `_parse_paise()` now rejects non-integral decimal values with ValueError; only accepts whole numbers or float representations of integers (e.g., "10000.0" from Excel) | High |
| H4 | UTF-8-BOM bank CSV (standard Excel export) failed required-column check → whole batch FAILED_INGESTION | CSV parser now strips UTF-8 BOM (`\ufeff`) prefix; Excel-exported "CSV UTF-8" files ingest cleanly | Medium |
| H6 | Paginated `/exceptions` + `/matches` had no ORDER BY → page contents unstable, rows could duplicate/vanish across pages | Both `get_exceptions_paginated` and `get_matches_paginated` now use `.order_by(ReconciliationResult.id)` for deterministic, stable pagination | Medium |

## Suspected Defects Under Test (hypotheses to verify)

None remaining — all suspected defects have been verified as either fixed (H1-H4, H6) or pinned working-as-designed (H5 → P8).

## Pinned Behaviors (verified & documented, not changed without owner sign-off)

- P1: Any payment with `amount_paise <= 0` fails the whole batch (fail-closed poison-pill). One bad payment blocks a day's reconciliation.
- P2: Payments with `captured_at=None` group under server-local `date.today()` — timezone-dependent, non-deterministic across hosts.
- P3: Malformed CSV rows are skipped silently — batch completes; dropped rows appear nowhere in metrics. **P3 visibility implemented**: `skipped_rows` count added to batch summary showing total malformed/missing data rows.
- P4: Negative bank amounts (debit/reversal rows) ingest as-is; become orphan exceptions.
- P5: `difference_paise` semantics vary by branch: bank variance for amount checks vs payment-minus-ledger for ledger mismatches.
- P6: Empty/header-only CSVs complete with 100% exceptions (honest zeros).
- P7: Re-POST of same idempotency key on non-completed batch re-runs pipeline with the new files.
- P8: Duplicate `order_id` rows in ledger CSV ingest as separate DB rows; matcher uses last-wins dict comprehension (deterministic but order-dependent). **US7 implemented**: `duplicate_ledger_order_ids` count added to batch summary for visibility. Operators can now see duplicate counts in API responses and logs.

## User Stories

1. As an ops engineer, I want Excel-exported (BOM) bank CSVs to ingest, so that real bank downloads work without hand-editing.
2. As an ops engineer, I want paise amounts parsed as exact integers, so that no rupee ever shifts due to float math.
3. As an ops engineer, I want a decimal value in an integer column rejected loudly, so that corrupted rows don't silently change totals.
4. As a finance reviewer, I want retry-without-files to refuse rather than reconcile stale demo files, so that production reports never contain synthetic data.
5. As a finance reviewer, I want each batch's report to cover only that batch's payments, so that coverage percentages mean something.
6. As an API consumer, I want stable pagination, so that paging the exception list neither duplicates nor drops rows.
7. As an ops engineer, I want duplicate ledger order_ids surfaced, so that source-system key errors are visible instead of absorbed.
8. As a QA engineer, I want unicode narrations preserved end-to-end, so that regional-language bank text survives to the dashboard.
9. As an ops engineer, I want empty uploads to produce honest zero/exception reports, so that "completed" never masquerades as "reconciled".
10. As an operator, I want a stuck mid-crash batch to be retryable deterministically, so that recovery never imports another batch's data.

## Implementation Decisions

- Tests exercise public interfaces only: HTTP endpoints via the app client, agent public methods. No private-method poking (TDD skill rule).
- Razorpay pull is monkeypatched at class level where e2e control of payment sets is needed; CSV content is passed directly as bytes.
- Confirmed bugs get minimal root-cause fixes; pinned behaviors get tests that document current behavior plus this PRD entry.
- No schema changes unless H2's honest fix requires one; preferred H2 resolution is refusing the unreliable path over new bookkeeping.

## Testing Decisions

- Good tests verify observable outcomes (HTTP status, response body, DB-visible rows), not internal call shapes.
- Prior art: `tests/test_batch_e2e.py` (client + db_session fixtures), `tests/test_matcher.py` (direct agent calls against seeded session).
- Each red-green cycle: write one failing test → minimal fix → full suite rerun.

## Out of Scope

- Auth/RBAC on endpoints (buildathon scope).
- Concurrency/load testing beyond existing idempotency tests.
- Changing settlement-grouping domain rules (§3) or LLM classifier behavior.
- Fixing P1–P7 semantics without owner approval.

## Further Notes

H1–H4, H6 were real defects caught during initial adversarial testing; all are now fixed at root cause:
- H1 fix: Refuses fallback to on-disk synthetic files unless `USE_FIXTURES=1` 
- H2 fix: Refuses retry when ingestion artifacts missing; prevents cross-batch Payment table contamination
- H6 fix: Pagination queries use `.order_by(ReconciliationResult.id)` for stable, deterministic results

H5 confirmed as working-as-designed: moved to P8 (pinned behavior). Duplicate ledger order_ids are last-wins-silent; future enhancement could add visibility counter to batch summary.

Pattern to watch: any prod code path reading test/demo artifacts.
