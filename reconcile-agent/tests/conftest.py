from __future__ import annotations

import datetime
import json
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app
from app.models.batch import Batch
from app.models.enums import BatchStatus, Decision, MatchMethod, ReasonCode, ResultScope
from app.models.payment import Payment
from app.models.reconciliation_result import ReconciliationResult

# Enable test fixtures for test runs (§10.1)
os.environ["USE_FIXTURES"] = "1"

# Use isolated SQLite in-memory for testing (§10.1)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session for each test with fresh schema."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with database dependency overridden and rate limiting disabled."""
    from app.core.security import TokenBucketRateLimiter, rate_limiter
    
    async def override_get_db():
        yield db_session

    # Override rate limiter with very high capacity for tests to prevent 429 errors
    test_rate_limiter = TokenBucketRateLimiter(capacity=10000, refill_rate=1000.0)
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[rate_limiter] = test_rate_limiter
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fixtures_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def razorpay_fixture_data(fixtures_dir: str) -> list[dict]:
    path = os.path.join(fixtures_dir, "razorpay_payments_50_mixed.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("items", [])


@pytest_asyncio.fixture
async def seeded_batch(db_session: AsyncSession) -> Batch:
    """Creates a sample batch with completed reconciliation results and payments for testing."""
    batch_id = uuid.uuid4()
    batch = Batch(
        id=batch_id,
        idempotency_key=f"seeded_batch_{uuid.uuid4().hex[:8]}",
        status=BatchStatus.COMPLETED,
    )
    db_session.add(batch)

    # Add sample payments
    pay1 = Payment(
        id="pay_qa_001",
        order_id="order_qa_001",
        amount_paise=50000,
        fee_paise=1180,
        tax_paise=180,
        status="captured",
    )
    pay2 = Payment(
        id="pay_qa_002",
        order_id="order_qa_002",
        amount_paise=30000,
        fee_paise=708,
        tax_paise=108,
        status="captured",
    )
    db_session.add_all([pay1, pay2])

    # Add sample reconciliation results
    r1 = ReconciliationResult(
        id=uuid.uuid4(),
        batch_id=batch_id,
        result_scope=ResultScope.PAYMENT,
        payment_id="pay_qa_001",
        decision=Decision.MATCH,
        match_method=MatchMethod.EXACT_UTR.value,
        expected_amount_paise=50000,
        actual_amount_paise=50000,
        difference_paise=0,
    )
    r2 = ReconciliationResult(
        id=uuid.uuid4(),
        batch_id=batch_id,
        result_scope=ResultScope.PAYMENT,
        payment_id="pay_qa_002",
        decision=Decision.EXCEPTION,
        reason_code=ReasonCode.AMOUNT_MISMATCH.value,
        expected_amount_paise=30000,
        actual_amount_paise=28000,
        difference_paise=2000,
    )
    db_session.add_all([r1, r2])
    await db_session.commit()
    await db_session.refresh(batch)
    return batch
