from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# SQLite-specific configuration for better concurrency handling
engine_kwargs = {
    "echo": False,
    "future": True,
}

# Add SQLite-specific settings to reduce database lock errors
if settings.database_url.startswith("sqlite"):
    engine_kwargs.update({
        "connect_args": {
            "timeout": 30,  # Wait up to 30 seconds for locks
            "check_same_thread": False,  # Allow usage across threads
        },
        "pool_pre_ping": True,  # Verify connections before using
        "pool_size": 5,  # Limit connection pool size
        "max_overflow": 10,  # Allow temporary overflow connections
    })

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
