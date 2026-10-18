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
# Environment overrides prevent loading local account credentials from .env files.
for name in ("GEMINI_API_KEY", "LLM_MODEL", "CANDIDATE_RESUME_DRIVE_URL", "CANDIDATE_GITHUB_URL",
             "CANDIDATE_ORIGINAL_LINKEDIN_URL", "CANDIDATE_PORTFOLIO_URL", "CANDIDATE_LEETCODE_URL",
             "CANDIDATE_CODEFORCES_URL", "CANDIDATE_GFG_URL", "CANDIDATE_HACKERRANK_URL", "JOB_AGENT_API_TOKEN",
             "HUNTER_API_KEY", "APOLLO_API_KEY", "SERPER_API_KEY",
             "SIGNALHIRE_API_KEY", "APIFY_API_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
             "GMAIL_REFRESH_TOKEN", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ[name] = ""

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


@pytest.fixture(autouse=True)
def block_external_http(monkeypatch):
    """All HTTP tests must use MockTransport/ASGITransport, never live accounts."""
    import httpx

    async def deny_async(*args, **kwargs):
        pytest.fail("Real HTTP is disabled in unit tests; inject MockTransport")

    def deny_sync(*args, **kwargs):
        pytest.fail("Real HTTP is disabled in unit tests; inject MockTransport")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_sync)


@pytest_asyncio.fixture
async def phase2_profile(db_session):
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.tests.phase2a_fakes import PROJECT
    profile = await CandidateProfileRepository(db_session).create_primary_profile(CandidateProfileCreate(
        full_name="Alex Example", email="alex@example.com", github_url="https://github.com/example",
        linkedin_url="https://www.linkedin.com/in/example", portfolio_url="https://example.com/portfolio",
        verified_experience_years=2, verified_skills=["Python", "FastAPI"], projects=[PROJECT],
        preferences={"notice_period_days": 30},
    ))
    await db_session.commit()
    return profile


@pytest.fixture
def phase2_settings():
    from backend.app.core.config import Settings
    return Settings(_env_file=None, LLM_MODEL="gemini-test-model", GEMINI_API_KEY="fictional-test-key")


@pytest.fixture
def phase2_auth(monkeypatch):
    from backend.app.core.config import get_settings
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "phase2-fictional-token")
    get_settings.cache_clear()
    yield {"Authorization": "Bearer phase2-fictional-token"}
    get_settings.cache_clear()
