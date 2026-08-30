# Setup Guide: Razorpay Test Account & Database

## Quick Start: 3 Steps to Run

### Step 1: Get Razorpay Test Credentials

1. Go to **[Razorpay Dashboard](https://dashboard.razorpay.com/)**
2. Sign up or log in (use test mode - it's free)
3. Go to **Settings → API Keys** (left sidebar)
4. Click **"Generate Test Key"**
5. Copy both:
   - **Key ID**: `rzp_test_XXXXXXXXXXXXXXXX`
   - **Key Secret**: `YYYYYYYYYYYYYYYY`

**Note**: Keep the Key Secret safe! You'll need it in Step 2.

---

### Step 2: Configure Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Copy the example file
cp .env.example .env
```

**Edit `.env` and add your credentials:**

```env
# === REQUIRED: Razorpay Test Credentials ===
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY_HERE
RAZORPAY_KEY_SECRET=YOUR_SECRET_HERE

# === Database (Choose ONE option below) ===

# OPTION A: SQLite (Simplest - No installation needed)
DATABASE_URL=sqlite+aiosqlite:///./reconcile.db

# OPTION B: PostgreSQL (Production-ready)
# DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/reconcile

# === LLM API Keys (Choose at least ONE) ===

# OpenRouter (Recommended - supports multiple models)
OPENROUTER_API_KEY=sk-or-v1-YOUR_KEY_HERE
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# OR Gemini (Google AI)
# GEMINI_API_KEY=AIzaYOUR_KEY_HERE
# GEMINI_MODEL=gemini-2.0-flash

# === Optional: Webhook Settings ===
# RAZORPAY_WEBHOOK_SECRET=whsec_...
# WEBHOOK_MICRO_BATCH_THRESHOLD=10
# WEBHOOK_MICRO_BATCH_INTERVAL_SECONDS=300
```

---

### Step 3: Run the Application

#### Option A: SQLite (Default - Simplest)

**Advantages:**
- ✅ No installation required
- ✅ File-based database (portable)
- ✅ Perfect for development/testing
- ✅ Works out of the box

**Run:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Database file location**: `./reconcile.db` in project root

---

#### Option B: PostgreSQL (Production)

**Advantages:**
- ✅ Production-grade performance
- ✅ Better for concurrent users
- ✅ Advanced query capabilities
- ✅ Scalable

**Setup:**

1. **Install PostgreSQL**:
   - Windows: [Download PostgreSQL](https://www.postgresql.org/download/windows/)
   - Or use Docker: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=password postgres`

2. **Create Database**:
   ```sql
   createdb reconcile
   ```

3. **Update `.env`**:
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/reconcile
   ```

4. **Run migrations & start**:
   ```bash
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## Getting LLM API Keys (For Narration Extraction)

The system needs an LLM to extract UTRs from bank narration text. **Choose ONE**:

### Option 1: OpenRouter (Recommended)

**Why**: Access to GPT-4, Claude, and other models through one API

1. Go to [OpenRouter](https://openrouter.ai/)
2. Sign up (free credits included)
3. Get API key from dashboard
4. Add to `.env`:
   ```env
   OPENROUTER_API_KEY=sk-or-v1-YOUR_KEY_HERE
   OPENROUTER_MODEL=openai/gpt-4o-mini
   ```

**Cost**: ~$0.0001 per reconciliation (extremely cheap)

---

### Option 2: Google Gemini

**Why**: Free tier available, fast inference

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create API key
3. Add to `.env`:
   ```env
   GEMINI_API_KEY=AIzaYOUR_KEY_HERE
   GEMINI_MODEL=gemini-2.0-flash
   ```

**Cost**: Free tier available

---

## Testing the Setup

### 1. Health Check

```bash
curl http://localhost:8000/api/v1/health
```

**Expected response:**
```json
{
  "status": "ok",
  "db": "connected"
}
```

---

### 2. Run with Sample Data (No Razorpay Account Needed)

The project includes 50-record synthetic dataset for testing:

1. **Open browser**: http://localhost:8000/
2. **Click**: "Run Seeded 50-Record Batch"
3. **See results**: Reconciliation metrics, matches, exceptions

This uses pre-generated test data from `data/` folder.

---

### 3. Test with Your Razorpay Account

Once you have Razorpay credentials configured:

```bash
# Generate sample orders in your Razorpay test account
python scripts/seed_razorpay_test_account.py

# This will:
# - Create test orders via Razorpay API
# - Generate matching CSV files
# - Show you the file paths
```

Then upload the CSVs via the web UI or API.

---

## Database Schema Migrations

The project uses **Alembic** for database migrations.

### Create New Migration (After Model Changes)

If you modified models (like we just did for `duplicate_ledger_order_ids`):

```bash
# Generate migration script
alembic revision --autogenerate -m "Add data quality metrics to batch"

# Apply migration
alembic upgrade head
```

### Check Current Migration Status

```bash
alembic current
```

### Rollback Migration

```bash
# Rollback one step
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision_id>
```

---

## Project Structure

```
reconcile-agent/
├── app/
│   ├── agents/          # Business logic agents
│   ├── api/             # FastAPI routes
│   ├── models/          # SQLAlchemy ORM models
│   ├── repositories/    # Data access layer
│   ├── schemas/         # Pydantic API schemas
│   └── core/            # Razorpay client, config
├── tests/               # Test suite (26 tests)
├── data/                # Sample CSV files
├── scripts/             # Utility scripts
├── alembic/             # Database migrations
├── .env                 # Your configuration (create this!)
├── .env.example         # Template
├── reconcile.db         # SQLite database (auto-created)
└── requirements.txt     # Python dependencies
```

---

## Troubleshooting

### "Razorpay API Error"

**Problem**: Can't connect to Razorpay  
**Solution**: 
1. Check `.env` has correct `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`
2. Ensure you're using **test mode** keys (starts with `rzp_test_`)
3. Try: `curl -u rzp_test_YOUR_KEY:YOUR_SECRET https://api.razorpay.com/v1/payments`

---

### "Database Connection Error"

**SQLite**:
- File `reconcile.db` will be created automatically
- Ensure `DATABASE_URL=sqlite+aiosqlite:///./reconcile.db` in `.env`

**PostgreSQL**:
- Check PostgreSQL is running: `pg_isready`
- Verify connection string format
- Test connection: `psql postgresql://user:pass@localhost:5432/reconcile`

---

### "LLM API Error"

**Problem**: Narration extraction fails  
**Solution**:
1. Check API key is valid
2. Test OpenRouter: `curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer sk-or-v1-YOUR_KEY"`
3. Fallback: The system works without LLM (skips narration extraction)

---

### "Import Error / Module Not Found"

```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade

# If using virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

---

## Next Steps

Once running:

1. **API Documentation**: http://localhost:8000/docs
2. **Web UI**: http://localhost:8000/
3. **Run Tests**: `pytest tests/ -v`
4. **Check Logs**: Application logs show reconciliation progress

---

## Production Deployment Checklist

- [ ] Switch to PostgreSQL database
- [ ] Set `USE_FIXTURES=0` (never use synthetic data)
- [ ] Configure webhook secrets for real-time reconciliation
- [ ] Set up proper authentication (currently buildathon scope)
- [ ] Enable HTTPS
- [ ] Configure log retention
- [ ] Set up monitoring/alerting
- [ ] Review P1-P8 pinned behaviors with stakeholders

---

## Support & Documentation

- **API Docs**: http://localhost:8000/docs (interactive)
- **PRD**: `ADVERSARIAL_TEST_PRD.md` (test strategy)
- **Review**: `ADVERSARIAL_TEST_REVIEW_SUMMARY.md` (test results)
- **Tests**: `tests/` folder (26 comprehensive tests)

---

## Summary: Minimum Required

To get started, you **ONLY** need:

1. ✅ Razorpay test account (free)
2. ✅ `.env` file with credentials
3. ✅ LLM API key (OpenRouter or Gemini)
4. ✅ SQLite (built-in, no setup)

**5 minutes to first reconciliation!** 🚀
