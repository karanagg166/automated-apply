"""Real Chromium against fictional loopback forms and the actual FastAPI application."""

import hashlib
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from backend.app.browser.runner import browser, origin, validate_destination
from backend.app.browser.service import metadata
from backend.app.core.config import Settings, get_settings
from backend.app.dashboard.models import PrivateResume
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.models.application_answer import CandidateResource
from backend.tests.browser_employers import employer_site


@pytest_asyncio.fixture
async def browser_api(db_session, phase2_profile, phase2_auth, monkeypatch, tmp_path):
    with employer_site() as (base, writes):
        monkeypatch.setenv("BROWSER_ASSISTANT_ENABLED", "true")
        monkeypatch.setenv("BROWSER_ALLOWED_ORIGINS", '["' + origin(base) + '"]')
        monkeypatch.setenv("BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
        monkeypatch.setenv("BROWSER_CHANNEL", "chromium")
        monkeypatch.setenv("BROWSER_HEADLESS", "true")
        monkeypatch.setenv("RESUME_ENCRYPTION_KEY", Fernet.generate_key().decode())
        get_settings.cache_clear()

        async def dependency():
            yield db_session
            await db_session.commit()

        app.dependency_overrides[get_db_session] = dependency
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=phase2_auth,
        ) as client:
            yield client, base, writes, db_session
        for key in list(browser.sessions):
            await browser.close(key)
        browser.locks.clear()
        app.dependency_overrides.pop(get_db_session, None)
        get_settings.cache_clear()


