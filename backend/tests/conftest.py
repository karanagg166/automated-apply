"""Pytest configuration and async fixtures for Job Pulse Agent."""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Never read the owner's real project .env (v1 Settings + shared v2 loader) in tests.
os.environ["AUTOMATED_APPLY_ENV_REPO_FILES"] = "0"
os.environ.pop("AUTOMATED_APPLY_ENV_FILE", None)
# Single-instance locks (worker, Telegram poller) live in a per-run temp dir: tests never contend
# with (or block) a live worker running from this checkout.
import tempfile as _tempfile  # noqa: E402

os.environ["AUTOMATED_APPLY_LOCK_DIR"] = _tempfile.mkdtemp(prefix="aa-test-locks-")
# Never query/refocus real macOS apps from tests (browser background mode).
os.environ["AUTOMATED_APPLY_BROWSER_BACKGROUND"] = "0"
# Milestone 2: Human Pulse pacing (inter-field / pre-submit pauses, key-by-key typing) is off in tests.
os.environ["AUTOMATED_APPLY_HUMAN_PULSE"] = "0"

# Force testing environment before importing app settings
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_SCHEMA"] = "job_agent"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-long-for-testing"
# Environment overrides prevent loading local account credentials from .env files.
for name in ("COHERE_API_KEY", "GEMINI_API_KEY", "LLM_MODEL", "CANDIDATE_RESUME_DRIVE_URL", "CANDIDATE_RESUME_DRIVE_FILE_ID", "RESUME_ENCRYPTION_KEY", "CANDIDATE_GITHUB_URL",
             "CANDIDATE_ORIGINAL_LINKEDIN_URL", "CANDIDATE_PORTFOLIO_URL", "CANDIDATE_LEETCODE_URL",
             "CANDIDATE_CODEFORCES_URL", "CANDIDATE_GFG_URL", "CANDIDATE_HACKERRANK_URL", "JOB_AGENT_API_TOKEN",
             "HUNTER_API_KEY", "APOLLO_API_KEY", "SERPER_API_KEY",
             "SIGNALHIRE_API_KEY", "APIFY_API_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
             "GMAIL_REFRESH_TOKEN", "MCP_API_TOKEN", "GMAIL_REDIRECT_URI", "GMAIL_EXPECTED_EMAIL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ[name] = ""

# Phase 5: never read the owner's IMAP/Mail.app/enrichment config from the private env file.
for name in ("GMAIL_IMAP_EMAIL", "GMAIL_IMAP_APP_PASSWORD", "MAIL_DRAFT_RESUME_PATH", "MAIL_APP_SENDER",
             "APIFY_CONTACT_ACTOR_ID", "MAIL_DRAFT_CHANNEL"):
    os.environ[name] = ""
os.environ["MAIL_APP_FALLBACK_DISABLED"] = "true"
# Never let the owner's real free-LLM keys (incl. numbered failover keys) reach a test.
for _base in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
              "CLOUDFLARE_API_TOKEN", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN", "CEREBRAS_API_KEY", "COHERE_API_KEY",
              "CUSTOM_CLOUD_LLM_API_KEY", "CUSTOM_CLOUD_LLM_BASE_URL"):
    os.environ[_base] = ""
    for _i in range(2, 11):
        os.environ[f"{_base}_{_i}"] = ""
for _alias in ("GROQ_KEY", "GOOGLE_AI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY",
               "GEMINI_KEY", "MISTRAL_KEY", "OPENROUTER_KEY", "OPEN_ROUTER_API_KEY", "CF_API_TOKEN",
               "CLOUDFLARE_AI_TOKEN", "CLOUDFLARE_WORKERS_AI_TOKEN", "CF_WORKERS_AI_TOKEN", "GH_MODELS_TOKEN",
               "GITHUB_MODELS_PAT", "CEREBRAS_KEY", "GROQ_TOKEN"):
    os.environ[_alias] = ""
os.environ["ENRICHMENT_FETCH_CAREERS_PAGE"] = "false"

os.environ["OAUTH_ENCRYPTION_KEYS"] = "{}"
os.environ["OAUTH_ACTIVE_KEY_ID"] = ""
os.environ["GMAIL_SENDING_ENABLED"] = "false"
os.environ["GMAIL_DRAFTS_ENABLED"] = "false"
os.environ["GMAIL_RETENTION_ENABLED"] = "false"
os.environ["RESUME_DRIVE_SYNC_ENABLED"] = "false"
os.environ["AUTOMATION_EXECUTION_ENABLED"] = "false"
os.environ["MCP_REMOTE_ENABLED"] = "false"
os.environ["MCP_ALLOW_DRAFT_CREATION"] = "false"
os.environ["COHERE_ENABLED"] = "false"
os.environ["COHERE_EVALUATION_KEY_CONFIRMED"] = "false"
os.environ["COHERE_OWNER_TEXT_AUTHORIZED"] = "false"
os.environ.update(COHERE_CANDIDATE_DATA_AUTHORIZED="false", GEMINI_CANDIDATE_DATA_AUTHORIZED="false")
os.environ["AGY_ENABLED"] = "false"
os.environ["AGY_QUOTA_AUTHORIZED"] = "false"
os.environ["AGY_MODEL"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_OWNER_USER_ID"] = ""
os.environ["TELEGRAM_OWNER_CHAT_ID"] = ""
os.environ["TELEGRAM_LOCAL_AI_ENABLED"] = "false"
os.environ["OLLAMA_MODEL"] = ""
os.environ["BROWSER_SUBMIT_ENABLED"] = "false"
os.environ["CHROME_NATIVE_MESSAGING_ENABLED"] = "false"
os.environ["CHROME_EXTENSION_ID"] = ""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import backend.app.db.session as db_session_module
from backend.app.main import app
from backend.app.models.base import Base

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
    from backend.app.resume_sync import service as resume_sync_service

    monkeypatch.setattr(resume_sync_service, "fetch_pdf", deny_async)


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
    return Settings(_env_file=None, LLM_MODEL="gemini-test-model", GEMINI_API_KEY="fictional-test-key", GEMINI_ENABLED=True, GEMINI_APPROVED_MONTHLY_REQUESTS=200, GEMINI_CANDIDATE_DATA_AUTHORIZED=True)


@pytest.fixture
def phase2_auth(monkeypatch):
    from backend.app.core.config import get_settings
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "phase2-fictional-token")
    get_settings.cache_clear()
    yield {"Authorization": "Bearer phase2-fictional-token"}
    get_settings.cache_clear()


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
