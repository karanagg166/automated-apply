"""Actual PG17/TCP/FastAPI/Chromium interruption and durable no-resubmission proof."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(client, packet, settings, writes, employer, *, after_dispatch=False):
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    route = "/api/v1/browser-applications/" + packet["id"]

    async def signed(path, body):
        raw = json.dumps(body).encode()
        return await client.post(
            path,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Browser-Owner-Approval": approval_header(
                    settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
                    path,
                    raw,
                    nonce=uuid4().hex,
                    timestamp=int(time.time()),
                ),
            },
        )

    # Legacy answer routes allow delayed request teardown. Packet/browser routes
    # now finish their function-scoped transaction before sending the response.
    # Both paths must make acknowledged writes visible to an independent GET.
    from backend.app.api.v1.application_answers import answer_service
    from backend.app.db.session import get_db_session, get_session_factory
    from backend.app.main import app
    from backend.app.services.application_answer_service import ApplicationAnswerService
    from backend.tests.phase2a_fakes import FakeProvider

    releases = {
        name: asyncio.Event()
        for name in (
            "approve-reuse",
            "revoke-reuse",
            "browser-applications",
            "generate",
        )
    }
    reached = {name: asyncio.Event() for name in releases}

    async def delayed_teardown(request: Request):
        async with get_session_factory()() as session:
            try:
                yield session
                action = request.url.path.rsplit("/", 1)[-1]
                if action in releases:
                    reached[action].set()
                    if action != "browser-applications":
                        await releases[action].wait()
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = delayed_teardown

    def fictional_answer_service(session=Depends(get_db_session)):
        return ApplicationAnswerService(
            session,
            settings.model_copy(
                update={
                    "LLM_PROVIDER": "ollama",
                    "OLLAMA_ENABLED": True,
                    "OLLAMA_MODEL": "fictional-fixture-provider",
                }
            ),
            FakeProvider(),
        )

    app.dependency_overrides[answer_service] = fictional_answer_service
    try:
        drafts = (await client.get("/api/v1/application-answers/drafts")).json()
        draft = next(
            d for d in drafts if d["question"] == "Describe a project you built"
        )
        target = "/api/v1/application-answers/drafts/" + draft["id"]
        response = await signed(
            target + "/approve-reuse",
            {
                "expected_profile_version": 1,
                "scope": "general_profile",
                "confirm_reviewed_answer": True,
            },
        )
        assert response.status_code == 200, response.text
        await asyncio.wait_for(reached["approve-reuse"].wait(), 3)
        bank = (await client.get("/api/v1/application-answers/reuse-approvals")).json()
        assert bank["approvals"][draft["id"]]["approved"], bank
        response = await client.post(target + "/revoke-reuse")
        assert response.status_code == 200, response.text
        await asyncio.wait_for(reached["revoke-reuse"].wait(), 3)
        bank = (await client.get("/api/v1/application-answers/reuse-approvals")).json()
        assert not bank["approvals"][draft["id"]]["approved"], bank
        prepared = await client.post(
            "/api/v1/browser-applications",
            json={
                "application_url": employer + "/basic",
                "company_name": "Example Circuit",
                "job_title": "Backend Engineer acknowledged prepare fixture",
                "idempotency_key": "acknowledged-browser-prepare-001",
            },
        )
        assert prepared.status_code == 200, prepared.text
        await asyncio.wait_for(reached["browser-applications"].wait(), 3)
        visible = await client.get(
            "/api/v1/browser-applications/" + prepared.json()["id"]
        )
        assert visible.status_code == 200, visible.text
        generated = await client.post(
            "/api/v1/application-answers/generate",
            json={
                "question": "Describe a project you built",
                "save_draft": True,
            },
        )
        assert (
            generated.status_code == 200 and generated.json()["status"] == "draft_ready"
        ), generated.text
        await asyncio.wait_for(reached["generate"].wait(), 3)
        from backend.app.models.application_answer import ApplicationAnswerDraft

        async with get_session_factory()() as observer:
            assert (
                await observer.get(
                    ApplicationAnswerDraft, UUID(generated.json()["draft_id"])
                )
                is not None
            )
    finally:
        for event in releases.values():
            event.set()
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(answer_service, None)

    async def open_analyze():
        current = (await client.get(route)).json()["packet"]
        response = await client.post(
            route + "/open",
            json={
                "expected_revision": current["revision"],
                "approve_dedicated_profile": True,
                "confirm_destination_permission": True,
            },
        )
        assert response.status_code == 200, response.text
        response = await client.post(
            route + "/actions",
            json={
                "action": "analyze",
                "expected_revision": current["revision"],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def interrupt(target, pending, *, via_cli=False):
        started = time.monotonic()
        response = await client.get(target + "/operation")
        assert response.status_code == 200, response.text
        control = response.json()
        active = control["active_operation"]
        assert active and time.monotonic() - started < 3, control
        revision = active["expected_revision"] or control["packet_revision"]
        bad = await client.post(
            target + "/actions",
            json={
                "action": "cancel",
                "expected_revision": revision,
                "operation_id": str(uuid4()),
            },
        )
        assert bad.status_code == 409
        if via_cli:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(ROOT / "backend/scripts/browser_assistant.py"),
                "cancel_application",
                "--packet-id",
                target.rsplit("/", 1)[1],
                "--revision",
                str(revision),
                "--origin",
                str(client.base_url).rstrip("/"),
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "JOB_AGENT_API_TOKEN": settings.JOB_AGENT_API_TOKEN.get_secret_value(),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, error = await asyncio.wait_for(process.communicate(), 15)
            assert process.returncode == 0, error.decode() + output.decode()
            assert json.loads(output)["ok"]
        else:
            response = await client.post(
                target + "/actions",
                json={
                    "action": "cancel",
                    "expected_revision": revision,
                    "operation_id": active["id"],
                },
            )
            assert response.status_code == 200, response.text
        response = await asyncio.wait_for(pending, 5)
        assert response.status_code == 409 and "cancelled" in response.text, (
            response.text
        )
        state = (await client.get(target)).json()
        assert not state["connected"] and not state["active_operation"]
        assert not state["cancellation_pending"]
        return state

    # Hold a real Playwright evaluate call after fill intent has committed.
    state = await open_analyze()
    runtime = browser.sessions[packet["id"]]
    entered = asyncio.Event()

    async def paused_fill(*args, **kwargs):
        entered.set()
        await runtime.page.evaluate("() => new Promise(() => {})")

    runtime.fill = paused_fill
    pending = asyncio.create_task(
        client.post(
            route + "/actions",
            json={
                "action": "fill",
                "expected_revision": state["packet"]["revision"],
                "confirm_reviewed_values": True,
                "confirm_page_context": True,
            },
        )
    )
    await asyncio.wait_for(entered.wait(), 10)
    state = await interrupt(route, pending)
    assert state["analysis"]["diagnostic"] == "cancelled"
    assert state["packet"]["tracking_state"] == "not_applied" and writes == []

    # Reopen explicitly, then interrupt after the mock dispatch intent is durable.
    state = await open_analyze()
    response = await client.post(
        route + "/actions",
        json={
            "action": "fill",
            "expected_revision": state["packet"]["revision"],
            "confirm_reviewed_values": True,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    state = response.json()
    checkbox = next(f for f in state["analysis"]["fields"] if f["kind"] == "checkbox")
    response = await signed(
        route + "/consent",
        {
            "expected_revision": state["packet"]["revision"],
            "field_id": checkbox["field_id"],
            "checked": True,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    revision = response.json()["packet"]["revision"]
    response = await client.post(
        route + "/submission-preview",
        json={
            "expected_revision": revision,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    view = response.json()
    grant_teardown = asyncio.Event()

    async def delayed_authorization_teardown(request: Request):
        async with get_session_factory()() as session:
            try:
                yield session
                if request.url.path.endswith("/authorize-submission"):
                    grant_teardown.set()
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = delayed_authorization_teardown
    try:
        response = await signed(
            route + "/authorize-submission",
            {
                "expected_revision": revision,
                "preview_digest": view["preview_digest"],
                "confirm_exact_application": True,
                "reviewed_consent_ids": [
                    c["consent_id"] for c in view["consents"] if c["checked"]
                ],
            },
        )
        assert response.status_code == 200, response.text
        grant = response.json()
        await asyncio.wait_for(grant_teardown.wait(), 3)
        from backend.app.browser.submission_models import BrowserSubmissionGrant

        async with get_session_factory()() as observer:
            assert (
                await observer.get(BrowserSubmissionGrant, UUID(grant["grant_id"]))
                is not None
            )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
    command = {
        "expected_revision": revision,
        "grant_id": grant["grant_id"],
        "grant_token": grant["grant_token"],
        "idempotency_key": "cancelled-dispatch-001",
    }
    runtime = browser.sessions[packet["id"]]
    entered = asyncio.Event()

    async def paused_submit(*args):
        if after_dispatch:
            await original_submit(*args)
        entered.set()
        await runtime.page.evaluate("() => new Promise(() => {})")

    original_submit = runtime.submit_mock
    runtime.submit_mock = paused_submit
    pending = asyncio.create_task(client.post(route + "/submit", json=command))
    await asyncio.wait_for(entered.wait(), 10)
    state = await interrupt(route, pending, via_cli=True)
    assert state["packet"]["lifecycle_state"] == "submission_unknown"
    expected_writes = ["/mock/applications"] if after_dispatch else []
    assert state["execution"]["state"] == "unknown" and writes == expected_writes
    replay = await client.post(route + "/submit", json=command)
    assert replay.status_code == 200 and replay.json()["state"] == "unknown", (
        replay.text
    )
    await close_db_engine()
    state = (await client.get(route)).json()
    assert state["execution"]["state"] == "unknown" and writes == expected_writes
    if after_dispatch:
        recovered = await client.post(route + "/recover-submission")
        assert (
            recovered.status_code == 200 and recovered.json()["state"] == "verified"
        ), recovered.text
        state = (await client.get(route)).json()
        closed = await client.post(
            route + "/actions",
            json={"action": "cancel", "expected_revision": state["packet"]["revision"]},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["execution"]["state"] == "verified"
        assert closed.json()["packet"]["tracking_state"] == "applied_verified"
        assert writes == expected_writes

    # Cancellation must also interrupt navigation before open has registered a session.
    created = await client.post(
        "/api/v1/browser-applications",
        json={
            "application_url": employer + "/slow-open",
            "company_name": "Example Circuit",
            "job_title": "Backend Engineer slow opening fixture",
            "idempotency_key": "cancel-open-001",
        },
    )
    assert created.status_code == 200, created.text
    other = created.json()
    target = "/api/v1/browser-applications/" + other["id"]
    pending = asyncio.create_task(
        client.post(
            target + "/open",
            json={
                "expected_revision": other["revision"],
                "approve_dedicated_profile": True,
                "confirm_destination_permission": True,
            },
        )
    )
    try:
        assert await asyncio.to_thread(writes.slow_started.wait, 15)
        await interrupt(target, pending)
        assert (
            other["id"] not in browser.opening and other["id"] not in browser.sessions
        )
    finally:
        writes.slow_release.set()
    print(
        "PASS: PG17 + TCP FastAPI + Chromium cancellation of fill, durable dispatch and opening; CLI orchestration, unknown outcome persistence and no replay",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-dispatch", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            os.environ["PROFILE_TEST_DATABASE_URL"],
            submission_demo=True,
            cancellation_demo="after_dispatch"
            if args.after_dispatch
            else "before_dispatch",
        )
    )
