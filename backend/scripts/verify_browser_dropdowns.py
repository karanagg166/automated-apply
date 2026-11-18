"""PG17/TCP/Chromium transient choices: manual source loading, review and durable fill."""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(client, packet, settings, writes):
    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    route = "/api/v1/browser-applications/" + packet["id"]

    async def command(action, revision=None, **kwargs):
        return await client.post(
            route + "/actions",
            json={
                "action": action,
                "expected_revision": revision or packet["revision"],
                **kwargs,
            },
        )

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
    runtime = browser.sessions[packet["id"]]
    assert (await command("analyze")).status_code == 409
    assert "/choice-options" not in writes.reads
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert (await command("take_over")).status_code == 200
    # A simulated human action against the owned fixture; the app never fetches choices automatically.
    await runtime.page.locator("#city").click()
    await runtime.page.get_by_role("option", name="Pune", exact=True).wait_for()
    await runtime.page.locator("#city").press("Escape")
    assert writes.reads.count("/choice-options") == 1
    response = await command("analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    field = next(f for f in state["analysis"]["fields"] if f["kind"] == "combobox")
    assert field["supported"] and field["choices_on_open"]
    assert field["options"] == ["Pune", "Bengaluru"]
    packet_route = "/api/v1/application-packets/" + packet["id"]
    response = await client.patch(
        packet_route + "/questions/" + field["field_id"],
        json={
            "expected_revision": state["packet"]["revision"],
            "answer": "Pune",
        },
    )
    assert response.status_code == 200, response.text
    state["packet"] = response.json()
    response = await command(
        "fill",
        state["packet"]["revision"],
        confirm_reviewed_values=True,
        confirm_page_context=True,
    )
    assert response.status_code == 200, response.text
    assert await runtime.page.locator("#city-code").input_value() == ""
    response = await client.post(
        packet_route + "/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": [field["field_id"]],
        },
    )
    assert response.status_code == 200, response.text
    response = await command(
        "fill",
        response.json()["revision"],
        confirm_reviewed_values=True,
        confirm_page_context=True,
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await runtime.page.locator("#city-code").input_value() == "pune"
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    assert not await runtime.page.locator("#consent").is_checked()
    assert writes.reads.count("/choice-options") == 1 and writes == []
    assert not state["automated_submission_enabled"]
    await browser.close(packet["id"])
    await close_db_engine()
    saved = (await client.get(route)).json()
    assert not saved["connected"] and saved["packet"]["tracking_state"] == "not_applied"
    assert next(f for f in saved["analysis"]["fields"] if f["kind"] == "combobox")[
        "choices_on_open"
    ]
    field = next(f for f in saved["packet"]["fields"] if f["id"] == field["field_id"])
    assert field["effective_answer"] == "Pune" and field["review_status"] == "reviewed"
    print(
        "PASS: PG17 + TCP FastAPI + Chromium transient dropdown, explicit manual choice loading, reviewed fill and durable tracking",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], dropdown_demo=True))
