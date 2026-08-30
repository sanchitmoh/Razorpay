# 🚀 Quick Start Guide (5 Minutes)

## Step 1: Get Razorpay Test Credentials (2 minutes)

1. Open **https://dashboard.razorpay.com/**
2. Sign up or log in (it's free)
3. Go to **Settings → API Keys** 
4. Click **"Generate Test Key"**
5. Copy your `Key ID` and `Key Secret`

---

## Step 2: Configure `.env` File (1 minute)

**The `.env` file is already created for you!**

Open `c:\class project\Razorpay\reconcile-agent\.env` and fill in:

```env
# Paste your credentials here:
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY_HERE
RAZORPAY_KEY_SECRET=YOUR_SECRET_HERE

# Choose ONE LLM provider:
# Option A: OpenRouter (https://openrouter.ai/)
OPENROUTER_API_KEY=sk-or-v1-YOUR_KEY_HERE

# Option B: Google Gemini (https://makersuite.google.com/app/apikey)
# GEMINI_API_KEY=AIza_YOUR_KEY_HERE
```

**Database is already configured** (SQLite - no installation needed!)

---

## Step 3: Install & Run (2 minutes)

```powershell
# Navigate to project
cd "c:\class project\Razorpay\reconcile-agent"

# Install dependencies (if not already done)
pip install -r requirements.txt

# Run database migrations (creates tables)
alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Step 4: Test It! (30 seconds)

### Option A: Web UI (Easiest)

1. Open browser: **http://localhost:8000/**
2. Click **"Run Seeded 50-Record Batch"**
3. See instant results! ✅

### Option B: API Test

```powershell
# Health check
curl http://localhost:8000/api/v1/health

# Expected:
# {"status":"ok","db":"connected"}
```

### Option C: Run Tests

```powershell
# Run all 26 tests
pytest tests/test_adversarial.py -v

# Expected: 26 passed ✅
```

---

## What You Get

✅ **Web Dashboard**: http://localhost:8000/  
✅ **Interactive API Docs**: http://localhost:8000/docs  
✅ **26 Comprehensive Tests**: All passing  
✅ **Data Quality Metrics**: Duplicates & skipped rows tracked  
✅ **Sample Data Included**: 50-record test dataset ready  

---

## Troubleshooting

### "Can't find module X"
```powershell
pip install -r requirements.txt --upgrade
```

### "Razorpay connection failed"
- Check your Key ID starts with `rzp_test_`
- Verify Key Secret is correct
- Try: `curl -u YOUR_KEY:YOUR_SECRET https://api.razorpay.com/v1/payments`

### "Database error"
- Run: `alembic upgrade head`
- File `reconcile.db` will be created automatically

### "LLM error"
- Verify your API key is correct
- Test OpenRouter: `curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer YOUR_KEY"`

---

## Next Steps

**With Razorpay Test Account:**
```powershell
# Generate sample orders in your account
python scripts/seed_razorpay_test_account.py
```

**Explore the API:**
- http://localhost:8000/docs (Swagger UI)
- Try uploading your own CSV files

**Run Advanced Tests:**
```powershell
# All test suites
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

---

## What's Working

- ✅ 3-way reconciliation (Razorpay + Bank + Ledger)
- ✅ Settlement grouping & matching
- ✅ Exception detection with reason codes
- ✅ Duplicate order_id tracking (US7)
- ✅ Skipped row visibility (P3)
- ✅ Excel BOM support (H4)
- ✅ Stable pagination (H6)
- ✅ Deterministic retry (US10)
- ✅ 26 adversarial tests passing

---

## Need Help?

📖 **Detailed Setup**: See `SETUP_GUIDE.md`  
📋 **Test Strategy**: See `ADVERSARIAL_TEST_PRD.md`  
📊 **Test Results**: See `ADVERSARIAL_TEST_REVIEW_SUMMARY.md`  
🧪 **Test Suite**: Run `pytest tests/ -v`

---

**You're all set! Happy reconciling! 🎉**