async def create(client, base, path="/basic"):
    response = await client.post(
        "/api/v1/browser-applications",
        json={
            "application_url": base + path,
            "company_name": "Example Circuit",
            "job_title": "Backend Engineer",
            "idempotency_key": "browser-test-key-01",
        },
    )
    assert response.status_code == 200, response.text
    packet = response.json()
    response = await client.post(
        f"/api/v1/browser-applications/{packet['id']}/open",
        json={
            "expected_revision": packet["revision"],
            "executor": "isolated_browser",
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def action(client, state, verb, **kwargs):
    response = await client.post(
        f"/api/v1/browser-applications/{state['packet']['id']}/actions",
        json={
            "action": verb,
            "expected_revision": state["packet"]["revision"],
            **kwargs,
        },
    )
    return response


@pytest.mark.asyncio
async def test_real_form_factual_fill_resume_consent_and_tracking(
    browser_api, phase2_profile
):
    client, base, writes, session = browser_api
    # Exact approved resource -> encrypted PDF bytes, with digest verification.
    resume_id = uuid4()
    resource = CandidateResource(
        candidate_profile_id=phase2_profile.id,
        resource_type="resume",
        label="Approved PDF",
        url="private-resume:" + str(resume_id),
        source_type="private_upload",
        user_confirmed=True,
        is_primary=True,
    )
    session.add(resource)
    await session.flush()
    raw = b"%PDF-1.4\nfictional-test-content"
    key = get_settings().RESUME_ENCRYPTION_KEY.get_secret_value().encode()
    session.add(
        PrivateResume(
            id=resume_id,
            label="Approved PDF",
            resource_id=resource.id,
            confirmed=True,
            ciphertext=Fernet(key).encrypt(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    )
    await session.commit()
    state = await create(client, base)
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    assert len(state["analysis"]["fields"]) == 6
    assert not state["analysis"]["fields"][-1]["supported"]
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    filled = response.json()
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("[name=name]").input_value() == "Alex Example"
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    assert await runtime.page.locator("[name=notice]").input_value() == "30 days"
    assert await runtime.page.locator("[name=ctc]").input_value() == ""
    assert not await runtime.page.locator("[type=checkbox]").is_checked()
    assert (
        await runtime.page.locator("[type=file]").evaluate("(e)=>e.files[0].name")
        == "resume.pdf"
    )
    assert filled["analysis"]["diagnostic"] == "filled_review_on_website"
    assert not filled["automated_submission_enabled"]
    assert filled["packet"]["tracking_state"] == "not_applied"
    await runtime.page.locator("[type=submit]").click()
    assert writes == []
    assert (await action(client, filled, "submit")).status_code == 403
    # Explicit handoff permits a real manual action but does not fabricate submission evidence.
    assert (await action(client, filled, "take_over")).status_code == 200
    assert (
        await action(
            client,
            filled,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).status_code == 409
    assert (await action(client, filled, "cancel")).status_code == 200
    status = await client.get(f"/api/v1/browser-applications/{state['packet']['id']}")
    assert not status.json()["connected"]
    assert status.json()["packet"]["tracking_state"] == "not_applied"


@pytest.mark.asyncio
async def test_dynamic_fields_stop_before_filling_changed_form(browser_api):
    client, base, writes, _ = browser_api
    state = await create(client, base, "/dynamic")
    state = (await action(client, state, "analyze")).json()
    result = (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).json()
    assert result["analysis"]["diagnostic"] == "interrupted_reanalyze_before_retry"
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("[name=email]").input_value() == ""
    again = await action(client, result, "analyze")
    assert len(again.json()["analysis"]["fields"]) == 3
    assert writes == []


@pytest.mark.asyncio
async def test_multistep_requires_owner_navigation_then_reanalysis(browser_api):
    client, base, _, _ = browser_api
    state = await create(client, base, "/steps")
    state = (await action(client, state, "analyze")).json()
    assert len(state["analysis"]["fields"]) == 1
    assert (await action(client, state, "take_over")).status_code == 200
    await browser.sessions[state["packet"]["id"]].page.get_by_text("Next step").click()
    next_state = (await action(client, state, "analyze")).json()
    assert next_state["analysis"]["fields"][0]["question"] == "Email"
    assert not next_state["manual"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/captcha", "/controls"])
async def test_captcha_and_authentication_require_handoff(browser_api, path):
    client, base, _, _ = browser_api
    state = await create(client, base, path)
    response = await action(client, state, "analyze")
    assert response.status_code == 409
    assert "authentication" in response.text


@pytest.mark.asyncio
async def test_page_injection_and_input_event_cannot_issue_posts(browser_api):
    client, base, writes, _ = browser_api
    state = await create(client, base, "/malicious")
    state = (await action(client, state, "analyze")).json()
    result = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert result.status_code == 200
    assert writes == []
    assert result.json()["packet"]["tracking_state"] == "not_applied"


@pytest.mark.asyncio
async def test_false_success_text_never_becomes_receipt(browser_api):
    client, base, _, _ = browser_api
    state = await create(client, base, "/false-success")
    state = (await action(client, state, "analyze")).json()
    assert state["packet"]["lifecycle_state"] != "provider_confirmed_submitted"
    assert state["packet"]["tracking_state"] == "not_applied"


@pytest.mark.asyncio
async def test_disconnect_restart_cancellation_and_replay(browser_api):
    client, base, _, session = browser_api
    state = await create(client, base)
    state = (await action(client, state, "analyze")).json()
    signature = state["analysis"]["signature"]
    # Analysis metadata survives browser death; no pending browser action is replayed.
    await browser.close(state["packet"]["id"])
    assert (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).status_code == 409
    saved = await metadata(session, state["packet"]["id"])
    assert saved.value["signature"] == signature
    status = await client.get(f"/api/v1/browser-applications/{state['packet']['id']}")
    assert "Nothing" not in status.json()["recovery"]
    assert not status.json()["connected"]
    assert (await action(client, state, "cancel")).status_code == 200


@pytest.mark.asyncio
async def test_owner_auth_expiry_permission_revision_and_csrf_boundaries(browser_api):
    client, base, _, _ = browser_api
    state = await create(client, base)
    path = f"/api/v1/browser-applications/{state['packet']['id']}"
    assert (
        await client.get(path, headers={"Authorization": "Bearer expired"})
    ).status_code == 401
    assert (
        await client.get(path, headers={"Origin": "https://evil.invalid"})
    ).status_code == 403
    response = await client.post(
        path + "/open",
        json={
            "expected_revision": 1,
            "executor": "isolated_browser",
            "approve_dedicated_profile": False,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 422
    response = await action(client, state, "fill")
    assert response.status_code == 422
    response = await client.post(
        path + "/actions", json={"action": "analyze", "expected_revision": 999}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_preparation_is_idempotent_and_context_conflicts(browser_api):
    client, base, _, _ = browser_api
    payload = {
        "application_url": base + "/basic",
        "company_name": "Example Circuit",
        "job_title": "Backend Engineer",
        "idempotency_key": "browser-test-key-01",
    }
    first = await client.post("/api/v1/browser-applications", json=payload)
    second = await client.post("/api/v1/browser-applications", json=payload)
    assert first.json()["id"] == second.json()["id"]
    payload["company_name"] = "Wrong Company"
    assert (
        await client.post("/api/v1/browser-applications", json=payload)
    ).status_code == 409


@pytest.mark.asyncio
async def test_url_permissions_and_private_network_are_fail_closed():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        BROWSER_ALLOWED_ORIGINS=["https://127.0.0.1:443"],
    )
    with pytest.raises(Exception) as error:
        await validate_destination("https://127.0.0.1/careers", settings)
    assert error.value.status_code == 403
    with pytest.raises(Exception):
        await validate_destination("http://user:password@127.0.0.1/form", settings) # pragma: allowlist secret — fictional local test value
    with pytest.raises(Exception):
        await validate_destination("https://not-approved.example/form", settings)


@pytest.mark.asyncio
async def test_native_dropdown_date_and_custom_controls(browser_api):
    client, base, writes, _ = browser_api
    state = await create(client, base, "/supported-controls")
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    assert any(
        f["kind"] == "combobox" and not f["supported"]
        for f in state["analysis"]["fields"]
    )
    reviewed_ids = []
    for kind, value in [("select", "Engineering"), ("date", "2026-11-01")]:
        field = next(f for f in state["analysis"]["fields"] if f["kind"] == kind)
        path = f"/api/v1/application-packets/{state['packet']['id']}/questions/{field['field_id']}"
        edit = await client.patch(
            path,
            json={"expected_revision": state["packet"]["revision"], "answer": value},
        )
        assert edit.status_code == 200, edit.text
        state["packet"] = edit.json()
        reviewed_ids.append(field["field_id"])
    reviewed = await client.post(
        f"/api/v1/application-packets/{state['packet']['id']}/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": reviewed_ids,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    state["packet"] = reviewed.json()
    filled = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert filled.status_code == 200, filled.text
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("select").input_value() == "Engineering"
    assert await runtime.page.locator("[type=date]").input_value() == "2026-11-01"
    assert not await runtime.page.locator("[type=radio]").is_checked()
    assert writes == []


@pytest.mark.asyncio
async def test_upload_accept_and_exact_company_page_confirmation(browser_api):
    client, base, _, _ = browser_api
    state = await create(client, base, "/wrong-file")
    state = (await action(client, state, "analyze")).json()
    assert not state["analysis"]["fields"][0]["supported"]
    response = await action(client, state, "fill", confirm_reviewed_values=True)
    assert response.status_code == 422
    assert "company and job" in response.text


@pytest.mark.asyncio
async def test_unknown_profile_directory_and_unrelated_navigation_are_rejected(
    browser_api, tmp_path, monkeypatch
):
    client, base, _, _ = browser_api
    state = await create(client, base)
    state = (await action(client, state, "analyze")).json()
    assert (await action(client, state, "take_over")).status_code == 200
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.goto(base + "/false-success")
    assert (await action(client, state, "analyze")).status_code == 409
    await browser.close(state["packet"]["id"])
    existing = tmp_path / "personal-profile"
    existing.mkdir()
    (existing / "Cookies").write_text("fictional-personal-cookie-marker")
    monkeypatch.setenv("BROWSER_PROFILE_ROOT", str(existing))
    get_settings.cache_clear()
    response = await client.post(
        f"/api/v1/browser-applications/{state['packet']['id']}/open",
        json={
            "expected_revision": state["packet"]["revision"],
            "executor": "isolated_browser",
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 422
    assert (existing / "Cookies").read_text() == "fictional-personal-cookie-marker"
