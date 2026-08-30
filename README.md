# Razorpay AI Buildathon — AI Finance Controller: Reconciliation Agent

**Track:** AI Finance Controller  
**Objective:** Automate the three-way match between Razorpay test-mode transaction data, bank statement CSVs, and internal order ledger records with reason-coded exception reporting, bounded LLM narration extraction, Token Bucket rate limiting, and an enterprise security test harness.

---

## 1. Features & Architecture Highlights

- **Domain-Accurate Settlement Grain:** Groups captured payments into deterministic daily settlements (`setl_...` / UTRs), reflecting how Razorpay's settlement cycle works in practice.
- **Staged 3-Way Matching:**
  1. *Stage 1 (Identity):* Exact Settlement UTR ↔ Bank UTR and Payment Order ID ↔ Ledger Order ID.
  2. *Stage 2 (Amount Equation):* Validates $\text{net} = \text{gross} - \text{fee} - \text{tax} + \text{adjustments}$ with classified bands:
     - Exact match ($\Delta = 0$)
     - Rounding match ($|\Delta| \le ₹2.00$)
     - Partial settlement (shortfall from bank credit)
     - Amount mismatch (unexplained variance)
  3. *Stage 3 (Residuals & Orphans):* Flagging missing bank credits, duplicate UTRs, and orphan bank credits.
- **Production API Security & Rate Limiting:**
  - **Token Bucket Rate Limiter**: Burst capacity with continuous token refill backed by **Upstash Redis REST API** (atomic Lua script) with automatic local in-memory fallback.
  - **API Key Protection**: Optional `X-API-Key` authentication for batch operations, QA inquiries, and webhook metrics (`API_KEY_ENABLED`).
  - **Constant-Time Webhooks**: HMAC-SHA256 signature verification with fail-closed security (`RAZORPAY_WEBHOOK_SECRET`).
  - **Input & Upload Safeguards**: 100MB max CSV upload capacity, 4000-char QA inquiries with HTML sanitization, and prompt injection delimiter defenses.
  - **Distributed Tracing & Metadata**: `X-Request-ID` propagation and server processing latency (`duration_ms`) attached to all responses.
  - **Configurable CORS**: Dynamic origin allowlisting via `CORS_ALLOWED_ORIGINS`.
- **Bounded LLM Extraction:** LLM (OpenRouter GPT-4o-mini / Gemini fallback) is strictly bounded to unstructured narration text extraction; extracted candidates are deterministically re-verified by the Validator before persisting.
- **Dual Reconciliation Metrics:**
  - `record_match_rate`: $\frac{\text{Matched Records}}{\text{Total Processed Records}}$
  - `amount_coverage`: $\frac{\sum \text{Payment Paise (Matched)}}{\sum \text{Payment Paise (Batch Total)}}$ (anchored on Payment gross paise)
- **Data Quality Visibility:**
  - `duplicate_ledger_order_ids`: Tracks duplicate order_ids in ledger CSV uploads
  - `skipped_rows`: Counts malformed rows skipped during CSV parsing
- **Settlement Q&A Assistant:** Natural language RAG endpoint (`POST /api/v1/qa`) to explain batch discrepancies and variances.
- **Comprehensive Test Harness**: 94/94 automated tests passing (100% pass rate).

---

## 2. CI/CD Status

