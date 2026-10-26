"""PG17 + real browser proof of grouped choices, owner-reviewed Next and custom controls."""

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
    response = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()

    async def answer_and_fill(state, values):
        reviewed = []
        for question, answer in values.items():
            field = next(
                f for f in state["analysis"]["fields"] if f["question"] == question
            )
            response = await client.patch(
                f"/api/v1/application-packets/{packet['id']}/questions/{field['field_id']}",
                json={
                    "expected_revision": state["packet"]["revision"],
                    "answer": answer,
                },
            )
            assert response.status_code == 200, response.text
            state["packet"] = response.json()
            reviewed.append(field["field_id"])
        response = await client.post(
            f"/api/v1/application-packets/{packet['id']}/review",
            json={
                "expected_revision": state["packet"]["revision"],
                "action": "review",
                "reviewed_field_ids": reviewed,
            },
        )
        assert response.status_code == 200, response.text
        response = await client.post(
            route + "/actions",
            json={
                "expected_revision": response.json()["revision"],
                "action": "fill",
                "confirm_reviewed_values": True,
                "confirm_page_context": True,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
        return response.json()

    state = await answer_and_fill(state, {"Remote work preference": "remote"})
    response = await client.post(
        route + "/step-preview", json={"expected_revision": state["packet"]["revision"]}
    )
    assert response.status_code == 200 and response.json()["complete"], response.text
    preview = response.json()
    body = json.dumps(
        {
            "expected_revision": preview["expected_revision"],
            "preview_digest": preview["preview_digest"],
            "idempotency_key": "fictional-pg-step-001",
            "confirm_values_and_consents": True,
        }
    ).encode()
    proof = approval_header(
        settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
        route + "/advance-step",
        body,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    response = await client.post(
        route + "/advance-step",
        content=body,
        headers={"Content-Type": "application/json", "X-Browser-Owner-Approval": proof},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["analysis"]["diagnostic"] == "next_step_analyzed"
    assert state["analysis"]["page_context"]["step"] == "Step 2"
    state = await answer_and_fill(
        state, {"Department": "Engineering", "Availability date": "2050-01-01"}
    )
    runtime = browser.sessions[packet["id"]]
    assert await runtime.page.locator("#department").input_value() == "Engineering"
    assert await runtime.page.locator("[type=date]").input_value() == "2050-01-01"
    assert not state["automated_submission_enabled"]
    assert runtime.blocked_mutations == 0
    await browser.close(packet["id"])
    saved = (await client.get(route)).json()
    assert len(saved["analysis"]["step_history"]) == 1
    assert saved["analysis"]["step_history"][0]["outcome"] == "next_step_analyzed"
    print(
        "PASS: PG17 + FastAPI + Chromium radio/custom dropdown/date filling, exact signed in-page Next and durable no-replay history; no submission",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], steps_demo=True))
