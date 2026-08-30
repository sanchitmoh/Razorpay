# Reconciliation Agent — Architecture Plan
**Track:** AI Finance Controller (Razorpay AI Buildathon)
**Scope:** Solo build, buildathon timeline. Optimized for correctness and honest metrics on a 50+ record batch — not production scale.

---

## 1. Project Objective (recap)

Automate the three-way match between a payment gateway's transaction data, a bank statement, and an internal order ledger. Flag genuine mismatches with a specific reason code instead of a generic "unmatched," and report an honest match rate on a full batch rather than a cherry-picked example.

---

## 2. Requirements Brief (Phase 0)

### Functional scope
- **In scope:** ingest 3 data sources → staged reconciliation via Settlement grain (identity → amount equation → LLM-assisted residual, see §14) → classify exceptions with reason codes → report match rate + exception list.
- **Out of scope (explicitly):** real fund movement, live-mode settlements, multi-tenant/auth system, UI beyond a simple dashboard/API response, historical trend analytics.
- **Core job that must work even if everything else slips:** ingest a batch → produce a match rate % and a reason-coded exception list. Everything else (Q&A layer, dashboard polish) is secondary.

### Non-functional constraints
| Constraint | Decision |
|---|---|
| Scale | 1 user (you), 1 batch run at a time, 50–500 records/batch. Not a scale problem. |
| Latency | Batch job, not synchronous user-facing — a few seconds to low minutes is fine. No latency budget engineering needed. |
| Consistency | Strong consistency within a batch (a payment can't be "half matched") — use DB transactions per batch run. |
| Availability | Best-effort. This is a demo/internship artifact, not a live service. |
| Read/write ratio | Write-heavy during ingestion, read-heavy when reviewing exceptions afterward. |
| Team/ops reality | Solo builder, short timeline → favor managed/simple over self-hosted infra. No Kafka, no Kubernetes. |
| Compliance | Test-mode data only, no real PII, no real money. |

**Why Phase 5 (capacity/load engineering) is intentionally skipped:** this is a batch reconciliation job for a single user, not a service under concurrent load. Spending buildathon hours on sharding/throughput math here would be over-engineering relative to the actual problem.

---

## 3. Known Platform Constraint (research finding — state this to judges)

Razorpay's own docs confirm: **test-mode transactions do not appear in real settlement reports**, since settlements are a live-mode banking process gated on account activation. This means the **Settlements API will not return usable data in test mode.**

**Design response:** use the **Payments API** (fully functional in test mode — captured payments carry real `amount`, `fee`, `tax` fields) as the gateway-side source of truth, and treat the "settlement batch" as something you construct yourself by grouping captured payments — mirroring what a real settlement would look like, rather than pretending the Settlements API works in test mode.

**Grouping rule (the part that has to actually be specified, not just gestured at):** one synthetic Settlement per calendar day of `Payment.captured_at`. Razorpay's actual standard cycle is **T+2 working days** (verified against current docs — not T+1, which only applies to POS/UPI-specific or upgraded accounts, and not T+0, which is a paid Instant Settlement feature). Rather than asserting this daily grouping *is* Razorpay's real cycle, state it plainly as what it is: **a deterministic simulation boundary**, chosen because test mode exposes no live settlement data — not a claim about how Razorpay actually batches your specific account. All payments captured on the same day roll into one synthetic Settlement with a self-assigned UTR; the synthetic bank-statement CSV must use that same UTR for the corresponding credit line, since there's no live UTR to draw from.

Say this explicitly in your pitch. It's a real platform limitation you found and designed around — that's exactly the "AI judgment" and "problem taste" signal judges are scoring for, and it's the kind of thing a Razorpay engineer on the panel will immediately recognize as correct.

---

## 4. Domain Model & Glossary (Phase 1)

**Revision note:** the first version of this model treated reconciliation as Payment ↔ BankEntry, one-to-one. That's wrong — confirmed against Razorpay's actual settlement payloads, where **one settlement (`setl_...`) aggregates multiple payments into a single UTR-tagged bank credit**. The model below fixes that: Settlement is now its own entity sitting between Payment and BankEntry.

| Term | Meaning |
|---|---|
| **Payment** | A captured transaction from Razorpay (source: Payments API, test mode) |
| **Settlement** | A batch of payments Razorpay pays out together as one bank credit, carrying its own gross amount, fees, tax, and UTR. In test mode this is **constructed by us** (see §3) rather than pulled from a live Settlements API. |
| **Settlement Line** | The allocation of one Payment's amount into one Settlement (the many-to-one join) |
| **Bank Entry** | A UTR-level line in a bank statement (source: synthetic CSV) |
| **Ledger Entry** | An expected amount tied to an order (source: synthetic CSV / internal system) |
| **Batch** | One reconciliation run over a set of records |
| **Reconciliation Result** | One row per record processed — either a confirmed match (all relevant FKs populated) or an exception (the FK for whatever's missing is null, with a reason code) |
| **Tolerance band** | Acceptable variance in amount, computed from the actual equation `gross − fees − tax ± adjustments = net`, not a blind `abs(a−b) < x` check |

**Invariants:**
- **Batch scoping was underspecified — fixed:** `SETTLEMENT` and `SETTLEMENT_LINE` both now carry `batch_id` directly. Each `POST /batches` run builds its own settlements from whatever it ingests, and the same real-world Payment can legitimately appear in different batches (a later run covering an overlapping date range, a retry against fresh data, etc.) — so the uniqueness constraint that prevents double-counting is **`UNIQUE(batch_id, payment_id)` on `SETTLEMENT_LINE`, not a bare `UNIQUE(payment_id)`**. A global constraint on `payment_id` alone would incorrectly block a payment from ever being reconciled a second time in any future batch.
- A Payment can appear in at most one Settlement Line **within a given batch** (no double-counting reconciled money in that run).
- `SUM(SettlementLine.allocated_amount) <= Payment.amount_paise` for any payment, and `allocated_amount_paise > 0` on every line — a zero or negative allocation is a bug, not data.
- `Settlement.net_amount_paise` is validated equal to `gross_amount_paise − fee_paise − tax_paise + adjustment_paise` at construction time, not just stored as an independent number that could silently drift from the other four.
- **Adjustments — scoped for MVP:** the matching equation in §14 references `± adjustments`; that maps to the new `adjustment_paise` field on `SETTLEMENT`. For the buildathon build, **default it to 0 and don't model refunds/chargebacks/partial-capture adjustments** — the field exists so the schema doesn't lie about what the equation computes, but populating it with real adjustment logic is out of scope. Say this explicitly if asked: "adjustments are modeled as a field, not populated, for this build."
- A Bank Entry can be referenced by at most one Reconciliation Result per batch.
- A `COMPLETED` batch can never have a Reconciliation Result missing (no partial-batch match rates — see §11).

```mermaid
erDiagram
    BATCH ||--o{ SETTLEMENT : contains
    BATCH ||--o{ SETTLEMENT_LINE : contains
    BATCH ||--o{ BANK_ENTRY : contains
    BATCH ||--o{ LEDGER_ENTRY : contains
    BATCH ||--o{ RECONCILIATION_RESULT : contains
    SETTLEMENT ||--o{ SETTLEMENT_LINE : aggregates
    SETTLEMENT ||--o| RECONCILIATION_RESULT : "matched in"
    BANK_ENTRY ||--o| RECONCILIATION_RESULT : "matched in"
    LEDGER_ENTRY ||--o| RECONCILIATION_RESULT : "matched in"
    PAYMENT ||--o| RECONCILIATION_RESULT : "matched in"

    BATCH {
        uuid id PK
        string idempotency_key UK
        string status
        timestamp started_at
        timestamp completed_at
    }
    PAYMENT {
        string id PK
        string order_id
        int amount_paise
        int fee_paise
        int tax_paise
        string status
        timestamp captured_at
    }
    SETTLEMENT {
        uuid id PK
        uuid batch_id FK
        string razorpay_settlement_id
        string utr
        int gross_amount_paise
        int fee_paise
        int tax_paise
        int adjustment_paise
        int net_amount_paise
        date settlement_date
    }
    SETTLEMENT_LINE {
        uuid id PK
        uuid batch_id FK
        uuid settlement_id FK
        string payment_id FK
        int allocated_amount_paise
    }
    BANK_ENTRY {
        uuid id PK
        uuid batch_id FK
        string utr
        int amount_paise
        date value_date
        string narration
    }
    LEDGER_ENTRY {
        uuid id PK
        uuid batch_id FK
        string order_id
        int expected_amount_paise
        string customer_ref
        date invoice_date
    }
    RECONCILIATION_RESULT {
        uuid id PK
        uuid batch_id FK
        string result_scope
        string payment_id FK "nullable"
        uuid settlement_id FK "nullable"
        uuid bank_entry_id FK "nullable"
        uuid ledger_entry_id FK "nullable"
        string decision
        string match_method
        string reason_code "nullable"
        string matcher_version
    }
```

`result_scope` enum: `PAYMENT` (the normal case — inherits its settlement's bank outcome, carries its own ledger outcome) or `ORPHAN_BANK_ENTRY` (the edge case — a bank credit with no captured payment behind it, `payment_id` genuinely null). This makes the nullable-FK exception explicit and queryable instead of relying on "null happens to mean this" — cheap to add, removes any doubt about what a given row represents.

`matcher_version` is one plain string (e.g. `"v1"`), bumped whenever the matching/equation logic changes. Not a request for a versioning framework — just enough to answer "why did the match rate change between two runs of the same batch" without guessing.

`match_method` enum: `EXACT_UTR`, `ORDER_ID_EXACT`, `AMOUNT_WITH_FEE_EQUATION`, `LLM_ASSISTED_NARRATION`. `reason_code` enum (populated only when `decision = EXCEPTION`): `PARTIAL_SETTLEMENT`, `DUPLICATE_UTR`, `MISSING_BANK_ENTRY`, `MISSING_SETTLEMENT`, `AMOUNT_MISMATCH`, `UNRESOLVED_AMBIGUOUS`.

**Why one table (`RECONCILIATION_RESULT`) instead of separate Match + Exception tables:** an unmatched-because-missing record has no match to attach an exception to — a required FK from Exception to a Match row can't represent "the bank entry never existed." Nullable FKs on one row per processed record fixes that cleanly, and it's the same amount of code either way.

**Grain:** the row is per-**Payment**, not per-Settlement (see `result_scope` above). A Settlement's bank-side match (`settlement_id`/`bank_entry_id`) is resolved once and then inherited by every Payment that rolled into it via `SETTLEMENT_LINE` — so five payments in one correctly-matched settlement produce five rows, all pointing at the same `settlement_id`/`bank_entry_id`, each independently carrying its own `ledger_entry_id` outcome. This matters because a settlement can match the bank fine while one payment inside it still fails its ledger check — per-payment grain is what lets that show up as its own exception instead of hiding inside an otherwise-successful settlement.

---

## 5. System Architecture — Layers (Phase 6)

**Pattern chosen:** modular monolith, layered (routes → services/agents → repositories → storage). No microservices — there's no independent-scaling or independent-deployment need here; splitting this into services would just add network calls between things that run fine in one process. This is a deliberate anti-overengineering call.

```mermaid
flowchart TB
    subgraph API["API Layer (FastAPI)"]
        R1["/batches — trigger run"]
        R2["/batches/:id — status & summary"]
        R3["/batches/:id/exceptions"]
        R4["/qa — stretch: ask about a batch"]
    end

    subgraph SVC["Service Layer"]
        ING["Ingestion Service<br/>(Payments API + CSV loaders)"]
        SETL["Settlement Builder<br/>(groups Payments into Settlements, since test-mode<br/>has no live Settlements API — see §3)"]
        MATCH["Matcher<br/>(staged: identity → amount equation → residual)"]
        VALID["Validator<br/>(classifies exceptions → reason codes)"]
        REP["Report Generator<br/>(record match rate + amount coverage + exceptions)"]
        LLM["LLM-assisted classifier<br/>(narration extraction only, bounded — see §5.1)"]
    end

    subgraph REPO["Repository Layer"]
        PR["PaymentRepo"]
        SR["SettlementRepo / SettlementLineRepo"]
        BR["BankEntryRepo"]
        LR["LedgerRepo"]
        RR["ReconciliationResultRepo"]
    end

    subgraph DATA["Storage"]
        PG[("PostgreSQL")]
    end

    R1 --> ING --> SETL --> MATCH --> VALID --> REP
    VALID -.ambiguous case only, extraction not authority.-> LLM
    LLM -.-> VALID
    R2 --> REP
    R3 --> RR
    MATCH --> PR & SR & BR & LR
    VALID --> RR
    PR & SR & BR & LR & RR --> PG
```

**Deletion test applied:** the `LLM-assisted classifier` is a separate module because it has a genuinely different failure mode (non-deterministic) from the rule-based Matcher/Validator — worth isolating so a bad LLM call can't silently corrupt deterministic matches. The `Settlement Builder` is separate because it's the one piece of domain logic unique to the test-mode workaround (§3) — isolating it means if Razorpay ever gives you real settlement data, you delete this module and point Ingestion straight at it, nothing else changes. Everything else stays as plain function calls; no interface was added for things with only one implementation.

### 5.1 LLM boundary (hard rule)

The LLM may **extract or suggest evidence** from unstructured text (e.g., a bank narration string) as constrained structured output (a fixed JSON schema — candidate order ID, candidate settlement reference, confidence note). It may **never directly write a match decision to the database**. Every LLM output is re-validated by the deterministic Validator before it can produce a `RECONCILIATION_RESULT`. This matters for two reasons: it keeps the "if I removed the LLM, does the core system still work?" answer honestly "yes," and it means untrusted external text (a bank narration is not something you control) can't manipulate financial state — it can only ever produce a *candidate* that a rule still has to approve.

---

## 6. Data Flow (Phase 3)

**Happy path — one batch run, traced end to end:**

```mermaid
sequenceDiagram
    participant U as You (trigger)
    participant API as API Layer
    participant ING as Ingestion
    participant RZP as Razorpay Payments API
    participant MATCH as Matcher
    participant VALID as Validator
    participant DB as PostgreSQL
    participant REP as Report Generator

    U->>API: POST /batches (bank.csv, ledger.csv, Idempotency-Key)
    API->>DB: check idempotency_key on BATCH
    alt key already seen
        DB-->>API: existing batch
        API-->>U: same batch, no re-ingestion
    else new key
        API->>ING: start_batch(status=INGESTING)
        ING->>RZP: GET /v1/payments (test mode)
        RZP-->>ING: captured payments (amount, fee, tax)
        ING->>DB: persist Payments, BankEntries, LedgerEntries
        ING->>DB: status=INGESTED
        ING->>MATCH: build_settlements() then run_match(batch_id)
        MATCH->>DB: group Payments into synthetic Settlements (§3, §4)
        MATCH->>DB: staged match — identity, then amount equation
        MATCH-->>VALID: unresolved candidates only
    end
    VALID->>VALID: assign reason_code (rule-based first)
    alt genuinely ambiguous
        VALID->>VALID: LLM-assisted classification (bounded, logged)
    end
    VALID->>DB: persist ReconciliationResults (match or exception, nullable FKs)
    MATCH->>REP: batch complete
    REP->>DB: compute match_rate, exception summary
    REP-->>API: batch report
    API-->>U: match_rate %, exceptions[]
```

**Failure path — what happens if the Razorpay API call fails mid-batch:**
- Ingestion wraps the Payments API call with a retry (2 attempts, backoff) and a timeout.
- On persistent failure, the batch is marked `status = FAILED_INGESTION`, not silently partial — you never want a match rate computed against an incomplete payment set.
- Bank/ledger CSV parsing errors (bad row, missing column) are caught per-row and logged as a `row-level ingestion exception`, not a batch-level crash — one malformed CSV row shouldn't kill the whole run.
- `BATCH.status` is a small explicit state machine: `CREATED → INGESTING → INGESTED → RECONCILING → COMPLETED`, with `FAILED_INGESTION` / `FAILED_RECONCILIATION` as terminal failure states. A crash mid-run leaves the batch visibly stuck at whatever state it was last in — never silently reported as complete. Re-running a stuck batch is explicit, not automatic: a `POST /batches/{id}/retry` is only accepted when status is one of the `FAILED_*` states — this stays simple on purpose, no stale-timeout detection or auto-recovery logic.
- Duplicate UTRs in the bank CSV are **detected**, not prevented at the DB layer — a `GROUP BY utr HAVING COUNT(*) > 1` check during matching, surfaced as a `DUPLICATE_UTR` exception. A hard uniqueness constraint on `utr` would reject the row instead of flagging the exact problem you're supposed to catch.
- Razorpay's Payments API paginates (`count`/`skip`), so a batch above the single-call limit needs a fetch loop, not one call. If any page fails partway through, the whole batch goes to `FAILED_INGESTION` — never a match rate computed against a partial payment set.

**State ownership:** PostgreSQL is the single source of truth for everything after ingestion. Razorpay's API is the source of truth for Payment data only until it's pulled — no caching layer needed at this scale.

---

## 7. API Design (Phase 2)

### 7.1 External API — Razorpay (consumed)
| Purpose | Endpoint | Mode | Notes |
|---|---|---|---|
| Fetch captured payments | `GET /v1/payments` | Test | Primary data source. Filter by `status=captured`. |
| Fetch a single payment | `GET /v1/payments/:id` | Test | For drill-down on an exception. |
| ~~Settlements~~ | ~~`GET /v1/settlements`~~ | — | **Not usable in test mode** — see §3. Do not build against this. |

Auth: Basic Auth with test Key ID/Secret, loaded from env vars — never committed.

### 7.2 Internal API (exposed by your service)

| Method | Path | Auth Required | Purpose |
|---|---|:---:|---|
| `POST` | `/api/v1/batches` | Optional `X-API-Key` | Upload bank CSV + ledger CSV, trigger a reconciliation run against current test-mode payments |
| `GET` | `/api/v1/batches/{batch_id}` | Optional `X-API-Key` | Batch status + summary (match rate, counts, quality metrics) |
| `GET` | `/api/v1/batches/{batch_id}/exceptions` | Optional `X-API-Key` | Paginated list of exceptions with reason codes |
| `GET` | `/api/v1/batches/{batch_id}/matches` | Optional `X-API-Key` | Paginated list of successful matches |
| `POST` | `/api/v1/batches/{batch_id}/retry` | Optional `X-API-Key` | Re-run a failed batch. Only accepted when status is `FAILED_INGESTION` or `FAILED_RECONCILIATION`; returns 409 otherwise |
| `GET` | `/api/v1/health` | Public | Health check — returns `{ "status": "ok", "db": "connected", "version": "1.0.0", "uptime_seconds": 12.3, "checks": {...} }` |
| `POST` | `/api/v1/qa` | Optional `X-API-Key` | Ask a natural language question about a batch, answered via grounded RAG over reconciled data |
| `POST` | `/api/v1/webhooks/razorpay` | `X-Razorpay-Signature` | Near-real-time push ingestion with constant-time HMAC-SHA256 verification |
| `GET` | `/api/v1/webhooks/stats` | Optional `X-API-Key` | Webhook ingestion statistics and counts |

**Auth & Rate Limiting:**
- **API Key Authentication**: Configurable via `API_KEY_ENABLED` and `API_KEY`. When enabled, requests require a valid `X-API-Key` header; when disabled (default), endpoints work seamlessly for local demo dashboards.
- **Provider-Agnostic Token Bucket Rate Limiting**: All routes are protected by a continuous Token Bucket rate limiter (`RATE_LIMIT_CAPACITY`, `RATE_LIMIT_REFILL_RATE`). Works with **any Redis provider** via `REDIS_URL` (AWS ElastiCache, Redis Cloud, Docker, Azure, Dragonfly), **Upstash Redis REST API** (via `UPSTASH_REDIS_REST_URL`), or local in-memory fallback.
- **Webhook Security**: Constant-time HMAC-SHA256 signature verification (`hmac.compare_digest`) with fail-closed 503 behavior if secrets are unconfigured.

**Contract notes:**
- Idempotency: `POST /batches` accepts an `Idempotency-Key` header, stored as a **unique column on `BATCH`** — the actual guarantee comes from the DB constraint, not an app-level check-then-create.
- Errors & Metadata: All responses return standardized `APIMetadata` (`request_id`, `timestamp`, `version`, `duration_ms`). Errors return `{ "error": { "code": "<ERROR_CODE>", "message": "<msg>", "field": "<field>" }, "metadata": {...} }` with HTTP status codes (400, 401, 404, 409, 413, 422, 429, 500, 503).
- Input Validation: File uploads validated up to 100MB (`MAX_UPLOAD_SIZE_BYTES`), QA questions up to 4000 chars (`QA_MAX_QUESTION_LENGTH`) with HTML entity escaping and prompt injection delimiters.
- Pagination: simple `limit`/`offset` on exception/match lists. Defaults: `limit=50`, `offset=0`, max `limit=200`. Response envelope: `{ "data": [...], "total": N, "limit": N, "offset": N, "metadata": {...} }`.
- CORS: Configured via `CORS_ALLOWED_ORIGINS` (defaults to `*` for demo, customizable for production).

### 7.3 Response Schemas (Pydantic)

These are the core response shapes — defined here so the contract is clear before implementation. Request: `POST /batches` accepts `multipart/form-data` with two file fields (`bank_csv`, `ledger_csv`) plus an optional `Idempotency-Key` header.

```python
# --- POST /batches response & GET /batches/{id} response ---
class BatchSummaryResponse(BaseModel):
    batch_id: str                        # uuid
    status: Literal[
        "CREATED", "INGESTING", "INGESTED",
        "RECONCILING", "COMPLETED",
        "FAILED_INGESTION", "FAILED_RECONCILIATION"
    ]
    started_at: datetime
    completed_at: datetime | None
    record_match_rate: float | None      # matched / total, 0.0–1.0
    amount_coverage: float | None        # matched paise / total paise, 0.0–1.0
    total_records: int | None
    matched_records: int | None
    exception_count: int | None

# --- GET /batches/{id}/exceptions item ---
class ExceptionListItem(BaseModel):
    result_id: str                       # uuid
    result_scope: Literal["PAYMENT", "ORPHAN_BANK_ENTRY"]
    payment_id: str | None
    settlement_utr: str | None
    bank_entry_utr: str | None
    ledger_order_id: str | None
    decision: Literal["EXCEPTION"]
    reason_code: Literal[
        "PARTIAL_SETTLEMENT", "DUPLICATE_UTR",
        "MISSING_BANK_ENTRY", "MISSING_SETTLEMENT",
        "AMOUNT_MISMATCH", "UNRESOLVED_AMBIGUOUS"
    ]
    match_method: str | None
    amounts: AmountDetail | None         # nested: expected_paise, actual_paise, difference_paise

# --- GET /batches/{id}/matches item ---
class MatchListItem(BaseModel):
    result_id: str
    result_scope: Literal["PAYMENT"]
    payment_id: str
    settlement_utr: str
    bank_entry_utr: str
    ledger_order_id: str | None
    decision: Literal["MATCH"]
    match_method: Literal[
        "EXACT_UTR", "ORDER_ID_EXACT",
        "AMOUNT_WITH_FEE_EQUATION", "LLM_ASSISTED_NARRATION"
    ]

# --- Shared nested ---
class AmountDetail(BaseModel):
    expected_paise: int
    actual_paise: int
    difference_paise: int

# --- Paginated wrapper (generic) ---
class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    total: int
    limit: int
    offset: int
```

---

## 8. Tech Stack & Storage Decisions (Phase 4)

| Component | Options considered | Choice | Why |
|---|---|---|---|
| Backend framework | FastAPI, Flask, Express | **FastAPI** | You already know it (AI CFO Platform), async support for the Razorpay API call, auto OpenAPI docs for free — useful for the panel demo. |
| Primary DB | PostgreSQL, MongoDB, SQLite | **PostgreSQL** | Relational integrity matters here — `RECONCILIATION_RESULT` has nullable FKs to Payment/Settlement/BankEntry/LedgerEntry (a null means "this side is missing," not "this side doesn't matter") and you need aggregate queries for match rate and amount coverage — this is a relational-integrity problem, not a flexible-schema one. |
| Local/demo fallback | — | **SQLite** acceptable for the panel demo if you want zero-setup — same SQLAlchemy models, swap the connection string. Don't build two schemas; just don't rely on Postgres-only features. |
| ORM | SQLAlchemy 1.x, SQLAlchemy 2.0, raw SQL | **SQLAlchemy 2.0** (mapped classes with type annotations) | New project — use the modern API. `Mapped[T]` annotations, `select()` over legacy `Query`, and native async session support. |
| Agent orchestration | LangChain/LangGraph, custom | **Custom, thin functions** | You don't need a framework for a linear pipeline (Settlement Builder → Matcher → Validator → Report Generator). A framework here would be a shallow wrapper — the deletion test fails it. |
| LLM provider | OpenAI direct, OpenRouter (GPT via proxy), Google Gemini API | **OpenRouter → GPT-4o-mini** (primary), **Google Gemini API** (fallback) | OpenRouter gives access to GPT models via a single API key and a unified OpenAI-compatible endpoint (`https://openrouter.ai/api/v1`). Gemini API key is available as a fallback if OpenRouter is slow/down during demo. Both support structured JSON output (critical for constrained extraction in the Validator). Use `openai` Python SDK pointed at OpenRouter's base URL — zero extra dependencies. |
| LLM use | — | **Only inside Validator, only for ambiguous cases** | Deterministic rules handle identity and amount-equation matching. LLM is for genuinely fuzzy narration-text extraction only — this is the "AI judgment" line judges are scoring. |
| CSV parsing | pandas, csv module | **pandas** | You'll want groupby (daily settlement grouping) and merge (staged matching) anyway; no reason to hand-roll it. |
| Migrations | Alembic, raw SQL | **Alembic** | Standard with SQLAlchemy, auto-generate migrations from model changes (`alembic revision --autogenerate`). Hand-edit only if autogenerate produces something wrong. |
| HTTP client | requests, httpx | **httpx** | Async-native, works well with FastAPI's async routes. Also enables `respx` mocking for tests (see §10.1). |

**Build vs. buy:** don't build a queue, don't build auth, don't build a custom LLM router — none of that is justified at this scope. If you want async ingestion later, a Python `BackgroundTasks` call in FastAPI is enough; a message broker would be solving a scale problem you don't have.

### 8.1 Environment Variables

Expected env vars — documented in `.env.example`:

```env
# --- Razorpay (test mode) ---
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=whsec_...
WEBHOOK_MICRO_BATCH_THRESHOLD=10
WEBHOOK_MICRO_BATCH_INTERVAL_SECONDS=300

# --- Database ---
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/reconcile
# For SQLite fallback: sqlite+aiosqlite:///./reconcile.db

# --- LLM: OpenRouter (primary) ---
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# --- LLM: Gemini (fallback) ---
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash

# --- LLM behavior ---
LLM_TIMEOUT_SECONDS=10          # hard timeout per LLM call
LLM_MAX_RETRIES=1               # retry once on transient failure, then mark UNRESOLVED_AMBIGUOUS

# --- API Security, Rate Limiting & Limits ---
API_KEY=your_secret_api_key
API_KEY_ENABLED=false           # set true to enforce X-API-Key header
RATE_LIMIT_CAPACITY=60          # Token Bucket burst capacity
RATE_LIMIT_REFILL_RATE=1.0      # Token Bucket refill rate per second
MAX_UPLOAD_SIZE_BYTES=104857600 # 100 MB max CSV upload
QA_MAX_QUESTION_LENGTH=4000     # max chars for natural language QA inquiry
CORS_ALLOWED_ORIGINS=*          # comma-separated allowed origins or *

# --- Redis Rate Limiting (Provider-Agnostic) ---
# Option 1: Any Redis provider (AWS ElastiCache, Redis Cloud, Docker, Azure, Dragonfly)
REDIS_URL=redis://default:password@localhost:6379/0
# Option 2: Upstash Redis REST API (HTTP / Serverless)
UPSTASH_REDIS_REST_URL=https://...upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

---

## 9. Project Structure

```
reconcile-agent/
├── app/
│   ├── main.py                     # FastAPI app, middlewares & global handlers
│   ├── api/
│   │   └── routes/
│   │       ├── batches.py          # Batch trigger, status, exceptions, matches, retry
│   │       ├── qa.py               # Natural language QA with prompt injection defense
│   │       ├── webhooks.py         # Razorpay webhook ingestion & HMAC verification
│   │       └── health.py           # Health, uptime, version & component checks
│   ├── core/
│   │   ├── config.py               # Pydantic Settings (env vars & security limits)
│   │   ├── security.py             # Token Bucket limiter (Upstash/Memory), API Key auth, middlewares
│   │   └── razorpay_client.py      # Async HTTP client over Payments API with retry
│   ├── agents/
│   │   ├── settlement_builder.py   # Groups payments into synthetic settlements (§3)
│   │   ├── matcher.py              # Staged deterministic match (identity → amount equation)
│   │   ├── validator.py            # Reason-code classification & candidate verification
│   │   ├── llm_classifier.py       # Bounded LLM narration extraction (GPT/Gemini)
│   │   ├── webhook_processor.py    # Idempotent webhook processing & micro-batch triggers
│   │   ├── qa_agent.py             # Grounded RAG assistant with delimiter defense
│   │   └── reporter.py             # Dual metrics (record match rate + amount coverage)
│   ├── models/                     # SQLAlchemy 2.0 ORM models (Batch, Payment, Settlement, etc.)
│   ├── schemas/                    # Pydantic v2 schemas (Batch, Responses, Health, APIMetadata)
│   ├── repositories/               # Async repository layer
│   ├── db/
│   │   ├── database.py             # Engine, Base & session factory
│   │   └── migrations/             # Alembic migration scripts
│   └── tests/                      # 94 automated test suites (100% pass rate)
│       ├── test_adversarial.py     # 26 adversarial edge cases & financial invariants
│       ├── test_qa_api.py          # 13 QA tests: validation, auth, prompt injection
│       ├── test_batches_security.py# 10 batch tests: 100MB uploads, auth, pagination
│       ├── test_health_api.py      # 6 health & CORS tests
│       ├── test_webhook_security.py# 6 webhook tests: HMAC, stats auth, rate limit
│       ├── test_batch_e2e.py       # E2E pipeline & retry tests
│       └── test_*.py               # Ingestion, Matcher, Validator, Webhook unit tests
├── data/
│   ├── synthetic_bank_statement.csv
│   └── synthetic_ledger.csv
├── static/
│   └── index.html                  # Interactive single-page demo dashboard
├── requirements.txt
├── .env.example
├── README.md
├── security_best_practices_report.md
└── ARCHITECTURE.md                 # this doc
```

---

## 10. Testing Plan

Keep this proportionate — no need for a full test pyramid on a buildathon build, but the track's judging bar explicitly rewards *measured, honest* accuracy, so testing the matcher is not optional.

| Layer | What to test | How |
|---|---|---|
| **Matcher (unit)** | Identity match, amount-equation match, correct no-match | Seed a small synthetic dataset with **known ground truth** (you decide in advance which records should match and which shouldn't) — assert the matcher gets them right. This is what lets you honestly report a match rate. |
| **Validator (unit)** | Correct reason_code assigned per failure type | One test case per reason code (duplicate UTR, missing bank entry, fee mismatch, etc.) |
| **Ingestion (integration)** | Razorpay test-mode API call succeeds, malformed CSV row doesn't crash the batch | Hit real test-mode API once in CI/local, mock for repeated runs |
| **End-to-end** | Full batch of 50+ synthetic records → match rate + exception list produced | Run against your seeded dataset, assert match_rate matches your known ground truth within expected tolerance |
| **LLM classifier (spot-check)** | Doesn't get called on cases the deterministic rules already resolved | Assert call count — this proves your "AI judgment" claim in the pitch, not just states it |

**Metric definition (fix from review — this matters):** report *two* numbers, not one — `record_match_rate` (matched records ÷ total records) and `amount_coverage`. Define the denominator explicitly, since the system now operates at multiple grains and it's easy to accidentally mix them: **`amount_coverage = Σ(Payment.amount_paise for successfully reconciled payments) ÷ Σ(Payment.amount_paise for all payments in the batch)`** — anchored on Payment gross amount specifically, not Settlement net or Ledger expected amount. Pick one and state it in the pitch; don't let "coverage" mean three different things across a demo.

These two numbers diverge in realistic cases — e.g. matching 47 of 50 small payments but missing one large one gives a misleadingly high record rate and a much lower amount coverage. Both belong in the Reporter's output; report both, don't pick the flattering one.

**Synthetic dataset — build it with deliberate failure categories, not randomly.** A realistic 50-record batch for the demo:
- ~35 exact matches
- ~5 rounding-band cases (₹1–2 off, classified `ROUNDING_MATCH`)
- ~3 partial settlements
- ~2 duplicate UTRs
- ~2 missing bank entries
- ~2 missing settlements
- ~1 genuine amount mismatch

Knowing the failure mix in advance is what makes the exception list, when it comes out the other end, checkable against ground truth instead of just plausible-looking.

**For the pitch:** show the ground-truth dataset alongside the actual output, and make sure the number you say matches the composition you actually built — with the mix above (35 exact + 5 rounding = 40 expected matches, 10 expected exceptions across 5 categories), the honest version is something like "we know 40 of these 50 should match, the system found 39, here's the one it missed — a rounding case it misclassified as `AMOUNT_MISMATCH` — and here's what that costs in amount coverage." That's a far stronger demo than a clean 100% run, and it only works if the number in your mouth actually matches the dataset on disk.

### 10.1 Mocking Strategy (pinned before implementation)

External dependencies need deterministic mocking so tests aren't flaky or slow. Strategy per dependency:

| Dependency | Unit tests | Integration / E2E tests | One-off manual validation |
|---|---|---|---|
| **Razorpay Payments API** | `respx` (mock `httpx` transport) — return fixture JSON from `tests/fixtures/razorpay_payments.json`. Deterministic, no network. | Same `respx` fixtures, loaded at test-session scope via `conftest.py`. | Real test-mode API call — run manually, not in CI. Capture the response as a new fixture if the shape changes. |
| **LLM (OpenRouter / Gemini)** | `respx` or `unittest.mock.patch` on the `openai.ChatCompletion.create` call — return a canned structured-JSON response. Assert the extraction output, not the LLM internals. | Same mock. The LLM is only called on residual cases (~1–3 records in the synthetic batch), so mock overhead is negligible. | Real LLM call — run manually to verify prompt quality and structured output parsing. Log the result for review. |
| **PostgreSQL** | In-memory SQLite via the same SQLAlchemy 2.0 models (swap `DATABASE_URL` in test config). Acceptable because the schema avoids Postgres-only features (§8). | Same SQLite, or a test Postgres container if available. | N/A — the ORM is the abstraction layer. |

**Fixture management:** store all fixture JSON files under `tests/fixtures/`. Name them descriptively (`razorpay_payments_50_mixed.json`, `llm_narration_extraction_response.json`). These fixtures are part of the ground-truth dataset — they should match the synthetic batch composition described above.

**Key rule:** never let a test depend on a live external call by default. Use an env flag (`USE_LIVE_API=1`) to opt-in to real calls for manual validation only.

---

## 11. Risk & Failure Modes (Phase 7)

| Failure mode | Likelihood × Impact | Detection | Mitigation |
|---|---|---|---|
| Razorpay test-mode API rate-limited or down mid-demo | Low × High (kills the live demo) | API error response | Cache last successful pull locally; demo can fall back to cached data if live call fails |
| CSV has a malformed row | Medium × Low | Row-level parse exception | Skip + log row-level exception, don't crash the batch |
| Amount equation misses a real adjustment type (e.g. a refund netted into the same settlement) | Medium × High (undermines "honest metrics" claim) | Ground-truth test set catches this | Encode known adjustment types explicitly in the equation; anything genuinely unaccounted-for surfaces as `AMOUNT_MISMATCH`, not a silently-passed match |
| Settlement grouping rule (§3) doesn't reflect how a real settlement would actually batch payments | Medium × Medium | Would only surface against real live-mode data, which this build never sees | State the daily-grouping assumption explicitly in the pitch as a simulation boundary, not a claim it mirrors Razorpay's actual T+2 cycle for your account — don't let a judge think it came from the API |
| LLM classifier called on a case a rule should've caught | Low × Medium | Call-count assertion in tests | Rule-based check always runs first; LLM only on the residual |
| Double-counting a Payment within one batch's reconciliation | Low × High (breaks match rate math) | DB constraint | `UNIQUE(batch_id, payment_id)` on `SETTLEMENT_LINE` — composite, not a bare `UNIQUE(payment_id)`, since the same payment can validly appear in a different batch later (§4) |
| Server/process crash mid-batch | Low × Medium (buildathon scope, single run) | Batch stuck at a non-terminal status | `BATCH.status` state machine (§6) — a stuck status is visible and re-runnable, never silently reported complete |
| Bank narration text reaches the LLM as untrusted input | Low × Medium | N/A — structural | LLM only ever returns constrained JSON extraction, never a match decision (§5.1); a hostile narration string can produce a bad *candidate*, never a bad *write* |
| LLM provider (OpenRouter / Gemini) down or slow during batch | Low × Medium (only affects residual cases, not core matching) | `LLM_TIMEOUT_SECONDS` exceeded, or HTTP 5xx from provider | Timeout after 10s (§8.1) → retry once → on persistent failure, mark those specific records as `UNRESOLVED_AMBIGUOUS` and continue the batch. The core deterministic pipeline is unaffected — this is the "if I removed the LLM, does the core system still work?" guarantee from §5.1 |

**Minimal observability:** log `batch_id`, `match_rate`, `amount_coverage`, `exception_count` per batch — this log *is* your audit trail for the "explainable" judging criterion, at basically zero extra build cost. For LLM calls specifically, log structured fields (`record_id`, `model`, `latency`, the extracted candidate, the Validator's resulting decision) rather than the raw narration text unfiltered — truncate or redact the free-text input itself. Costs nothing extra to build and avoids turning your logs into an unstructured second copy of the data.

**Data retention:** old batches and their results are kept indefinitely in the database — no TTL, no cleanup, no archival needed at this scope. If the DB grows large enough to matter (it won't at 50–500 records/batch), a simple `DELETE FROM batch WHERE completed_at < X` is sufficient. This is a deliberate non-investment, not an oversight.

---

## 12. Stretch Features — Implementation Guide

These are stretch layers, not core scope. Don't start any of these until §4–§11 above actually runs end-to-end on your seeded batch. Each subsection below documents the architecture, data flow, file placement, and build steps for the feature — enough to implement it or explain it to a judge.

**Status key:** ✅ = implemented and tested, 🔲 = documented here for future build.

---

### 12.1 Settlement Q&A Layer (`POST /qa`) — ✅ Implemented

**What it does:** A thin RAG endpoint that lets a panelist ask a natural language question about a reconciled batch (e.g. "why didn't payment X match?") and get an answer grounded in the actual exception `reason_code`, fee equations, and settlement data stored in the database — not a hallucinated general explanation.

**Why it matters for the pitch:** The judging rubric scores "explainability." Being able to type a question during the live demo and get a traced answer is a much stronger signal than pointing at JSON fields.

#### Architecture

The Q&A layer plugs into the existing Service layer (§5) as one new agent + one new route. It does **not** touch the core reconciliation pipeline — it's a read-only consumer of `RECONCILIATION_RESULT` rows.

```mermaid
flowchart LR
    subgraph API["API Layer"]
        QA_ROUTE["POST /api/v1/qa"]
    end
    subgraph SVC["Service Layer"]
        QA_AGENT["SettlementQAAgent"]
    end
    subgraph DATA["Storage (read-only)"]
        DB[("PostgreSQL / SQLite")]
    end
    subgraph LLM["LLM Providers"]
        OR["OpenRouter GPT-4o-mini"]
        GEM["Gemini 2.0 Flash"]
    end

    QA_ROUTE --> QA_AGENT
    QA_AGENT -->|"1. Query batch results,<br/>exceptions, settlements"| DB
    QA_AGENT -->|"2. Build grounded prompt<br/>with DB context"| OR
    OR -.->|"fallback"| GEM
    QA_AGENT -->|"3. Return traced answer"| QA_ROUTE
```

#### Data flow

1. **User posts** `{ "question": "Why did pay_ABC not match?", "batch_id": "uuid" }` to `POST /api/v1/qa`.
2. **QA Agent queries DB**: fetches `Batch` status, all `ReconciliationResult` rows for that batch (or recent results if no `batch_id`), and aggregates match/exception counts.
3. **Context assembly**: Builds a structured text block with:
   - Batch status, total records, match count, exception count.
   - Up to 15 exception details: `payment_id`, `reason_code`, `result_scope`, `match_method`.
4. **LLM synthesis**: Sends context + user question to OpenRouter GPT-4o-mini (primary) or Gemini (fallback) with a system prompt constraining the answer to the provided context only.
5. **Deterministic fallback**: If neither LLM key is configured, returns the raw context summary directly — no LLM needed, the structured data is already the answer.

#### Files

| File | Purpose |
|---|---|
| `app/agents/qa_agent.py` | `SettlementQAAgent` class — DB context retrieval + LLM prompt construction + fallback logic |
| `app/api/routes/qa.py` | FastAPI route: `POST /api/v1/qa` — request validation, dependency injection, response model |
| `app/main.py` | Router registration: `app.include_router(qa.router, prefix="/api/v1")` |

#### Request / Response contract

```python
# Request
class QARequest(BaseModel):
    question: str          # "Why did payment X fail?"
    batch_id: uuid.UUID | None = None   # optional — grounds the query to a specific batch

# Response
class QAResponse(BaseModel):
    question: str
    answer: str            # LLM-synthesized or deterministic context summary
    batch_id: str | None
    note: str | None       # present only in deterministic-fallback mode
```

#### Key design decisions

- **No vector store / embedding index**: At 50–500 records per batch, the entire result set fits in a single LLM context window. A vector DB would be over-engineering — the "RAG" here is just "query the relational DB, format the results as prompt context." State this to judges if asked.
- **LLM is synthesis-only, not authority**: The Q&A agent never writes to the database. It reads `reason_code` values that the Validator already assigned deterministically (§5.1 boundary still holds).
- **Graceful degradation**: Works without any LLM keys — returns the structured DB context directly. This means the Q&A endpoint is functional even in offline/demo mode.

---

### 12.2 Match Method Transparency — ✅ Implemented

**What it does:** Surfaces the `match_method` field (`EXACT_UTR`, `ORDER_ID_EXACT`, `AMOUNT_WITH_FEE_EQUATION`, `LLM_ASSISTED_NARRATION`) directly in every API response — both match lists and exception lists — so a panelist can see *how* each record was resolved, not just that it was.

**Why it matters for the pitch:** "This payment was matched via exact UTR lookup" vs. "this one required LLM-assisted narration extraction" is the entire "AI judgment" story. Hiding it behind a DB column no one sees wastes the best demo signal you have.

#### How it works (zero new infrastructure)

The field already exists in the `RECONCILIATION_RESULT` model (§4). The implementation is purely about **not dropping it** at the schema boundary:

```mermaid
flowchart LR
    DB["RECONCILIATION_RESULT.match_method"] --> REPO["ReconciliationResultRepo"] --> SCHEMA["MatchListItem / ExceptionListItem<br/>(Pydantic response model)"] --> API["JSON response to client"]
```

#### Where it appears

| API Endpoint | Response field | Values |
|---|---|---|
| `GET /batches/{id}/matches` | `match_method` on each `MatchListItem` | `EXACT_UTR`, `ORDER_ID_EXACT`, `AMOUNT_WITH_FEE_EQUATION`, `LLM_ASSISTED_NARRATION` |
| `GET /batches/{id}/exceptions` | `match_method` on each `ExceptionListItem` | Same enum (nullable — may be `null` for orphan bank entries that never entered matching) |
| `POST /batches` / `GET /batches/{id}` | `match_method_breakdown` on `BatchSummaryResponse` | Aggregate count dict: `{ "EXACT_UTR": 37, "AMOUNT_WITH_FEE_EQUATION": 5, ... }` |

#### Files modified (from baseline §7.3 schemas)

| File | Change |
|---|---|
| `app/schemas/batch.py` | `match_method` field included in `MatchListItem` and `ExceptionListItem`; `match_method_breakdown: dict` added to `BatchSummaryResponse` |
| `app/agents/reporter.py` | Computes `match_method_breakdown` by grouping `MATCH` results by `match_method` |
| `app/api/routes/batches.py` | Passes `match_method` through from repo → schema — no transformation needed |

#### Key design decision

- **No `resolution_method` rename**: The second architecture review suggested renaming `match_method` to `resolution_method` but called it optional. Keeping `match_method` — it's what the model, schema, and tests already use, and renaming for aesthetics mid-buildathon isn't worth the churn.

---

### 12.3 Simple Exception Dashboard — ✅ Implemented

**What it does:** A single-page HTML dashboard (no framework, no build step) that renders the batch summary, metric cards, reason-code badges, match-method badges, and tabbed exception/match tables — for the live demo.

**Why it matters for the pitch:** Panelists should see the reconciliation results visually during the demo, not read raw JSON from Swagger or a terminal. This is the difference between "it works" and "you can see it working."

#### Architecture

```mermaid
flowchart LR
    subgraph Browser["Browser (no framework)"]
        HTML["static/index.html<br/>Tailwind CSS via CDN"]
    end
    subgraph Server["FastAPI"]
        STATIC["StaticFiles mount at /static"]
        DATA_MOUNT["StaticFiles mount at /data"]
        API["REST API at /api/v1/*"]
        QA_API["POST /api/v1/qa"]
    end

    HTML -->|"fetch() calls"| API
    HTML -->|"Q&A queries"| QA_API
    HTML -->|"load synthetic CSVs"| DATA_MOUNT
    Server -->|"GET / serves"| HTML
```

#### Features

| Feature | Implementation |
|---|---|
| **One-click seeded demo** | "Run Seeded 50-Record Batch" button fetches `synthetic_bank_statement.csv` and `synthetic_ledger.csv` from `/data/` mount, posts them to `POST /api/v1/batches` |
| **Custom file upload** | Drag-and-drop file inputs for bank CSV + ledger CSV, posted as `multipart/form-data` |
| **Metric cards** | Record Match Rate (%), Amount Coverage (%), Exception Count, Batch Status — live-updated from `BatchSummaryResponse` |
| **Reason code breakdown** | Color-coded badges: `PARTIAL_SETTLEMENT: 3`, `DUPLICATE_UTR: 2`, etc. |
| **Match method breakdown** | Color-coded badges: `EXACT_UTR: 37`, `AMOUNT_WITH_FEE_EQUATION: 5`, etc. |
| **Tabbed results tables** | Exceptions tab (with reason codes) and Matches tab (with match methods), paginated via API |
| **Settlement Q&A chat** | Text input + "Ask Assistant" button → `POST /api/v1/qa` → answer displayed inline |

#### Files

| File | Purpose |
|---|---|
| `static/index.html` | Complete self-contained dashboard — HTML + Tailwind CSS (CDN) + vanilla JS |
| `app/main.py` | Mounts `static/` and `data/` directories, serves `index.html` at `GET /` |

#### Key design decisions

- **No React/Vue/Svelte**: A single HTML file with inline `<script>` is the right tool for a buildathon demo dashboard. No build step, no node_modules, no bundler — it just works when you start the server.
- **Tailwind via CDN**: `<script src="https://cdn.tailwindcss.com">` — not a production pattern, but perfect for a demo. No PostCSS config, no purge setup.
- **Progressive disclosure**: Metrics section is hidden until a batch completes, then reveals with live data. Q&A section is always visible but only produces results after a batch exists.

---

### 12.4 Webhook-Based Near-Real-Time Mode — ✅ Implemented

**What it does:** Instead of pulling Payments from Razorpay's API on a schedule (the current batch model), listen to Razorpay's `payment.captured` webhook and reconcile incrementally as payments arrive.

**Why it changes things:** This shifts the ingestion trigger from **pull** (you decide when to fetch) to **push** (Razorpay tells you when something happened). It's a fundamentally different failure mode — webhook delivery guarantees, signature verification, idempotent event processing — so don't attempt this until the batch/pull version is solid.

#### Architecture (proposed)

```mermaid
flowchart TB
    subgraph Razorpay["Razorpay Platform"]
        WH["Webhook Dispatcher<br/>(payment.captured event)"]
    end

    subgraph API["API Layer (FastAPI)"]
        WH_ROUTE["POST /api/v1/webhooks/razorpay"]
        BATCH_ROUTES["Existing batch routes (unchanged)"]
    end

    subgraph SVC["Service Layer"]
        SIG_VERIFY["Signature Verifier<br/>(HMAC-SHA256)"]
        EVENT_PROC["Event Processor<br/>(idempotent upsert)"]
        MICRO_BATCH["Micro-Batch Trigger<br/>(threshold or timer)"]
        EXISTING["Existing pipeline:<br/>Settlement Builder → Matcher<br/>→ Validator → Reporter"]
    end

    subgraph DATA["Storage"]
        EVT_LOG[("webhook_event log table")]
        DB[("Existing tables")]
    end

    WH -->|"POST with X-Razorpay-Signature"| WH_ROUTE
    WH_ROUTE --> SIG_VERIFY
    SIG_VERIFY -->|"valid"| EVENT_PROC
    SIG_VERIFY -->|"invalid → 401"| WH_ROUTE
    EVENT_PROC -->|"upsert Payment"| DB
    EVENT_PROC -->|"log event"| EVT_LOG
    EVENT_PROC --> MICRO_BATCH
    MICRO_BATCH -->|"threshold reached<br/>or timer elapsed"| EXISTING
    EXISTING --> DB
```

#### Data flow (step by step)

1. **Razorpay sends webhook**: `POST /api/v1/webhooks/razorpay` with JSON body containing `event: "payment.captured"` and header `X-Razorpay-Signature`.
2. **Signature verification**: Compute `HMAC-SHA256(request_body, RAZORPAY_WEBHOOK_SECRET)` and compare to the signature header. Reject with `401 Unauthorized` if mismatch. This prevents forged webhook calls from manipulating financial state.
3. **Idempotent event processing**: Extract the `payment.entity` from the webhook payload. Upsert the Payment into the DB using `payment.id` as the natural key. Log the raw webhook event to a `webhook_event` audit table with `event_id` (Razorpay provides this) as a dedup key.
4. **Micro-batch trigger**: Two strategies (configurable):
   - **Threshold-based**: After N new payments accumulate (e.g. 10), trigger a reconciliation run against available bank/ledger data.
   - **Timer-based**: Every M minutes, if any unreconciled payments exist, trigger a run.
5. **Reconciliation**: The existing pipeline (Settlement Builder → Matcher → Validator → Reporter) runs unchanged — it doesn't care whether its input came from a pull or a push.

#### New files required

| File | Purpose |
|---|---|
| `app/api/routes/webhooks.py` | `POST /api/v1/webhooks/razorpay` — signature verification, event parsing, response |
| `app/agents/webhook_processor.py` | Event processing: Payment upsert, dedup, micro-batch trigger logic |
| `app/models/webhook_event.py` | `WEBHOOK_EVENT` table: `id`, `razorpay_event_id` (unique), `event_type`, `payload_json`, `processed_at`, `status` |
| `app/core/config.py` | New env vars: `RAZORPAY_WEBHOOK_SECRET`, `WEBHOOK_MICRO_BATCH_THRESHOLD`, `WEBHOOK_MICRO_BATCH_INTERVAL_SECONDS` |

#### New environment variables

```env
# --- Webhook mode (§12.4) ---
RAZORPAY_WEBHOOK_SECRET=whsec_...       # from Razorpay Dashboard → Webhooks → Secret
WEBHOOK_MICRO_BATCH_THRESHOLD=10        # trigger reconciliation after N new payments
WEBHOOK_MICRO_BATCH_INTERVAL_SECONDS=300  # or every 5 minutes, whichever comes first
```

#### Signature verification (implementation detail)

Razorpay signs webhooks with HMAC-SHA256 using your webhook secret. The verification is straightforward:

```python
import hashlib
import hmac

def verify_razorpay_webhook_signature(
    request_body: bytes,
    signature_header: str,
    webhook_secret: str,
) -> bool:
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        request_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

**Critical**: Use `hmac.compare_digest` (constant-time comparison), not `==`. Timing attacks on signature verification are a real vulnerability class, not a theoretical one.

#### New DB model

```python
class WebhookEvent(Base):
    __tablename__ = "webhook_event"

    id: Mapped[uuid.UUID]               # PK
    razorpay_event_id: Mapped[str]      # UNIQUE — Razorpay's own event ID, for dedup
    event_type: Mapped[str]             # "payment.captured", "payment.failed", etc.
    payload_json: Mapped[str]           # raw JSON body, stored for audit
    processed_at: Mapped[datetime]
    status: Mapped[str]                 # "PROCESSED", "SKIPPED_DUPLICATE", "FAILED"
```

#### Failure modes unique to webhook mode

| Failure mode | Detection | Mitigation |
|---|---|---|
| **Razorpay retries a webhook** (they retry up to 24h on non-2xx response) | `razorpay_event_id` unique constraint catches the duplicate | Upsert with `ON CONFLICT DO NOTHING`; return `200 OK` immediately (Razorpay stops retrying on 2xx) |
| **Webhook secret compromised** | N/A — structural | Rotate the secret in Razorpay Dashboard + `.env`; all old signatures immediately fail verification |
| **Micro-batch runs against stale bank/ledger data** | Batch will produce `MISSING_BANK_ENTRY` exceptions for payments that arrived via webhook but haven't been matched to a bank statement yet | This is correct behavior — the exception surfaces the real state. Upload fresh bank CSV to clear them |
| **Webhook endpoint is down** | Razorpay's retry queue will hold events for up to 24h | On recovery, events arrive in burst — the idempotent upsert and micro-batch threshold handle this gracefully |
| **Event arrives out of order** (e.g. `payment.captured` before `order.paid`) | Only `payment.captured` is processed; other events are logged but not acted on | Filtering by event type at the processor level |

#### When to build this

**Not until** the batch/pull pipeline passes all 19 tests and produces correct results on the seeded dataset. The webhook mode reuses the entire existing pipeline — it only changes *how* payments enter the system, not how they're reconciled. If the batch mode doesn't work, the webhook mode won't either, and you'll have two broken things instead of one.

#### Demo tip

For a live demo with webhooks, you need a publicly reachable URL. Options:
- **ngrok**: `ngrok http 8000` → gives you a public HTTPS URL to register in Razorpay Dashboard → Webhooks.
- **Razorpay Dashboard test webhook**: Use the "Send Test Webhook" button in the Razorpay Dashboard to trigger a `payment.captured` event against your local endpoint.

Register `https://your-ngrok-url/api/v1/webhooks/razorpay` in the Razorpay Dashboard with the `payment.captured` event selected.

---

## 13. Build Order (what to tackle first)

1. **Domain model + DB schema + migrations** — get PostgreSQL tables real before writing any matching logic.
2. **Synthetic dataset with known ground truth** — write this before the matcher, not after. You need it to know if the matcher is actually working. Build the synthetic bank CSV's UTRs to match the daily-grouping rule from §3, or the settlement builder and the bank data won't line up.
3. **Ingestion**: Razorpay Payments API pull + CSV loaders.
4. **Settlement Builder** — group payments per §3's grouping rule before any matching runs against them.
5. **Matcher** (staged: identity → amount equation, per §14) — test against ground truth.
6. **Validator** (rule-based reason codes) — LLM classifier only after the rule-based path is solid.
7. **Report Generator** + API routes to expose match rate/exceptions.
8. **Tests** (can interleave with 5–7, not bolted on at the end).
9. Only then: stretch items from §12, in the order listed.

This order front-loads the part that's actually being judged (measured accuracy on a real batch) and pushes the demo-polish items to the end, where they belong.

---

## 14. Matcher staging (kept intentionally lean)

**Responsibility split:** the Matcher proposes candidates by identifier or arithmetic; the Validator is what actually decides whether a candidate is financially valid and, if not, why. Keeping that split explicit is what makes the "if I removed the LLM, does the core still work" answer clean — the LLM only ever adds a candidate for the Validator to judge, same as the deterministic stages do.

The Matcher runs in three stages, in order, stopping at the first one that resolves a record:

1. **Identity match** — `Payment.order_id ↔ LedgerEntry.order_id`, and `Settlement.utr ↔ BankEntry.utr`. Deterministic, exact.
2. **Amount match, classified** — not a single pass/fail check. Compute `expected = Settlement.gross − Settlement.fee − Settlement.tax + Settlement.adjustment_paise` (adjustment defaulted to 0 for this build — see §4), compare to `BankEntry.amount`, and classify the difference against a documented policy rather than a blind threshold:
   - `difference == 0` → `EXACT_MATCH`
   - `difference` within a stated rounding allowance (document the number, e.g. ≤ ₹1) → `ROUNDING_MATCH`
   - `difference > 0` beyond that allowance, but not the full expected amount → `PARTIAL_SETTLEMENT` (money did arrive, just less than expected — after fees/tax/adjustments are already accounted for, so a real shortfall, not a mislabeled fee deduction)
   - `difference` unexplained by any known adjustment type → `AMOUNT_MISMATCH`

   This preserves the "AI judgment" story from the original design (a documented accounting rule, not a fuzzy matcher) while still handling the rounding case the original problem statement explicitly called out.
3. **LLM-assisted residual** — only for the records stage 1–2 couldn't resolve (e.g. bank narration is the only signal left). Bounded per §5.1: extraction only, never a direct write.

This is a deliberately compressed version of the finer-grained staging an external review of this doc proposed (it suggested 8 named levels). Three stages, with one of them classified into sub-bands, cover every case this project actually needs to handle at 50–500 records; more stages would be organizing complexity you don't have yet, not removing risk.

---

## 15. Note: changes made after external review

**First review pass:** the Payment↔BankEntry grain (confirmed against Razorpay's actual settlement API payloads — one settlement aggregates multiple payments into one UTR) and the Exception table requiring a match that might not exist were both genuinely wrong and are fixed above. Medium fixes folded in: the two-number match-rate metric, a hard LLM authority boundary, idempotency key storage, and an explicit batch state machine.

**Second review pass:** caught a real remaining ambiguity (the `RECONCILIATION_RESULT` grain wasn't formally tagged — fixed with `result_scope`) and a factual error worth flagging plainly — I'd claimed Razorpay's default settlement cycle is T+1; verified against current docs, the actual standard is **T+2 working days**, corrected in §3. Also adopted: classified amount-match bands (rounding vs. partial vs. mismatch, restoring the tolerance handling the original problem statement called for), SettlementLine allocation invariants, a defined `amount_coverage` denominator, pagination handling for the Payments API, a single `matcher_version` field, structured (not raw) LLM logging, and an explicit retry rule for stuck batches.

**Not adopted, either pass:** CAP-theorem analysis (no distributed component exists in a single-process, single-Postgres build), an 8-level matching hierarchy, per-field audit-trail versioning beyond the one `matcher_version` string, and renaming `match_method` to `resolution_method`.

---

## 16. Production API Security, Rate Limiting & Hardening Architecture

In addition to core three-way matching, the service incorporates production security controls and enterprise API safeguards:

### 16.1 Security Controls Matrix

| Domain | Mechanism | Specification |
|---|---|---|
| **API Authentication** | Header-based API Key | Validates `X-API-Key` via `verify_api_key` dependency. Gated behind `API_KEY_ENABLED=true` so demo dashboards work out-of-the-box. |
| **Distributed Rate Limiting** | Token Bucket Algorithm | Continuous token refill with burst capacity. Native support for **any standard Redis provider** via `REDIS_URL` (AWS ElastiCache, Redis Cloud, Docker, Azure, Dragonfly) and **Upstash Redis REST API** via atomic Lua script execution with seamless local in-memory fallback. |
| **Webhook Integrity** | Constant-Time HMAC-SHA256 | Validates `X-Razorpay-Signature` with `hmac.compare_digest`. Fails closed with `HTTP 503` if webhook secret is unset. |
| **Input Validation** | File & Length Bounds | CSV file uploads validated up to 100MB (`MAX_UPLOAD_SIZE_BYTES`). QA natural language prompts capped at 4,000 chars with HTML escaping (`html.escape`). |
| **Prompt Injection Defense** | XML Delimiter Isolation | Binds database facts inside `<reconciliation_context>` and user questions in `<user_question>`, strictly disallowing override instructions. |
| **Observability & Tracing** | Standardized Metadata | Injects and propagates `X-Request-ID` across middleware. Attaches `APIMetadata` (`request_id`, `timestamp`, `version`, `duration_ms`) to all responses. |
| **CORS Policy** | Origin Allowlisting | Dynamic allowlisting via `CORS_ALLOWED_ORIGINS` (defaults to `*` for demo). |

### 16.2 Automated Test Coverage (102 Tests, 100% Passing, 0 Skipped)

The test suite covers full unit, integration, adversarial, and security test harnesses:
- `tests/test_adversarial.py` (26 tests): Financial equation invariants, float safety, duplicate UTRs, and data quality metrics.
- `tests/test_qa_api.py` (15 tests): QA input bounds, HTML escaping, API key auth, batch grounding, Token Bucket rate limiting across generic Redis and Upstash providers, and prompt injection defense.
- `tests/test_batches_security.py` (10 tests): 100MB upload checks, invalid extensions, pagination limits ($\le 200$), and conflict handling.
- `tests/test_webhook.py` (8 tests): Near-real-time push ingestion, idempotency, and micro-batch triggers.
- `tests/test_batch_e2e.py` (8 tests): Full 3-way reconciliation pipeline and retry handling.
- `tests/test_matcher.py` (7 tests): Staged matching (identity, fee equations, residual candidates).
- `tests/test_health_api.py` (6 tests): Uptime, DB health, versioning, and CORS headers.
- `tests/test_webhook_security.py` (6 tests): HMAC-SHA256 constant-time verification, stats auth, JSON parsing errors, and rate limits.
- `tests/test_ingestion.py` (4 tests): Razorpay API pull and CSV parsers.
- `tests/test_validator.py` (4 tests): Reason-code classification and bounded LLM extraction.
- `tests/test_qa_complex.py` (1 test with 7 domain questions): Deep analytical questions (Root Cause, Business Impact, Remediation).
- `tests/test_qa_rag.py` (2 tests): General and batch-specific RAG grounding.
- `tests/test_qa_simple.py` (1 test): Health and basic query verification.
- `tests/test_connections.py` (2 tests): Razorpay and LLM client connection tests.
- `tests/test_settlement_builder.py` (2 tests): Daily settlement grouping and arithmetic invariants.
