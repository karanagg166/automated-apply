"""Actual isolated Chromium: preserve page answers and bind form destinations."""

import pytest

from backend.app.browser.runner import browser
from backend.tests import test_browser_assistant as fixture

browser_api = fixture.browser_api


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_analysis", "after_analysis"])
async def test_browser_preserves_existing_values_and_fills_remaining(browser_api, when):
    client, base, writes, _ = browser_api
    state = await fixture.create(client, base)
    runtime = browser.sessions[state["packet"]["id"]]
    if when == "before_analysis":
        await runtime.page.locator("[name=name]").fill("Owner's actual answer")
    state = (await fixture.action(client, state, "analyze")).json()
    if when == "after_analysis":
        await runtime.page.locator("[name=name]").fill("Owner's actual answer")
    response = await fixture.action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (
        await runtime.page.locator("[name=name]").input_value()
        == "Owner's actual answer"
    )
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    name = next(f for f in saved["analysis"]["fields"] if f["question"] == "Full name")
    assert name["field_id"] not in saved["analysis"]["filled_field_ids"]
    assert any(
        "Existing answer preserved" in (v["reason"] or "")
        for v in saved["analysis"]["validation"]
    )
    assert saved["packet"]["tracking_state"] == "not_applied" and not writes


@pytest.mark.asyncio
async def test_browser_destination_change_requires_new_review(browser_api):
    client, base, writes, _ = browser_api
    state = await fixture.create(client, base)
    state = (await fixture.action(client, state, "analyze")).json()
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.evaluate("document.forms[0].action = '/different-job'")
    response = await fixture.action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 409
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert not writes
