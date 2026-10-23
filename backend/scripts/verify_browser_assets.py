"""PG17/TCP/FastAPI/Chromium public-asset bootstrap with private-session isolation."""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(client, packet, settings, reads, writes):
    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    route = "/api/v1/browser-applications/" + packet["id"]
    policy = (await client.get("/api/v1/browser-applications/policy")).json()
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "backend/scripts/browser_assistant.py"),
        "get_browser_policy",
        "--origin",
        str(client.base_url).rstrip("/"),
        env={
            "PATH": "/usr/bin:/bin",
            "JOB_AGENT_API_TOKEN": settings.JOB_AGENT_API_TOKEN.get_secret_value(),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await asyncio.wait_for(worker.communicate(), timeout=15)
    import json

    assert worker.returncode == 0, error.decode()
    assert json.loads(output) == policy
    assert policy["origins"] == settings.BROWSER_ASSET_ORIGINS
    body = {
        "expected_revision": packet["revision"],
        "approve_dedicated_profile": True,
        "confirm_destination_permission": True,
    }
    assert (await client.post(route + "/open", json=body)).status_code == 422
    response = await client.post(
        route + "/open",
        json={
            **body,
            "confirm_asset_permissions": True,
            "asset_policy_digest": policy["digest"],
        },
    )
    assert response.status_code == 200, response.text
    runtime = browser.sessions[packet["id"]]
    assert await runtime.page.locator("[name=name]").count() == 1
    assert (
        await runtime.page.locator("#application").evaluate(
            "e=>getComputedStyle(e).borderTopWidth"
        )
        == "3px"
    )
    response = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "fill",
            "confirm_reviewed_values": True,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["analysis"]["diagnostic"] == "filled_review_on_website"
    assert state["assets"]["sealed"] and state["assets"]["requests"] == 2
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    assert await runtime.page.locator("[type=file]").evaluate("e=>e.files.length") == 1
    for request in reads:
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert (
            not {"cookie", "authorization", "referer", "proxy-authorization"}
            & headers.keys()
        )
    assert not any(
        cookie["name"] == "asset_poison" for cookie in await runtime.context.cookies()
    )
    assert not state["automated_submission_enabled"] and writes == []
    await browser.close(packet["id"])
    await close_db_engine()
    saved = (await client.get(route)).json()
    assert (
        not saved["connected"]
        and saved["analysis"]["diagnostic"] == "filled_review_on_website"
    )
    assert saved["packet"]["tracking_state"] == "not_applied"
    print(
        "PASS: PG17 + TCP FastAPI + Chromium approved public JS/CSS bootstrap, credential-free relay, reviewed facts/PDF fill and durable manual-handoff tracking",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], asset_demo=True))