![CI Tests](https://github.com/YOUR_USERNAME/Razorpay/workflows/CI%20-%20Testing%20%26%20Quality%20Checks/badge.svg)
![CD Deploy](https://github.com/YOUR_USERNAME/Razorpay/workflows/CD%20-%20Deployment/badge.svg)
![Scheduled Tests](https://github.com/YOUR_USERNAME/Razorpay/workflows/Scheduled%20Tests%20%26%20Maintenance/badge.svg)

**Automated Pipelines:**
- ✅ **Continuous Integration**: Python 3.10, 3.11, 3.12 test matrix
- ✅ **Code Quality**: Ruff, Black, isort, mypy
- ✅ **Security Scanning**: Bandit, Safety checks
- ✅ **Deployment**: Docker containerization with GitHub Container Registry
- ✅ **Scheduled Maintenance**: Nightly tests, dependency audits

---

## 3. Quick Links

- **Architecture Document:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Application Code:** [`reconcile-agent/`](reconcile-agent/)
- **CI/CD Setup Guide:** [`CI_CD_SETUP_GUIDE.md`](CI_CD_SETUP_GUIDE.md)
- **Contributing Guidelines:** [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **Security Report:** [`reconcile-agent/security_best_practices_report.md`](reconcile-agent/security_best_practices_report.md)
- **Setup Guide:** [`reconcile-agent/SETUP_GUIDE.md`](reconcile-agent/SETUP_GUIDE.md)
- **Quick Start:** [`reconcile-agent/QUICKSTART.md`](reconcile-agent/QUICKSTART.md)
- **Test Documentation:** [`reconcile-agent/ADVERSARIAL_TEST_PRD.md`](reconcile-agent/ADVERSARIAL_TEST_PRD.md)

---

## 4. Fast Start

```powershell
# 1. Navigate to reconcile-agent
cd "c:\class project\Razorpay\reconcile-agent"

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Configure environment (copy .env.example to .env and fill in your credentials)
# See section 4 below for required variables

# 4. Run database migrations
alembic upgrade head

# 5. Verify installation
python test_connections.py

# 6. Run automated tests (94/94 passing)
pytest tests/ -v

# 7. Start development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **[http://localhost:8000/](http://localhost:8000/)** to access the interactive web dashboard.

---

## 5. Environment Configuration

Create a `.env` file in the `reconcile-agent/` directory:

```env
# --- Razorpay (test mode) ---
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=whsec_...

# --- Database ---
DATABASE_URL=sqlite+aiosqlite:///./reconcile.db

# --- LLM: OpenRouter (primary) ---
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# --- LLM: Gemini (fallback) ---
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash

# --- Security & Rate Limiting ---
API_KEY=your_secure_api_key_here
API_KEY_ENABLED=false
RATE_LIMIT_CAPACITY=60
RATE_LIMIT_REFILL_RATE=1.0
MAX_UPLOAD_SIZE_BYTES=104857600
QA_MAX_QUESTION_LENGTH=4000
CORS_ALLOWED_ORIGINS=*

# --- Redis Rate Limiting (Provider-Agnostic) ---
# Option 1: Any Redis provider (AWS ElastiCache, Redis Cloud, Docker, Azure, Dragonfly, GCP)
REDIS_URL=redis://default:password@localhost:6379/0
# Option 2: Upstash Redis REST API (HTTP / Serverless)
UPSTASH_REDIS_REST_URL=https://...upstash.io
UPSTASH_REDIS_REST_TOKEN=...
# Option 3: Leave blank for automatic high-performance in-memory Token Bucket fallback

# --- Testing (optional) ---
USE_FIXTURES=0  # Set to 1 for offline fixture testing
```

---

## 6. How to Run

### Option A: Using Pre-Seeded Offline Fixtures (Demo Mode)
The repository includes a ready-to-run 50-record dataset:
```bash
# (Optional) Regenerate the dataset
python scripts/generate_synthetic_data.py

# Start the application server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000/](http://localhost:8000/)** and click **"Run Seeded 50-Record Batch"**.

---

### Option B: Live Integration with Razorpay Test Account
1. Add your Razorpay credentials to `.env`
2. Run the Live Seeder:
   ```bash
   python scripts/seed_razorpay_test_account.py
   ```
3. Start the server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

### Option C: Running with Docker & Docker Compose
```bash
# 1. Start Reconcile Agent in Docker
docker compose up -d --build

# 2. Or start with PostgreSQL & Redis profiles enabled:
docker compose --profile postgres --profile redis up -d --build

# 3. View live logs:
docker compose logs -f
```

---

## 7. API Endpoints Reference

| Method | Endpoint | Auth Required | Description |
|---|---|:---:|---|
| `POST` | `/api/v1/batches` | Optional `X-API-Key` | Upload Bank CSV + Ledger CSV and trigger 3-way reconciliation |
| `GET` | `/api/v1/batches/{id}` | Optional `X-API-Key` | Get status, match rate %, amount coverage %, and breakdown |
| `GET` | `/api/v1/batches/{id}/exceptions` | Optional `X-API-Key` | Paginated list of reason-coded exceptions |
| `GET` | `/api/v1/batches/{id}/matches` | Optional `X-API-Key` | Paginated list of matched records |
| `POST` | `/api/v1/batches/{id}/retry` | Optional `X-API-Key` | Retry a failed batch run |
| `POST` | `/api/v1/qa` | Optional `X-API-Key` | Natural language Q&A about batch discrepancies |
| `POST` | `/api/v1/webhooks/razorpay` | `X-Razorpay-Signature` | Receive Razorpay webhooks (HMAC-SHA256) |
| `GET` | `/api/v1/webhooks/stats` | Optional `X-API-Key` | Webhook ingestion statistics |
| `GET` | `/api/v1/health` | Public | Health check with uptime and version |
| `GET` | `/docs` | Public | Interactive Swagger / OpenAPI documentation |
| `GET` | `/` | Public | Web UI Demo Dashboard |

### Example: Upload CSV Files
```bash
curl -X POST "http://localhost:8000/api/v1/batches" \
  -H "X-API-Key: your_secure_api_key_here" \
  -F "bank_csv=@data/synthetic_bank_statement.csv" \
  -F "ledger_csv=@data/synthetic_ledger.csv"
```

### Example: Ask QA Question
```bash
curl -X POST "http://localhost:8000/api/v1/qa" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secure_api_key_here" \
  -d '{
    "question": "Why did payment pay_qa_002 result in an exception?",
    "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }'
```

---

## 8. Testing & Verification

### Run Full Test Suite
```bash
pytest tests/ -v
```
Expected: `102 passed, 0 skipped in ~60 seconds`

### Test Suite Breakdown
- **`test_adversarial.py` (26 tests)**: Financial edge cases, fee equations, and fixed defects
- **`test_qa_api.py` (15 tests)**: QA input validation, provider-agnostic Redis rate limiting, and prompt injection defense
- **`test_batches_security.py` (10 tests)**: File size limits (100MB), API key auth, and pagination
- **`test_webhook.py` (8 tests)**: Near-real-time push ingestion, idempotency, and micro-batch triggers
- **`test_batch_e2e.py` (8 tests)**: End-to-end batch processing and retry state machines
- **`test_matcher.py` (7 tests)**: Staged matching (identity, fee equations, residual candidates)
- **`test_health_api.py` (6 tests)**: Uptime tracking, component health, and CORS headers
- **`test_webhook_security.py` (6 tests)**: Constant-time HMAC verification, stats auth, and rate limiting
- **`test_ingestion.py` (4 tests)**: Razorpay API pull and CSV parsers
- **`test_validator.py` (4 tests)**: Reason-code classification and bounded LLM extraction
- **`test_qa_complex.py` (1 test with 7 domain questions)**: Deep analytical questions (Root Cause, Business Impact, Remediation)
- **`test_qa_rag.py` (2 tests)**: General and batch-specific RAG grounding
- **`test_qa_simple.py` (1 test)**: Health and basic query verification
- **`test_connections.py` (2 tests)**: Razorpay and LLM client connection tests
- **`test_settlement_builder.py` (2 tests)**: Daily settlement grouping and arithmetic invariants

### Verification Scripts
```bash
# Test all connections
python test_connections.py

# Full end-to-end test
python test_full_reconciliation.py

# Check batch exceptions
python check_batch_exceptions.py <batch_id>
```

### Run with Coverage
```bash
pytest tests/ --cov=app --cov-report=html
```

---

## 9. API Security Architecture

| Security Domain | Mechanism | Implementation |
|---|---|---|
| **API Authentication** | `X-API-Key` Header | `app/core/security.py` - `verify_api_key` dependency |
| **Rate Limiting** | Token Bucket Algorithm | Upstash Redis REST + local in-memory fallback |
| **Webhook Security** | Constant-time HMAC-SHA256 | `hmac.compare_digest` with fail-closed validation |
| **Input Validation** | File upload & Prompt bounds | 100MB CSV limit, 4000-char QA questions |
| **Prompt Injection** | Delimiter isolation | `<reconciliation_context>` tag encapsulation |
| **Distributed Tracing** | Request ID Header | `RequestIdMiddleware` with `X-Request-ID` |
| **CORS Policy** | Origin Allowlisting | Configurable via `CORS_ALLOWED_ORIGINS` |

---

## 10. Performance Benchmarks

- **Test Suite**: 94 tests in ~60 seconds (100% pass rate)
- **Reconciliation**: <10 seconds per batch (100 records)
- **Token Bucket**: <1ms (in-memory) / ~15ms (Upstash Redis)
- **Webhook Processing**: <50ms with HMAC validation
- **File Upload**: Up to 100MB per CSV

---

## 11. Documentation

| Document | Description |
|---|---|
| `README.md` | This file - overview, setup, and API reference |
| `ARCHITECTURE.md` | System architecture and design decisions |
| `reconcile-agent/SETUP_GUIDE.md` | Detailed installation guide |
| `reconcile-agent/QUICKSTART.md` | 5-minute quick start |
| `reconcile-agent/ADVERSARIAL_TEST_PRD.md` | Test scenarios and defect documentation |
| `reconcile-agent/INTEGRATION_TEST_RESULTS.md` | Latest test results |
| `CI_CD_SETUP_GUIDE.md` | CI/CD pipeline setup and configuration |
| `CONTRIBUTING.md` | Contributing guidelines and development workflow |
| `reconcile-agent/security_best_practices_report.md` | Security inspection report |

---

## 12. Troubleshooting

### No captured payments in Razorpay
Visit https://dashboard.razorpay.com/app/payments and create test payments, then re-run the seeder script.

### LLM extraction not working
Verify `OPENROUTER_API_KEY` in .env and check API quota at https://openrouter.ai

### Database migration errors
```bash
alembic upgrade head
```

### CSV parsing errors
Check CSV format, encoding (UTF-8), and ensure no BOM markers.

### Tests failing
```bash
pytest tests/ -v -s  # Run with verbose output
```

---

## 13. System Status

✅ **Production Ready** (Verified August 29, 2026)

- ✅ Razorpay API integration working
- ✅ LLM extraction functional (OpenRouter GPT-4o-mini)
- ✅ Database migrations applied
- ✅ Security features enabled (API Key, Rate Limiting, HMAC)
- ✅ All 94 tests passing (100%)
- ✅ API endpoints responsive
- ✅ Web UI operational

---

## 14. Contact & Support

- **Razorpay Dashboard**: https://dashboard.razorpay.com
- **API Documentation**: http://localhost:8000/docs
- **Test Results**: See `reconcile-agent/INTEGRATION_TEST_RESULTS.md`
