"""Real browser manual server steps and signed resumption; no automated navigation."""

import asyncio
import json
import time
from uuid import UUID, uuid4

import pytest

from backend.app.browser.owner_approval import approval_header
from backend.app.browser.runner import BrowserSession, browser
from backend.app.core.config import get_settings
from backend.tests import test_browser_assistant as fixture

browser_api = fixture.browser_api
create, action = fixture.create, fixture.action
KEY = "fictional-owner-navigation-separate-key"  # pragma: allowlist secret — fictional only


def permission(monkeypatch):
    monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", KEY)
    get_settings.cache_clear()


async def preview(client, state):
    return await client.post(
        f"/api/v1/browser-applications/{state['packet']['id']}/page-preview",
        json={"expected_revision": state["packet"]["revision"]},
    )


async def resume(client, state, view, *, signed=True, confirmed=True):
    path = f"/api/v1/browser-applications/{state['packet']['id']}/resume-page"
    raw = json.dumps(
        {
            "expected_revision": view["expected_revision"],
            "capture_digest": view["capture_digest"],
            "confirm_same_application": confirmed,
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Browser-Owner-Approval"] = approval_header(
            KEY, path, raw, nonce=uuid4().hex, timestamp=int(time.time())
        )
    return await client.post(path, content=raw, headers=headers)


async def manual_step(client, state):
    runtime = browser.sessions[state["packet"]["id"]]
    assert (await action(client, state, "take_over")).status_code == 200
    await runtime.page.locator("[name=name]").fill("Owner-entered fictional name")
    await runtime.page.get_by_role("button", name="Save and continue").click()
    await runtime.page.wait_for_url("**/server-step-two")
    await runtime.page.wait_for_function("window.__aaManual === true")
    return runtime


@pytest.mark.asyncio
async def test_manual_server_navigation_signed_review_fill_and_durable_history(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    state = (await action(client, state, "analyze")).json()
    runtime = await manual_step(client, state)
    assert writes == ["/server-save"]  # Only the explicit manual save.
    assert (await action(client, state, "analyze")).status_code == 409
    view = (await preview(client, state)).json()
    assert view["questions"][0]["question"] == "Email"
    assert not runtime.manual and runtime.in_page_mode
    assert await runtime.page.evaluate("window.__aaManual") is False
    assert (await resume(client, state, view, signed=False)).status_code == 403
    assert (await resume(client, state, view, confirmed=False)).status_code == 422
    assert (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).status_code == 409
    response = await resume(client, state, view)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["analysis"]["diagnostic"] == "owner_page_resumed"
    assert not state["page_review_required"]
    assert (
        state["packet"]["snapshot"]["destination"]["application_url"]
        == base + "/server-step-one"
    )
    assert state["packet"]["tracking_state"] == "not_applied"
    filled = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert filled.status_code == 200, filled.text
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    await runtime.page.get_by_role("button", name="Submit application").click()
    assert writes == ["/server-save"]
    assert (
        await resume(client, state, view)
    ).status_code == 409  # Lost acknowledgment cannot replay.
    await browser.close(state["packet"]["id"])
    saved = (
        await client.get(f"/api/v1/browser-applications/{state['packet']['id']}")
    ).json()
    assert len(saved["analysis"]["navigation_history"]) == 1
    assert saved["analysis"]["navigation_history"][0]["outcome"] == "owner_page_resumed"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["form", "url", "reload"])
async def test_page_review_rejects_changed_form_url_or_same_url_document(
    browser_api, monkeypatch, change
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    runtime = await manual_step(client, state)
    view = (await preview(client, state)).json()
    if change == "form":
        await runtime.page.locator("form").evaluate(
            "e => e.insertAdjacentHTML('beforeend','<label>New required answer<input required></label>')"
        )
    elif change == "url":
        await runtime.page.evaluate(
            "history.pushState({}, '', '/server-step-two?another=step')"
        )
    else:
        # Only a renewed explicit takeover can permit the reload request.
        await action(client, state, "take_over")
        await runtime.page.reload()
        await runtime.page.wait_for_function("window.__aaManual === true")
    result = await resume(client, state, view)
    assert result.status_code == 409, result.text
    assert writes == ["/server-save"]
    assert runtime.url == base + "/server-step-one"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/server-step-wrong", "/captcha", "/false-success"])
async def test_wrong_application_challenge_or_success_text_is_not_resumed(
    browser_api, monkeypatch, path
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    runtime = browser.sessions[state["packet"]["id"]]
    await action(client, state, "take_over")
    await runtime.page.goto(base + path)
    result = await preview(client, state)
    assert result.status_code == 409, result.text
    assert runtime.url == base + "/server-step-one"
    assert writes == []


@pytest.mark.asyncio
async def test_same_url_manual_reload_requires_review_and_preview_is_network_isolated(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    runtime = browser.sessions[state["packet"]["id"]]
    assert (await preview(client, state)).status_code == 409
    await action(client, state, "take_over")
    await runtime.page.reload()
    await runtime.page.wait_for_function("window.__aaManual === true")
    assert (await action(client, state, "analyze")).status_code == 409
    view = (await preview(client, state)).json()
    await runtime.page.evaluate("fetch('/save-draft?private=fixture').catch(()=>{})")
    assert "/save-draft?private=fixture" not in writes.reads
    assert writes == []
    assert (await resume(client, state, view)).status_code == 200
    await runtime.page.get_by_role("button", name="Save and continue").click()
    assert writes == []  # Guard survives same-URL resumption.


@pytest.mark.asyncio
async def test_cross_origin_page_cannot_be_adopted(browser_api, monkeypatch):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    runtime = browser.sessions[state["packet"]["id"]]
    await action(client, state, "take_over")
    # about:blank sends no external request; it still must never become a destination.
    await runtime.page.goto("about:blank")
    result = await preview(client, state)
    assert result.status_code in {403, 422}
    assert writes == []


@pytest.mark.asyncio
async def test_late_owner_mode_reply_cannot_undo_a_review_pause(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    pending, release = asyncio.Event(), asyncio.Event()
    original = BrowserSession.owner_mode

    async def delayed(self, source):
        state = original(self, source)
        if source["frame"].url.endswith("/server-step-two") and state["manual"]:
            pending.set()
            await release.wait()
        return state

    monkeypatch.setattr(BrowserSession, "owner_mode", delayed)
    state = await create(client, base, "/server-step-one")
    runtime = browser.sessions[state["packet"]["id"]]
    try:
        await action(client, state, "take_over")
        await runtime.page.locator("[name=name]").fill("Fictional owner")
        await runtime.page.get_by_role("button", name="Save and continue").click()
        await runtime.page.wait_for_url("**/server-step-two")
        await asyncio.wait_for(pending.wait(), timeout=5)
        assert (await preview(client, state)).status_code == 200
        release.set()
        # Deliver the older binding reply and its browser microtask.
        await runtime.page.wait_for_timeout(100)
        assert await runtime.page.evaluate("window.__aaManual") is False
        await runtime.page.locator("[name=email]").fill("fictional@example.org")
        await runtime.page.get_by_role("button", name="Submit application").click()
        assert writes == ["/server-save"]
    finally:
        release.set()


@pytest.mark.asyncio
async def test_preview_from_a_closed_browser_cannot_authorize_a_reopened_document(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    await action(client, state, "take_over")
    view = (await preview(client, state)).json()
    await browser.close(state["packet"]["id"])
    route = f"/api/v1/browser-applications/{state['packet']['id']}"
    opened = await client.post(
        route + "/open",
        json={
            "expected_revision": state["packet"]["revision"],
            "executor": "isolated_browser",
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert opened.status_code == 200, opened.text
    await action(client, state, "take_over")
    assert (await resume(client, state, view)).status_code == 409
    assert writes == []


@pytest.mark.asyncio
async def test_interrupted_analysis_restores_the_review_pause(browser_api, monkeypatch):
    from backend.app.browser import navigation

    client, base, writes, session = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/server-step-one")
    runtime = await manual_step(client, state)
    view = (await preview(client, state)).json()

    async def interrupted(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(navigation, "analyze", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await navigation.resume(
            session,
            UUID(state["packet"]["id"]),
            navigation.ResumePage(
                expected_revision=view["expected_revision"],
                capture_digest=view["capture_digest"],
                confirm_same_application=True,
            ),
        )
    assert runtime.url == base + "/server-step-one"
    assert runtime.paused_for_resume and not runtime.manual
    assert writes == ["/server-save"]
