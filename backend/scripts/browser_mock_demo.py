"""Disposable PostgreSQL 17 + actual local FastAPI + fictional employer fixture.

The supplied URL must name candidate_profile_test on loopback. Only a newly created
child database receives migrations or writes. No repository environment files are read.
Use --serve for the Next.js browser journey; default runs the assisted lifecycle proof.
"""

import argparse
import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def run(url, serve=False):
    import asyncpg
    import httpx
    import uvicorn
    from cryptography.fernet import Fernet

    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only disposable localhost candidate_profile_test is allowed")
    admin = await asyncpg.connect(url)
    if int(await admin.fetchval("SHOW server_version_num")) // 10000 != 17:
        await admin.close()
        raise ValueError("Disposable PostgreSQL 17 is required")
    name = "candidate_profile_test_browser_" + uuid4().hex
    await admin.execute(f'CREATE DATABASE "{name}"')
    child = urlunsplit(parsed._replace(path="/" + name))
    task, server = None, None
    try:
        connection = await asyncpg.connect(child)
        try:
            for role in ("anon", "authenticated", "service_role"):
                if not await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
                ):
                    await connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
            for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
                await connection.execute(migration.read_text())
            assert not await connection.fetchval(
                "SELECT has_table_privilege('anon','job_agent.owner_preferences','SELECT')"
            )
            assert not await connection.fetchval(
                "SELECT has_table_privilege('authenticated','job_agent.private_resumes','SELECT')"
            )
        finally:
            await connection.close()
        from backend.tests.browser_employers import employer_site

        with (
            tempfile.TemporaryDirectory(prefix="automated-apply-browser-") as directory,
            employer_site() as (employer, writes),
        ):
            from backend.app.core.config import Settings, configure_operator

            settings = Settings(
                _env_file=None,
                ENVIRONMENT="testing",
                LOG_LEVEL="WARNING",
                DATABASE_URL=child.replace("postgresql://", "postgresql+asyncpg://", 1),
                SECRET_KEY="fictional-browser-demo-only", # pragma: allowlist secret — fictional local test value
                JOB_AGENT_API_TOKEN="fictional-browser-demo-owner-token",
                BROWSER_ASSISTANT_ENABLED=True,
                BROWSER_ALLOWED_ORIGINS=[employer],
                BROWSER_PROFILE_ROOT=str(Path(directory).resolve() / "profiles"),
                BROWSER_CHANNEL="chromium",
                BROWSER_HEADLESS=True,
                RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                GEMINI_API_KEY=None,
                LLM_MODEL=None,
                COHERE_EVALUATION_ENABLED=False,
                OLLAMA_ENABLED=False,
                UI_FIXTURE_MODE=True,
            )
            # Settings' origin format contains an explicit port for all destinations.
            configure_operator(settings)
            from backend.app.browser.runner import browser
            from backend.app.dashboard.models import PrivateResume
            from backend.app.db.session import close_db_engine, get_session_factory
            from backend.app.main import app
            from backend.app.models.application_answer import CandidateResource
            from backend.app.repositories.candidate_profile import (
                CandidateProfileRepository,
            )
            from backend.app.schemas.candidate_profile import CandidateProfileCreate
            from backend.tests.test_phase7_dashboard import pdf_bytes

            async with get_session_factory()() as session:
                profile = await CandidateProfileRepository(
                    session
                ).create_primary_profile(
                    CandidateProfileCreate(
                        full_name="Alex Example",
                        email="alex@example.com",
                        phone="+15550000000",
                        verified_skills=["Python", "FastAPI"],
                        preferences={"notice_period_days": 30},
                    )
                )
                resume_id = uuid4()
                resource = CandidateResource(
                    candidate_profile_id=profile.id,
                    resource_type="resume",
                    label="Fictional approved PDF",
                    url="private-resume:" + str(resume_id),
                    source_type="private_upload",
                    is_primary=True,
                    user_confirmed=True,
                )
                session.add(resource)
                await session.flush()
                raw = pdf_bytes("Alex Example | alex@example.com | Python FastAPI")
                session.add(
                    PrivateResume(
                        id=resume_id,
                        label="Fictional approved PDF",
                        resource_id=resource.id,
                        confirmed=True,
                        ciphertext=Fernet(
                            settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()
                        ).encrypt(raw),
                        sha256=hashlib.sha256(raw).hexdigest(),
                    )
                )
                await session.commit()
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=8767, log_level="warning")
            )
            task = asyncio.create_task(server.serve())
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:8767",
                timeout=60,
                headers={"Authorization": "Bearer fictional-browser-demo-owner-token"},
                trust_env=False,
            ) as client:
                for _ in range(100):
                    if server.started:
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Local API did not start")
                payload = {
                    "application_url": employer + "/basic",
                    "company_name": "Example Circuit",
                    "job_title": "Backend Engineer",
                    "idempotency_key": "browser-pg-demo-001",
                }
                response = await client.post(
                    "/api/v1/browser-applications", json=payload
                )
                assert response.status_code == 200, response.text
                packet = response.json()
                if serve:
                    # This fictional URL/packet manifest contains no credentials or personal data.
                    output = ROOT / "reports/browser-mock.private.json"
                    output.parent.mkdir(exist_ok=True)
                    output.write_text(
                        __import__("json").dumps(
                            {
                                "packet_id": packet["id"],
                                "employer_url": employer + "/basic",
                            }
                        )
                    )
                    print(
                        "Fictional PostgreSQL browser demo ready on loopback port 8767",
                        flush=True,
                    )
                    await task
                else:
                    route = "/api/v1/browser-applications/" + packet["id"]
                    response = await client.post(
                        route + "/open",
                        json={
                            "expected_revision": packet["revision"],
                            "approve_dedicated_profile": True,
                            "confirm_destination_permission": True,
                        },
                    )
                    assert response.status_code == 200, response.text
                    # Independent API transactions race the same packet revision: one winner.
                    attempts = await asyncio.gather(
                        *[
                            client.post(
                                route + "/actions",
                                json={
                                    "expected_revision": packet["revision"],
                                    "action": "analyze",
                                },
                            )
                            for _ in range(2)
                        ]
                    )
                    assert sorted(r.status_code for r in attempts) == [200, 409], [
                        r.text for r in attempts
                    ]
                    response = next(r for r in attempts if r.status_code == 200)
                    state = response.json()
                    revision = state["packet"]["revision"]
                    response = await client.post(
                        route + "/actions",
                        json={
                            "expected_revision": revision,
                            "action": "fill",
                            "confirm_reviewed_values": True,
                            "confirm_page_context": True,
                        },
                    )
                    assert response.status_code == 200, response.text
                    assert (
                        response.json()["analysis"]["diagnostic"]
                        == "filled_review_on_website"
                    )
                    page = browser.sessions[packet["id"]].page
                    assert (
                        await page.locator("[name=name]").input_value()
                        == "Alex Example"
                    )
                    assert (
                        await page.locator("[type=file]").evaluate(
                            "(e)=>e.files.length"
                        )
                        == 1
                    )
                    from backend.app.ai.base import ProviderError
                    from backend.app.ai.optional_usage import OptionalUsageManager

                    usage = OptionalUsageManager(
                        get_session_factory(),
                        settings.model_copy(
                            update={
                                "LLM_PROVIDER": "cohere",
                                "LLM_MONTHLY_MAX_REQUESTS": 1,
                            }
                        ),
                    )
                    reservations = await asyncio.gather(
                        *(usage.reserve() for _ in range(5)), return_exceptions=True
                    )
                    assert sum(isinstance(r, str) for r in reservations) == 1
                    assert sum(isinstance(r, ProviderError) for r in reservations) == 4
                    # Actual manual submission in a fictional site, with real receipt and explicit owner report.
                    await client.post(
                        route + "/actions",
                        json={"expected_revision": revision, "action": "take_over"},
                    )
                    await page.locator("[name=ctc]").fill(
                        "Fictional value supplied manually"
                    )
                    await page.locator("[type=checkbox]").check()
                    await page.locator("[type=submit]").click()
                    await page.wait_for_url(employer + "/receipt")
                    assert "MOCK-ONLY-123" in await page.inner_text("body")
                    assert writes == ["/receipt"]
                    response = await client.post(
                        "/api/v1/application-packets/"
                        + packet["id"]
                        + "/report-submission",
                        json={
                            "expected_revision": revision,
                            "idempotency_key": "mock-owner-receipt-001",
                            "human_confirmed": True,
                            "confirmation": "I submitted this application on the official website",
                            "receipt_reference": "MOCK-ONLY-123",
                        },
                    )
                    assert response.status_code == 200, response.text
                    await browser.close(packet["id"])
                    await close_db_engine()
                    # A new engine reads durable evidence after the browser and connections are closed.
                    response = await client.get(route)
                    assert response.status_code == 200, response.text
                    assert (
                        response.json()["packet"]["lifecycle_state"]
                        == "user_reported_submitted"
                    )
                    assert not response.json()["connected"]
                    print(
                        "PASS: PG17 + TCP FastAPI + real Chromium analysis/fill + manual mock receipt + durable owner report; no automated submission"
                    )
            for key in list(browser.sessions):
                await browser.close(key)
            await close_db_engine()
    finally:
        if server:
            server.should_exit = True
        if task and not task.done():
            await task
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], args.serve))
