"""Fictional Phase 3 transport inside the disposable PostgreSQL browser harness.

Uses actual account storage, encryption, selected-message sync, evidence, imports
and owner APIs. Provider HTTP is intercepted; no genuine account is contacted.
Started by ``frontend/playwright.browser.config.ts`` (loopback port 8767).
"""

import asyncio
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

ACCOUNT_IDS = [UUID("10000000-0000-4000-8000-000000000001"), UUID("10000000-0000-4000-8000-000000000002")]
QUESTION = "Describe the fictional payment gateway incident you personally resolved in October."


async def install(app, settings, factory):
    from backend.app.api.v1.integrations import read_service
    from backend.app.core.security import require_api_token
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.db.session import get_db_session, get_engine
    from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
    from backend.app.integrations.google_oauth import READ_SCOPES
    from backend.app.integrations.token_store import TokenStore
    from backend.app.local_agent.models import (
        AgentOperation,
        AgentPolicy,
        PolicyEvent,
        TelegramDelivery,
        TelegramState,
    )
    from backend.app.models.connected_account import GmailReadAccount

    # Historical migration fixtures predate these local-agent model tables. The
    # complete Connections page reads them alongside Gmail. Create only these
    # additional fixture tables inside the already-validated disposable child DB.
    async with get_engine().begin() as connection:
        for model in (AgentPolicy, PolicyEvent, AgentOperation, TelegramState, TelegramDelivery):
            await connection.run_sync(lambda conn, table=model.__table__: table.create(conn, checkfirst=True))

    calls = []
    addresses = ["first-fixture@example.com", "second-fixture@example.com"]
    tokens = {"fixture-access-1": 0, "fixture-access-2": 1}

    def respond(request):
        # Only the production GmailReadClient's GET requests are accepted here.
        assert request.method == "GET"
        assert request.url.host == "gmail.googleapis.com"
        index = tokens[request.headers["Authorization"].removeprefix("Bearer ")]
        prefix = "/gmail/v1/users/me/messages"
        calls.append({"method": request.method, "path": request.url.path, "account_id": str(ACCOUNT_IDS[index])})
        message = f"fixture-message-{index + 1}"
        if request.url.path == prefix:
            return httpx.Response(200, json={"messages": [{"id": message}]})
        assert request.url.path == prefix + "/" + message
        payload = {
            "mimeType": "text/plain",
            "headers": [{"name": "From", "value": "jobs@example.org"}, {"name": "Subject", "value": "Job alert: fictional engineer"}],
        }
        if request.url.params.get("format") == "full":
            raw = f"Job alert https://fixture-company-{index + 1}.example/jobs/backend?tracking=discarded"
            payload["body"] = {"data": base64.urlsafe_b64encode(raw.encode()).decode()}
        return httpx.Response(200, json={"id": message, "threadId": f"fixture-thread-{index + 1}", "internalDate": str(int((datetime.now(timezone.utc) - timedelta(minutes=2)).timestamp() * 1000)), "labelIds": ["Label_Jobs"], "payload": payload})

    class FixtureIdentity:
        def configured(self):
            return True

        async def identity(self, token):
            index = tokens[token]
            return f"fixture-subject-{index + 1}", addresses[index]

        async def revoke(self, token):
            return None  # Local fictional revocation, never a provider request.

    def service(session):
        # MockTransport has no sockets; production read, path and evidence guards run.
        return GmailReadService(session, settings, google=FixtureIdentity(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    async def dependency(session: AsyncSession = Depends(get_db_session)):
        instance = service(session)
        try:
            yield instance
        finally:
            await instance.client.aclose()

    store = TokenStore(settings)
    async with factory() as session:
        for index, account_id in enumerate(ACCOUNT_IDS):
            session.add(OwnerPreference(key=f"gmail_workspace_slot:read_{index + 1}", value={"account_id": str(account_id)}))
            session.add(GmailReadAccount(
                id=account_id, google_subject=f"fixture-subject-{index + 1}",
                account_email=addresses[index], connected_at=datetime.now(timezone.utc),
                last_verified_at=datetime.now(timezone.utc), status="connected",
                granted_scopes=sorted(READ_SCOPES), encryption_key_id="fixture-v1",
                encrypted_access_token=store.encrypt(f"fixture-access-{index + 1}", str(account_id) + ":access"),
                encrypted_refresh_token=store.encrypt(f"fixture-refresh-{index + 1}", str(account_id) + ":refresh"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
        await session.commit()
        for account_id in ACCOUNT_IDS:
            instance = service(session)
            try:
                await instance.configure(account_id, ReadPolicy(expected_version=0, enabled=True, label_allowlist=["Label_Jobs"], read_body=True, body_purpose="Fictional browser test of selected job alerts"))
                await instance.sync(account_id)
            finally:
                await instance.client.aclose()

    app.dependency_overrides[read_service] = dependency

    @app.get("/_fictional_test/phase3-provider-audit", dependencies=[Depends(require_api_token)])
    async def audit():
        return {"fixture": True, "calls": calls, "mailbox_writes": 0, "external_requests": 0}

    output = Path(__file__).resolve().parents[2] / "reports/phase3-browser-fixture.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"fixture": True, "account_ids": [str(value) for value in ACCOUNT_IDS], "question": QUESTION}))


async def serve(url):
    """Serve the real API on loopback 8767 over a fresh disposable PostgreSQL 17 database."""
    import asyncpg
    import uvicorn
    from cryptography.fernet import Fernet

    root = Path(__file__).resolve().parents[2]
    parsed = urlsplit(url)
    if (parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path != "/candidate_profile_test"
            or parsed.query or parsed.fragment):
        raise ValueError("Only disposable localhost candidate_profile_test is allowed")
    admin = await asyncpg.connect(url)
    if int(await admin.fetchval("SHOW server_version_num")) // 10000 != 17:
        await admin.close()
        raise ValueError("Disposable PostgreSQL 17 is required")
    name = "candidate_profile_test_browser_" + uuid4().hex
    role_suffix = uuid4().hex
    roles = ("fixture_owner_" + role_suffix, "fixture_runtime_" + role_suffix)
    await admin.execute(f'CREATE DATABASE "{name}"')
    child = urlunsplit(parsed._replace(path="/" + name))
    roles_created = False
    try:
        connection = await asyncpg.connect(child)
        try:
            for role in ("anon", "authenticated", "service_role"):
                if not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
                    await connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
            bootstrap = (root / "docs/sql/phase9-role-bootstrap.sql").read_text()
            for original, fixture_role in zip(("job_agent_owner", "job_agent_runtime"), roles):
                bootstrap = bootstrap.replace(original, fixture_role)
            await connection.execute(bootstrap)
            roles_created = True
            for migration in sorted((root / "supabase/migrations").glob("*.sql")):
                await connection.execute(migration.read_text())
            from backend.app.integrations.gmail.schema import render_review_sql

            read_sql = render_review_sql("job_agent")
            for original, fixture_role in zip(("job_agent_owner", "job_agent_runtime"), roles):
                read_sql = read_sql.replace(original, fixture_role)
            await connection.execute(read_sql)
            assert not await connection.fetchval("SELECT has_table_privilege('anon','job_agent.owner_preferences','SELECT')")
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated','job_agent.private_resumes','SELECT')")
        finally:
            await connection.close()
        from backend.app.core.config import Settings, configure_operator

        settings = Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_SCHEMA="job_agent",
            LOG_LEVEL="WARNING",
            DATABASE_URL=child.replace("postgresql://", "postgresql+asyncpg://", 1),
            DB_POOL_SIZE=1,
            DB_MAX_OVERFLOW=0,
            SECRET_KEY="fictional-browser-demo-only",  # pragma: allowlist secret — fictional local test value
            JOB_AGENT_API_TOKEN="fictional-browser-demo-owner-token",
            BROWSER_OWNER_APPROVAL_KEY="fictional-owner-approval-separate-from-cli-token",  # pragma: allowlist secret — isolated fixture only
            RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            GEMINI_API_KEY=None,
            LLM_MODEL=None,
            LLM_PROVIDER="gemini",
            LLM_LOCAL_FALLBACK_ENABLED=False,
            COHERE_EVALUATION_ENABLED=False,
            COHERE_API_KEY=None,
            COHERE_MODEL=None,
            APPROVED_ANSWER_REUSE_ENABLED=True,
            OPPORTUNITY_CONTEXT_ENABLED=True,
            UI_FIXTURE_MODE=True,
            GMAIL_READ_SYNC_ENABLED=True,
            GMAIL_RETENTION_ENABLED=True,
            GMAIL_READ_BODY_REVIEWED=True,
            OAUTH_ACTIVE_KEY_ID="fixture-v1",
            OAUTH_ENCRYPTION_KEYS={"fixture-v1": Fernet.generate_key().decode()},
            **{key: field.get_default(call_default_factory=True)
               for key, field in Settings.model_fields.items() if key.startswith("CANDIDATE_")},
        )
        configure_operator(settings)
        from fastapi import Depends as Dependency

        from backend.app.api.v1.applications import application_service
        from backend.app.dashboard.models import PrivateResume
        from backend.app.db.session import (
            close_db_engine,
            get_db_session,
            get_session_factory,
        )
        from backend.app.main import app
        from backend.app.models.application_answer import (
            ApplicationAnswerDraft,
            CandidateResource,
        )
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.application_answer_service import (
            ApplicationAnswerService,
        )
        from backend.app.services.applications.service import ApplicationPacketService
        from backend.tests.opportunity_fakes import OpportunityFixtureProvider
        from backend.tests.test_phase7_dashboard import pdf_bytes

        def fictional_application_service(
            session: Annotated[AsyncSession, Dependency(get_db_session, scope="function")],
        ):
            return ApplicationPacketService(session, ApplicationAnswerService(
                session,
                settings.model_copy(update={"LLM_PROVIDER": "ollama", "OLLAMA_ENABLED": True,
                                            "OLLAMA_MODEL": "fictional-injected-provider-no-live-model"}),
                OpportunityFixtureProvider(separator=" "),
                owns_read_transaction=True,
            ))

        app.dependency_overrides[application_service] = fictional_application_service
        async with get_session_factory()() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name="Alex Example", email="alex@example.com", phone="+15550000000",
                verified_skills=["Python", "FastAPI"],
                projects=[{"name": "Fictional Relay", "purpose": "A task update service.",
                           "contribution": "I built backend authentication using Python and FastAPI."}],
                preferences={"notice_period_days": 30},
            ))
            session.add(ApplicationAnswerDraft(
                candidate_profile_id=profile.id, question="Describe a project you built",
                answer="I built backend authentication using Python and FastAPI.",
                question_category="project_explanation", writing_style="professional",
                candidate_profile_version=profile.version, review_status="reviewed",
                evidence_references=[{"source_type": "verified_project", "source_id": f"{profile.id}:project:0"}],
            ))
            resume_id = uuid4()
            resource = CandidateResource(
                candidate_profile_id=profile.id, resource_type="resume", label="Fictional approved PDF",
                url="private-resume:" + str(resume_id), source_type="private_upload", is_primary=True,
                user_confirmed=True,
            )
            session.add(resource)
            await session.flush()
            raw = pdf_bytes("Alex Example | alex@example.com | Python FastAPI")
            session.add(PrivateResume(
                id=resume_id, label="Fictional approved PDF", resource_id=resource.id, confirmed=True,
                ciphertext=Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()).encrypt(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            ))
            await session.commit()
        await install(app, settings, get_session_factory())
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8767, log_level="warning"))
        print("Fictional PostgreSQL browser fixture ready on loopback port 8767", flush=True)
        try:
            await server.serve()
        finally:
            app.dependency_overrides.pop(application_service, None)
            await close_db_engine()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        if roles_created:
            await admin.execute(f'DROP ROLE "{roles[1]}", "{roles[0]}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(serve(os.environ["PROFILE_TEST_DATABASE_URL"]))
