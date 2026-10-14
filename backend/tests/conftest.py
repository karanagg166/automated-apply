"""Pytest configuration and async fixtures for Job Pulse Agent."""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force testing environment before importing app settings
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_SCHEMA"] = "job_agent"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-long-for-testing"

from collections.abc import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import get_settings
from backend.app.models.base import Base
import backend.app.db.session as db_session_module
from backend.app.main import app

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
test_session_factory = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Override the global engine and session factory for tests
db_session_module._engine = test_engine
db_session_module._session_factory = test_session_factory


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Create all schema tables in memory before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated async session for database operations."""
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client for FastAPI routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
