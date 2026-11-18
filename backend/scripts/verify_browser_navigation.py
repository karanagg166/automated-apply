"""Actual local TCP API/PG17/Chromium manual server navigation and signed resumption."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(client, packet, settings, writes):
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser

    route = "/api/v1/browser-applications/" + packet["id"]
    response = await client.post(
        route + "/open",
        json={
            "expected_revision": packet["revision"],
            "executor": "isolated_browser",
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": packet["revision"],
            "action": "analyze",
        },
    )
    assert response.status_code == 200, response.text
    state = response.json()
    revision = state["packet"]["revision"]
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": revision,
            "action": "take_over",
        },
    )
    assert response.status_code == 200, response.text
    runtime = browser.sessions[packet["id"]]
    # This is the fixture's simulated owner action, never an assistant-side step.
    await runtime.page.locator("[name=name]").fill("Fictional owner-entered value")
    await runtime.page.get_by_role("button", name="Save and continue").click()
    await runtime.page.wait_for_url("**/server-step-two")
    await runtime.page.wait_for_function("window.__aaManual === true")
    assert writes == ["/server-save"]
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": revision,
            "action": "analyze",
        },
    )
    assert response.status_code == 409, response.text
    response = await client.post(
        route + "/page-preview", json={"expected_revision": revision}
    )
    assert response.status_code == 200, response.text
    view = response.json()
    raw = json.dumps(
        {
            "expected_revision": revision,
            "capture_digest": view["capture_digest"],
            "confirm_same_application": True,
        }
    ).encode()
    assert (
        await client.post(
            route + "/resume-page",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
    ).status_code == 403
    proof = approval_header(
        settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
        route + "/resume-page",
        raw,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    response = await client.post(
        route + "/resume-page",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": proof,
        },
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["analysis"]["diagnostic"] == "owner_page_resumed"
    assert state["packet"]["snapshot"]["destination"]["application_url"].endswith(
        "/server-step-one"
    )
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "fill",
            "confirm_page_context": True,
            "confirm_reviewed_values": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    await runtime.page.get_by_role("button", name="Submit application").click()
    assert writes == ["/server-save"]
    await browser.close(packet["id"])
    saved = (await client.get(route)).json()
    assert saved["packet"]["tracking_state"] == "not_applied"
    assert not saved["automated_submission_enabled"]
    assert (
        saved["analysis"]["navigation_history"][0]["capture_digest"]
        == view["capture_digest"]
    )
    print(
        "PASS: PG17 + TCP FastAPI + Chromium manual server save, signed page resumption, fresh fill and durable history; no application submission",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], navigation_demo=True))
