"""Owner-authorized in-page transitions, no writes/navigation, and durable no replay."""

import json
import time
from uuid import uuid4

import pytest

from backend.app.browser.owner_approval import approval_header
from backend.app.browser.runner import browser
from backend.app.core.config import get_settings
from backend.tests import test_browser_assistant as fixture

browser_api = fixture.browser_api
create, action = fixture.create, fixture.action
KEY = "fictional-owner-step-approval-separate-key"  # pragma: allowlist secret — fictional fixture only


def permission(monkeypatch):
    monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", KEY)
    get_settings.cache_clear()


def test_owner_step_signing_key_cannot_be_the_delegated_bearer():
    from pydantic import ValidationError

    from backend.app.core.config import Settings

    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            _env_file=None, JOB_AGENT_API_TOKEN=KEY, BROWSER_OWNER_APPROVAL_KEY=KEY
        )


async def preview(client, state):
    return await client.post(
        f"/api/v1/browser-applications/{state['packet']['id']}/step-preview",
        json={"expected_revision": state["packet"]["revision"]},
    )


async def advance(client, state, view, key="fictional-step-request-001", signed=True):
    path = f"/api/v1/browser-applications/{state['packet']['id']}/advance-step"
    raw = json.dumps(
        {
            "expected_revision": view["expected_revision"],
            "preview_digest": view["preview_digest"],
            "idempotency_key": key,
            "confirm_values_and_consents": True,
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Browser-Owner-Approval"] = approval_header(
            KEY, path, raw, nonce=uuid4().hex, timestamp=int(time.time())
        )
    return await client.post(path, content=raw, headers=headers)


@pytest.mark.asyncio
async def test_reviewed_in_page_next_requires_owner_and_never_repeats(
    browser_api, monkeypatch
):
    client, base, writes, session = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/steps")
    state = (await action(client, state, "analyze")).json()
    incomplete = (await preview(client, state)).json()
    assert not incomplete["complete"]
    assert (await advance(client, state, incomplete, signed=False)).status_code == 403
    assert (await advance(client, state, incomplete)).status_code == 409
    state = (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).json()
    view = (await preview(client, state)).json()
    assert view["complete"] and view["label"] == "Next step"
    assert view["values"][0]["value"] == "Alex Example"
    moved = await advance(client, state, view)
    assert moved.status_code == 200, moved.text
    next_state = moved.json()
    assert next_state["analysis"]["diagnostic"] == "next_step_analyzed"
    assert next_state["analysis"]["fields"][0]["question"] == "Email"
    assert next_state["packet"]["revision"] == state["packet"]["revision"] + 1
    again = await advance(client, state, view)
    assert again.status_code == 200
    assert again.json()["packet"]["revision"] == next_state["packet"]["revision"]
    assert len(again.json()["analysis"]["step_history"]) == 1
    assert writes == []


@pytest.mark.asyncio
async def test_step_review_binds_actual_values_and_never_clicks_submit(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/steps")
    state = (await action(client, state, "analyze")).json()
    state = (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).json()
    view = (await preview(client, state)).json()
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.locator("input").fill("Changed after review")
    assert (await advance(client, state, view)).status_code == 409
    await runtime.page.get_by_text("Next step").evaluate("e => e.type='submit'")
    assert (await preview(client, state)).status_code == 409
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/steps-post", "/steps-submit", "/steps-get"])
async def test_step_network_save_is_blocked_and_hands_off_without_retry(
    browser_api, monkeypatch, path
):
    client, base, writes, _ = browser_api
    permission(monkeypatch)
    state = await create(client, base, path)
    state = (await action(client, state, "analyze")).json()
    state = (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).json()
    view = (await preview(client, state)).json()
    result = await advance(client, state, view)
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["analysis"]["diagnostic"] == "step_handoff_required"
    assert "never replay" in state["recovery"]
    again = await advance(client, state, view)
    assert again.status_code == 200
    runtime = browser.sessions[state["packet"]["id"]]
    if path == "/steps-post":
        assert runtime.blocked_mutations == 1
    elif path == "/steps-submit":
        assert await runtime.page.evaluate("window.__aaSubmissionBlocks") == 1
    else:
        assert runtime.blocked_step_requests == 1
        assert not any(path.startswith("/save-draft") for path in writes.reads)
    assert writes == []


@pytest.mark.asyncio
async def test_interrupted_step_after_intent_is_not_replayed_on_reconnect(
    browser_api, monkeypatch
):
    from backend.app.browser.service import metadata

    client, base, writes, session = browser_api
    permission(monkeypatch)
    state = await create(client, base, "/steps")
    state = (await action(client, state, "analyze")).json()
    state = (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).json()
    view = (await preview(client, state)).json()
    saved = await metadata(session, state["packet"]["id"])
    saved.value = {
        **saved.value,
        "diagnostic": "step_started",
        "step_history": [
            {
                "key": "fictional-step-request-001",
                "digest": view["preview_digest"],
                "outcome": "started",
            }
        ],
    }
    await session.commit()
    await browser.close(state["packet"]["id"])
    result = await advance(client, state, view)
    assert result.status_code == 200
    assert result.json()["analysis"]["diagnostic"] == "step_started"
    assert not result.json()["connected"]
    assert writes == []


def test_opaque_step_handles_reject_selector_fragments():
    from pydantic import ValidationError

    from backend.app.browser.contracts import StepControl

    with pytest.raises(ValidationError):
        StepControl(key='x"] button[type="submit', label="Next", supported=True)
