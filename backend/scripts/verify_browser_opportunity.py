"""Disposable PG17 proof of reviewed employer context and fictional grounded generation."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(client, packet, settings):
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser

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
    preview = await client.post(
        route + "/opportunity-preview", json={"expected_revision": packet["revision"]}
    )
    assert preview.status_code == 200, preview.text
    data = {
        k: preview.json()[k]
        for k in ("expected_revision", "capture_digest", "job_text", "company_text")
    }
    data["confirm_company_job_and_source"] = True
    raw = json.dumps(data).encode()
    response = await client.post(
        route + "/opportunity-approve",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": approval_header(
                settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
                route + "/opportunity-approve",
                raw,
                nonce=uuid4().hex,
                timestamp=int(time.time()),
            ),
        },
    )
    assert response.status_code == 200, response.text
    state = (await client.get(route)).json()
    assert state["packet"]["revision"] == packet["revision"] + 1
    response = await client.post(
        route + "/actions",
        json={"expected_revision": state["packet"]["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    question = next(
        f for f in state["analysis"]["fields"] if f["question"].startswith("Why do you")
    )
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/questions/{question['field_id']}/generate",
        json={"expected_revision": state["packet"]["revision"]},
    )
    assert response.status_code == 200, response.text
    current = response.json()
    field = next(f for f in current["fields"] if f["id"] == question["field_id"])
    assert field["validation_status"] == "draft_ready", field
    assert (
        "Example Circuit" in field["effective_answer"]
        and "I built backend" in field["effective_answer"]
    )
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/review",
        json={
            "expected_revision": current["revision"],
            "action": "review",
            "confirm_resume": True,
            "confirm_destination": True,
            "reviewed_field_ids": [
                f["id"] for f in current["fields"] if f["effective_answer"]
            ],
        },
    )
    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
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
        await browser.sessions[packet["id"]].page.locator("textarea").input_value()
        == field["effective_answer"]
    )
    draft = field["provenance"]["answer_draft_id"]
    await browser.close(packet["id"])
    response = await client.get(
        f"/api/v1/application-answers/drafts/{draft}/opportunity-evidence"
    )
    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence and evidence[0]["source_url"].endswith("/opportunity")
    assert "Example Circuit" in evidence[0]["excerpt"]
    print(
        "PASS: PG17 + TCP FastAPI + Chromium capture, signed source review, fictional grounded proposal, reviewed fill and durable evidence; no live model or employer submission",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], opportunity_demo=True))
