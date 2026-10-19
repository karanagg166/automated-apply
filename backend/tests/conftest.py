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
             "GMAIL_REFRESH_TOKEN", "MCP_API_TOKEN", "GMAIL_REDIRECT_URI", "GMAIL_EXPECTED_EMAIL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ[name] = ""

os.environ["OAUTH_ENCRYPTION_KEYS"] = "{}"
os.environ["OAUTH_ACTIVE_KEY_ID"] = ""
os.environ["GMAIL_SENDING_ENABLED"] = "false"
os.environ["MCP_REMOTE_ENABLED"] = "false"
os.environ["MCP_ALLOW_DRAFT_CREATION"] = "false"

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


@pytest.fixture
def mcp_auth(monkeypatch):
    monkeypatch.setenv("MCP_REMOTE_ENABLED", "true")
    monkeypatch.setenv("MCP_API_TOKEN", "fictional-mcp-owner-token-at-least-32-characters")
    monkeypatch.setenv("MCP_REQUIRE_TLS", "true")
    get_settings.cache_clear()
    yield {"Authorization": "Bearer fictional-mcp-owner-token-at-least-32-characters",
           "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def mcp_client(mcp_auth):
    from backend.app.main import app, mcp_app
    import asyncio
    ready, stop = asyncio.Event(), asyncio.Event()

    async def serve_lifespan():
        async with mcp_app.lifespan(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(serve_lifespan())
    await ready.wait()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
            yield client
    finally:
        stop.set()
        await task


@pytest_asyncio.fixture
async def outreach_target(db_session, phase2_profile):
    from backend.tests.phase4a_fakes import target
    return await target(db_session)


@pytest_asyncio.fixture
async def oauth_bundle(db_session):
    from backend.app.integrations.connection_service import ConnectionService
    from backend.app.integrations.google_oauth import GoogleOAuth
    from backend.tests.phase4a_fakes import GoogleFixture, oauth_settings
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        yield ConnectionService(db_session, settings, GoogleOAuth(settings, client)), fake, settings


@pytest_asyncio.fixture
async def sending_bundle(db_session, phase2_profile):
    from backend.tests.phase4b_fakes import approved_target, bundle, connect_sender, SendFixture
    from backend.app.services.gmail_sending import GmailSendingService
    settings, google = await bundle()
    async with google.client() as http:
        connection = await connect_sender(db_session, settings, google, http)
        draft, contact, evidence, mailbox = await approved_target(db_session, settings)
        sender = SendFixture()
        service = GmailSendingService(db_session, settings, connection, sender)
        yield service, draft, sender, contact, evidence, mailbox


@pytest_asyncio.fixture
async def application_target(db_session, phase2_profile):
    from backend.tests.phase5a_fakes import target
    return await target(db_session, phase2_profile)


@pytest.fixture
def packet_service(db_session, phase2_settings):
    from backend.app.services.application_answer_service import ApplicationAnswerService
    from backend.app.services.applications.service import ApplicationPacketService
    from backend.tests.phase2a_fakes import FakeProvider
    answer = ApplicationAnswerService(db_session, phase2_settings, FakeProvider())
    return ApplicationPacketService(db_session, answer)
