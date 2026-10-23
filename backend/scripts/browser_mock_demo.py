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


async def run(
    url,
    serve=False,
    submission_demo=False,
    receipt_mode="valid",
    opportunity_demo=False,
    steps_demo=False,
    navigation_demo=False,
    cancellation_demo=False,
    live_ollama_model=None,
):
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
            if submission_demo:
                await connection.execute(
                    (
                        ROOT / "backend/app/browser/migrations/001_mock_submission.sql"
                    ).read_text()
                )
                for role in ("anon", "authenticated", "service_role"):
                    assert not await connection.fetchval(
                        "SELECT has_table_privilege($1,'job_agent.browser_submission_attempts','SELECT,INSERT,UPDATE,DELETE')",
                        role,
                    )
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
                SECRET_KEY="fictional-browser-demo-only",  # pragma: allowlist secret — fictional local test value
                JOB_AGENT_API_TOKEN="fictional-browser-demo-owner-token",
                BROWSER_ASSISTANT_ENABLED=True,
                BROWSER_MOCK_SUBMISSION_ENABLED=submission_demo,
                BROWSER_OWNER_APPROVAL_KEY="fictional-owner-approval-separate-from-cli-token",  # pragma: allowlist secret — isolated fixture only
                BROWSER_ALLOWED_ORIGINS=[employer],
                BROWSER_PROFILE_ROOT=str(Path(directory).resolve() / "profiles"),
                BROWSER_CHANNEL="chromium",
                BROWSER_HEADLESS=True,
                RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                GEMINI_API_KEY=None,
                LLM_MODEL=None,
                LLM_PROVIDER="ollama" if live_ollama_model else "gemini",
                LLM_TIMEOUT_SECONDS=80 if live_ollama_model else 30,
                LLM_MONTHLY_MAX_REQUESTS=5 if live_ollama_model else 200,
                LLM_LOCAL_FALLBACK_ENABLED=False,
                COHERE_EVALUATION_ENABLED=False,
                COHERE_API_KEY=None,
                COHERE_MODEL=None,
                OLLAMA_ENABLED=bool(live_ollama_model),
                OLLAMA_MODEL=live_ollama_model,
                APPROVED_ANSWER_REUSE_ENABLED=True,
                OPPORTUNITY_CONTEXT_ENABLED=True,
                UI_FIXTURE_MODE=True,
                **{
                    key: None
                    for key in Settings.model_fields
                    if key.startswith("CANDIDATE_")
                },
            )
            # Settings' origin format contains an explicit port for all destinations.
            configure_operator(settings)
            from backend.app.browser.runner import browser
            from backend.app.dashboard.models import PrivateResume
            from backend.app.db.session import close_db_engine, get_session_factory
            from backend.app.main import app
            from backend.app.models.application_answer import (
                ApplicationAnswerDraft,
                CandidateResource,
            )
            from backend.app.repositories.candidate_profile import (
                CandidateProfileRepository,
            )
            from backend.app.schemas.candidate_profile import CandidateProfileCreate
            from backend.tests.test_phase7_dashboard import pdf_bytes

            if (serve or opportunity_demo) and not live_ollama_model:
                from fastapi import Depends

                from backend.app.api.v1.applications import application_service
                from backend.app.db.session import get_db_session
                from backend.app.services.application_answer_service import (
                    ApplicationAnswerService,
                )
                from backend.app.services.applications.service import (
                    ApplicationPacketService,
                )
                from backend.tests.opportunity_fakes import OpportunityFixtureProvider

                def fictional_application_service(session=Depends(get_db_session)):
                    return ApplicationPacketService(
                        session,
                        ApplicationAnswerService(
                            session,
                            settings.model_copy(
                                update={
                                    "LLM_PROVIDER": "ollama",
                                    "OLLAMA_MODEL": "fictional-injected-provider-no-live-model",
                                }
                            ),
                            OpportunityFixtureProvider(),
                        ),
                    )

                app.dependency_overrides[application_service] = (
                    fictional_application_service
                )

            async with get_session_factory()() as session:
                profile = await CandidateProfileRepository(
                    session
                ).create_primary_profile(
                    CandidateProfileCreate(
                        full_name="Alex Example",
                        email="alex@example.com",
                        phone="+15550000000",
                        verified_skills=["Python", "FastAPI"],
                        projects=[
                            {
                                "name": "Fictional Relay",
                                "purpose": "A task update service.",
                                "contribution": "I built backend authentication using Python and FastAPI.",
                            }
                        ],
                        preferences={"notice_period_days": 30},
                    )
                )
                session.add(
                    ApplicationAnswerDraft(
                        candidate_profile_id=profile.id,
                        question="Describe a project you built",
                        answer="I built backend authentication using Python and FastAPI.",
                        question_category="project_explanation",
                        writing_style="professional",
                        candidate_profile_version=profile.version,
                        review_status="reviewed",
                        evidence_references=[
                            {
                                "source_type": "verified_project",
                                "source_id": f"{profile.id}:project:0",
                            }
                        ],
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
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=8767 if serve else 0,
                    log_level="warning",
                )
            )
            task = asyncio.create_task(server.serve())
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Local API did not start")
            actual_port = server.servers[0].sockets[0].getsockname()[1]
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{actual_port}",
                timeout=95 if live_ollama_model else 60,
                headers={"Authorization": "Bearer fictional-browser-demo-owner-token"},
                trust_env=False,
            ) as client:
                payload = {
                    "application_url": employer
                    + (
                        "/guided"
                        if steps_demo
                        else "/server-step-one"
                        if navigation_demo
                        else "/opportunity"
                        if opportunity_demo
                        else "/mock/apply"
                        if submission_demo
                        else "/basic"
                    ),
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
                    # A fixed fictional owner action for the dashboard harness.
                    # This route exists only in this subprocess fixture, never in
                    # the normal app. No packet/selector/script input is accepted.
                    from fastapi import Depends, HTTPException

                    from backend.app.browser.router import local_boundary
                    from backend.app.browser.runner import browser
                    from backend.app.core.security import require_api_token

                    @app.post(
                        "/_fictional_test/owner-server-step",
                        dependencies=[
                            Depends(require_api_token),
                            Depends(local_boundary),
                        ],
                    )
                    async def fictional_owner_server_step():
                        runtime = browser.sessions.get(navigation_packet.json()["id"])
                        if (
                            not runtime
                            or not runtime.manual
                            or runtime.page.url != employer + "/server-step-one"
                        ):
                            raise HTTPException(
                                409, "Fictional owner takeover is required"
                            )
                        await runtime.page.locator("[name=name]").fill(
                            "Fictional manual UI owner"
                        )
                        await runtime.page.get_by_role(
                            "button", name="Save and continue"
                        ).click()
                        await runtime.page.wait_for_url("**/server-step-two")
                        await runtime.page.wait_for_function(
                            "window.__aaManual === true"
                        )
                        return {
                            "simulated_owner_action": True,
                            "server_save_count": writes.count("/server-save"),
                        }

                    mock_packet_id = packet["id"] if submission_demo else None
                    if submission_demo:
                        assisted = await client.post(
                            "/api/v1/browser-applications",
                            json={
                                "application_url": employer + "/basic",
                                "company_name": "Example Circuit",
                                "job_title": "Backend Engineer assisted fixture",
                                "idempotency_key": "browser-assisted-001",
                            },
                        )
                        assert assisted.status_code == 200, assisted.text
                        packet = assisted.json()
                    # This fictional URL/packet manifest contains no credentials or personal data.
                    context_packet = await client.post(
                        "/api/v1/browser-applications",
                        json={
                            "application_url": employer + "/opportunity-demo",
                            "company_name": "Example Circuit Context",
                            "job_title": "Backend Engineer context fixture",
                            "idempotency_key": "browser-opportunity-001",
                        },
                    )
                    assert context_packet.status_code == 200, context_packet.text
                    guided_packet = await client.post(
                        "/api/v1/browser-applications",
                        json={
                            "application_url": employer + "/guided",
                            "company_name": "Example Circuit",
                            "job_title": "Backend Engineer guided fixture",
                            "idempotency_key": "browser-guided-001",
                        },
                    )
                    assert guided_packet.status_code == 200, guided_packet.text
                    slow_packet = await client.post(
                        "/api/v1/browser-applications",
                        json={
                            "application_url": employer + "/slow-open",
                            "company_name": "Example Circuit",
                            "job_title": "Backend Engineer slow opening fixture",
                            "idempotency_key": "browser-slow-opening-001",
                        },
                    )
                    assert slow_packet.status_code == 200, slow_packet.text
                    navigation_packet = await client.post(
                        "/api/v1/browser-applications",
                        json={
                            "application_url": employer + "/server-step-one",
                            "company_name": "Example Circuit",
                            "job_title": "Backend Engineer navigation fixture",
                            "idempotency_key": "browser-navigation-001",
                        },
                    )
                    assert navigation_packet.status_code == 200, navigation_packet.text
                    output = ROOT / "reports/browser-mock.private.json"
                    output.parent.mkdir(exist_ok=True)
                    output.write_text(
                        __import__("json").dumps(
                            {
                                "packet_id": packet["id"],
                                "employer_url": employer + "/basic",
                                "mock_packet_id": mock_packet_id,
                                "opportunity_packet_id": context_packet.json()["id"],
                                "guided_packet_id": guided_packet.json()["id"],
                                "slow_packet_id": slow_packet.json()["id"],
                                "navigation_packet_id": navigation_packet.json()["id"],
                            }
                        )
                    )
                    print(
                        "Fictional PostgreSQL browser demo ready on loopback port 8767",
                        flush=True,
                    )
                    await task
                    app.dependency_overrides.pop(application_service, None)
                elif cancellation_demo:
                    from backend.scripts.verify_browser_cancellation import verify

                    await verify(
                        client,
                        packet,
                        settings,
                        writes,
                        employer,
                        after_dispatch=cancellation_demo == "after_dispatch",
                    )
                elif navigation_demo:
                    from backend.scripts.verify_browser_navigation import verify

                    await verify(client, packet, settings, writes)
                elif steps_demo:
                    from backend.scripts.verify_browser_steps import verify

                    await verify(client, packet, settings)
                elif opportunity_demo:
                    from backend.scripts.verify_browser_opportunity import verify

                    await verify(client, packet, settings, live_model=live_ollama_model)
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
                    if submission_demo:
                        await page.locator("[type=checkbox]").check()
                        response = await client.post(
                            route + "/submission-preview",
                            json={
                                "expected_revision": revision,
                                "confirm_page_context": True,
                            },
                        )
                        assert response.status_code == 200, response.text
                        preview = response.json()
                        import json
                        import time

                        from backend.app.browser.owner_approval import approval_header

                        owner_body = {
                            "expected_revision": revision,
                            "preview_digest": preview["preview_digest"],
                            "confirm_exact_application": True,
                            "reviewed_consent_ids": [
                                c["consent_id"]
                                for c in preview["consents"]
                                if c["checked"]
                            ],
                        }
                        raw_body = json.dumps(owner_body).encode()
                        proof = approval_header(
                            settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
                            route + "/authorize-submission",
                            raw_body,
                            nonce=uuid4().hex,
                            timestamp=int(time.time()),
                        )
                        response = await client.post(
                            route + "/authorize-submission",
                            content=raw_body,
                            headers={
                                "Content-Type": "application/json",
                                "X-Browser-Owner-Approval": proof,
                            },
                        )
                        assert response.status_code == 200, response.text
                        grant = response.json()
                        command = {
                            "expected_revision": revision,
                            "grant_id": grant["grant_id"],
                            "grant_token": grant["grant_token"],
                            "idempotency_key": "mock-authorized-dispatch-001",
                        }
                        writes.mode = receipt_mode
                        from uuid import UUID

                        from backend.app.browser.submission_contracts import (
                            SubmitApproved,
                        )
                        from backend.app.browser.submissions import submit

                        async def independent_worker():
                            async with get_session_factory()() as worker_session:
                                outcome = await submit(
                                    worker_session,
                                    UUID(packet["id"]),
                                    SubmitApproved.model_validate(command),
                                )
                                await worker_session.commit()
                                return outcome

                        # No shared Python browser lock: PostgreSQL serializes independent transactions.
                        attempts = await asyncio.gather(
                            independent_worker(), independent_worker()
                        )
                        expected_outcome = (
                            "verified" if receipt_mode == "valid" else "unknown"
                        )
                        assert any(
                            outcome["state"] == expected_outcome for outcome in attempts
                        ), attempts
                        assert attempts[0]["attempt_id"] == attempts[1]["attempt_id"]
                        assert writes == ["/mock/applications"]
                        await browser.close(packet["id"])
                        await close_db_engine()
                        state = (await client.get(route)).json()
                        if receipt_mode != "valid":
                            assert (
                                state["packet"]["lifecycle_state"]
                                == "submission_unknown"
                            )
                            replay = await client.post(route + "/submit", json=command)
                            assert replay.json()["state"] == "unknown"
                            writes.mode = "valid"
                            worker = await asyncio.create_subprocess_exec(
                                sys.executable,
                                str(
                                    ROOT
                                    / "backend/scripts/verify_browser_submission.py"
                                ),
                                "--recover-worker",
                                packet["id"],
                                env={
                                    **os.environ,
                                    "BROWSER_FIXTURE_DATABASE_URL": child,
                                    "BROWSER_FIXTURE_ORIGIN": employer,
                                },
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            output, error = await asyncio.wait_for(
                                worker.communicate(), timeout=30
                            )
                            assert worker.returncode == 0, error.decode()
                            assert json.loads(output)["state"] == "verified", (
                                output.decode()
                            )
                            state = (await client.get(route)).json()
                            assert writes == ["/mock/applications"]
                        assert (
                            state["packet"]["lifecycle_state"]
                            == "provider_confirmed_submitted"
                        )
                        assert (
                            state["execution"]["receipt"]["fixture"]
                            == "automated-apply-employer-v1"
                        )
                        assert state["real_employer_submission_enabled"] is False
                        print(
                            "PASS: PG17 durable owner grant + concurrent one-dispatch admission + actual mock POST + independent receipt + restart persistence; no real employer submission"
                        )
                    else:
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
