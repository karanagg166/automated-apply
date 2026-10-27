"""Real native/ARIA choices, exact options, dynamic changes and consent boundaries."""

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


@pytest.mark.asyncio
async def test_native_and_aria_radio_groups_and_custom_dropdown_fill(browser_api):
    client, base, writes, _ = browser_api
    state = await create(client, base, "/choices")
    await browser.sessions[state["packet"]["id"]].scan()
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    fields = state["analysis"]["fields"]
    assert len(fields) == 4
    assert sum(f["kind"] == "radio_group" and f["supported"] for f in fields) == 2
    assert next(f for f in fields if f["kind"] == "combobox")["supported"]
    assert not next(f for f in fields if "agree" in f["question"])["supported"]
    runtime = browser.sessions[state["packet"]["id"]]
    for question, expected in [
        ("Remote work preference", "remote"),
        ("Department", "Engineering"),
        ("Preferred city", "Pune"),
    ]:
        field = next(f for f in fields if f["question"] == question)
        response = await client.patch(
            f"/api/v1/application-packets/{state['packet']['id']}/questions/{field['field_id']}",
            json={"expected_revision": state["packet"]["revision"], "answer": expected},
        )
        assert response.status_code == 200, response.text
        state["packet"] = response.json()
    reviewed = await client.post(
        f"/api/v1/application-packets/{state['packet']['id']}/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": [f["field_id"] for f in fields if f["supported"]],
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    state["packet"] = reviewed.json()
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await runtime.page.locator("#remote").is_checked()
    assert (
        await runtime.page.locator("#engineering").get_attribute("aria-checked")
        == "true"
    )
    assert await runtime.page.locator("#city").input_value() == "Pune"
    assert not await runtime.page.locator("#agree").is_checked()
    assert writes == []


@pytest.mark.asyncio
async def test_owner_consent_cannot_trigger_background_submission(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    key = "fictional-owner-checkbox-isolation-key"  # pragma: allowlist secret — fixture only
    monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", key)
    get_settings.cache_clear()
    state = await create(client, base, "/consent-get")
    state = (await action(client, state, "analyze")).json()
    path = f"/api/v1/browser-applications/{state['packet']['id']}/consent"
    raw = json.dumps(
        {
            "expected_revision": state["packet"]["revision"],
            "field_id": state["analysis"]["fields"][0]["field_id"],
            "checked": True,
            "confirm_page_context": True,
        }
    ).encode()
    result = await client.post(
        path,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": approval_header(
                key, path, raw, nonce=uuid4().hex, timestamp=int(time.time())
            ),
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["in_page_network_isolation"]
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("[type=checkbox]").is_checked()
    assert runtime.blocked_step_requests >= 1
    assert not any(url.startswith("/save-draft") for url in writes.reads)
    assert writes == []


@pytest.mark.asyncio
async def test_ambiguous_custom_controls_and_consent_stay_manual(browser_api):
    client, base, writes, _ = browser_api
    state = await create(client, base, "/ambiguous-choices")
    await browser.sessions[state["packet"]["id"]].scan()
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    assert all(not f["supported"] for f in state["analysis"]["fields"])
    for question in ["Processing choice", "Declaration", "Contact preference"]:
        field = next(
            f for f in state["analysis"]["fields"] if f["question"] == question
        )
        assert "manual" in field["manual_reason"].casefold()
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/fill-get", "/fill-post"])
async def test_filling_blocks_background_submission_and_stops_before_more_values(
    browser_api, path
):
    client, base, writes, _ = browser_api
    state = await create(client, base, path)
    state = (await action(client, state, "analyze")).json()
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis"]["diagnostic"] == "network_activity_requires_takeover"
    assert "Take Over" in result["recovery"]
    assert result["in_page_network_isolation"]
    runtime = browser.sessions[state["packet"]["id"]]
    assert runtime.blocked_step_requests >= 1
    assert await runtime.page.locator("[name=email]").input_value() == ""
    assert not any(url.startswith("/save-draft") for url in writes.reads)
    assert writes == []
