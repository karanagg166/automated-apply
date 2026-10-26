"""Saved pre-dropdown metadata must retain human answers during fresh analysis."""

import pytest

from backend.app.browser.service import metadata
from backend.app.services.applications.resume_selector import digest
from backend.tests import test_browser_assistant as fixture

browser_api = fixture.browser_api


@pytest.mark.asyncio
async def test_legacy_field_identity_preserves_saved_human_answer_review_and_field_count(
    browser_api,
):
    client, base, _, session = browser_api
    state = await fixture.create(client, base)
    state = (await fixture.action(client, state, "analyze")).json()
    ids = {field["field_id"] for field in state["analysis"]["fields"]}
    count = len(state["packet"]["fields"])
    email = next(
        field for field in state["analysis"]["fields"] if field["question"] == "Email"
    )
    route = "/api/v1/application-packets/" + state["packet"]["id"]
    response = await client.patch(
        route + "/questions/" + email["field_id"],
        json={
            "expected_revision": state["packet"]["revision"],
            "answer": "reviewed-owner@example.com",
        },
    )
    assert response.status_code == 200
    state["packet"] = response.json()
    response = await client.post(
        route + "/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": [email["field_id"]],
        },
    )
    assert response.status_code == 200
    state["packet"] = response.json()
    saved = await metadata(session, state["packet"]["id"])
    legacy = []
    for field in saved.value["fields"]:
        field = {key: value for key, value in field.items() if key != "choices_on_open"}
        field["identity"] = digest(
            {
                key: value
                for key, value in field.items()
                if key not in {"field_id", "identity"}
            }
        )
        legacy.append(field)
    saved.value = {**saved.value, "fields": legacy}
    await session.commit()
    response = await fixture.action(client, state, "analyze")
    assert response.status_code == 200
    state = response.json()
    assert {field["field_id"] for field in state["analysis"]["fields"]} == ids
    assert len(state["packet"]["fields"]) == count
    answer = next(
        field for field in state["packet"]["fields"] if field["id"] == email["field_id"]
    )
    assert answer["effective_answer"] == "reviewed-owner@example.com"
    assert answer["review_status"] == "reviewed"
