"""Actual Chromium multiple sets, explicit review and consent/dynamic boundaries."""

import json

import pytest
import pytest_asyncio

from backend.app.browser.runner import browser
from backend.app.core.config import get_settings
from backend.tests import browser_employers
from backend.tests import test_browser_assistant as fixture
from backend.tests.multiple_employers import application

browser_api = fixture.browser_api
action = fixture.action


@pytest_asyncio.fixture
async def multiple_api(browser_api, monkeypatch):
    monkeypatch.setenv("MULTI_SELECT_FIELDS_ENABLED", "true")
    get_settings.cache_clear()
    yield browser_api


async def create(api, monkeypatch, kind="select", **kwargs):
    client, base, _, _ = api
    monkeypatch.setitem(
        browser_employers.FORMS, "/multiple", application(kind, **kwargs)
    )
    state = await fixture.create(client, base, "/multiple")
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    return response.json()


async def review(client, state, field):
    response = await client.post(
        f"/api/v1/application-packets/{state['packet']['id']}/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": [field["field_id"]],
        },
    )
    assert response.status_code == 200, response.text
    state["packet"] = response.json()
    return state


async def selected(runtime, kind):
    if kind == "select":
        return await runtime.page.locator("#choices").evaluate(
            "e=>[...e.selectedOptions].map(o=>o.label)"
        )
    return await runtime.page.locator("#choices").evaluate(
        "e=>[...e.querySelectorAll('input[type=checkbox],[role=checkbox]')].filter(c=>c.checked || c.getAttribute('aria-checked')==='true').map(c=>(c.labels ? [...c.labels].map(l=>l.innerText).join(' ') : '') || c.getAttribute('aria-label'))"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select", "checkbox", "aria"])
async def test_verified_multiple_proposals_require_review_and_fill_empty_controls(
    multiple_api, monkeypatch, kind
):
    client, _, writes, _ = multiple_api
    state = await create(multiple_api, monkeypatch, kind, preselected=False)
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    assert field["supported"]
    item = next(f for f in state["packet"]["fields"] if f["id"] == field["field_id"])
    assert item["field_type"] == "multi_select" and item["requires_review"]
    assert json.loads(item["effective_answer"]) == ["Python", "FastAPI"]
    assert item["provenance"]["source"] == "candidate_profile"
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    runtime = browser.sessions[state["packet"]["id"]]
    assert await selected(runtime, kind) == []
    state = await review(client, response.json(), field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await selected(runtime, kind) == ["Python", "FastAPI"]
    assert not await runtime.page.locator("#consent").is_checked()
    assert response.json()["packet"]["tracking_state"] == "not_applied" and writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select", "checkbox", "aria"])
async def test_existing_multiple_selection_is_preserved_after_answer_review(
    multiple_api, monkeypatch, kind
):
    client, _, writes, _ = multiple_api
    state = await create(multiple_api, monkeypatch, kind)
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    item = next(f for f in state["packet"]["fields"] if f["id"] == field["field_id"])
    assert json.loads(item["effective_answer"]) == ["Python", "FastAPI"]
    runtime = browser.sessions[state["packet"]["id"]]
    assert await selected(runtime, kind) == ["Go"]
    state = await review(client, state, field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert await selected(runtime, kind) == ["Go"]
    assert field["field_id"] not in result["analysis"]["filled_field_ids"]
    validation = next(
        v
        for v in result["analysis"]["validation"]
        if v["field_id"] == field["field_id"]
    )
    assert not validation["complete"]
    assert validation["reason"] == "Existing answer preserved; review it on the website"
    assert not await runtime.page.locator("#consent").is_checked()
    assert result["packet"]["tracking_state"] == "not_applied" and writes == []


@pytest.mark.asyncio
async def test_disabled_capability_stays_manual_and_rejects_canonical_write(
    browser_api, monkeypatch
):
    client, _, writes, _ = browser_api
    state = await create(browser_api, monkeypatch)
    field = next(f for f in state["analysis"]["fields"] if f["kind"] == "multi_select")
    assert not field["supported"]
    response = await client.post(
        f"/api/v1/application-packets/{state['packet']['id']}/questions",
        json={
            "expected_revision": state["packet"]["revision"],
            "questions": [
                {
                    "question": "Technical skills",
                    "field_type": "multi_select",
                    "options": ["Python", "Go"],
                }
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["consent", "duplicate", "duplicate-values", "individual", "readonly"]
)
async def test_unsafe_checkbox_groups_remain_manual_even_with_reviewed_answers(
    multiple_api, monkeypatch, mode
):
    client, _, writes, _ = multiple_api
    state = await create(multiple_api, monkeypatch, "checkbox", mode=mode)
    groups = [f for f in state["analysis"]["fields"] if f["kind"] == "checkbox_group"]
    assert groups and all(not f["supported"] for f in groups)
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,mode",
    [("checkbox", "dynamic"), ("checkbox", "network"), ("select", "network")],
)
async def test_multiple_handlers_stop_before_later_answers(
    multiple_api, monkeypatch, kind, mode
):
    client, _, writes, _ = multiple_api
    state = await create(
        multiple_api, monkeypatch, kind, mode=mode, preselected=False
    )
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    state = await review(client, state, field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == (
        "network_activity_requires_takeover"
        if mode == "network"
        else "interrupted_reanalyze_before_retry"
    )
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("[name=email]").input_value() == ""
    assert not any(path.startswith("/save-draft") for path in writes.reads)
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select", "checkbox", "aria"])
@pytest.mark.parametrize("preselected", [False, True])
async def test_optional_reviewed_empty_set_preserves_existing_selections(
    multiple_api, monkeypatch, kind, preselected
):
    client, _, writes, _ = multiple_api
    state = await create(
        multiple_api, monkeypatch, kind, required=False, preselected=preselected
    )
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    response = await client.patch(
        f"/api/v1/application-packets/{state['packet']['id']}/questions/{field['field_id']}",
        json={"expected_revision": state["packet"]["revision"], "answer": "[]"},
    )
    assert response.status_code == 200, response.text
    state["packet"] = response.json()
    state = await review(client, state, field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await selected(browser.sessions[state["packet"]["id"]], kind) == (
        ["Go"] if preselected else []
    )
    validation = next(
        v
        for v in result["analysis"]["validation"]
        if v["field_id"] == field["field_id"]
    )
    if preselected:
        assert field["field_id"] not in result["analysis"]["filled_field_ids"]
        assert not validation["complete"]
        assert validation["reason"] == (
            "Existing answer preserved; review it on the website"
        )
    else:
        assert field["field_id"] in result["analysis"]["filled_field_ids"]
        assert validation["complete"] and validation["reason"] is None
    assert result["packet"]["tracking_state"] == "not_applied" and writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select", "checkbox", "aria"])
async def test_invalid_browser_state_is_reported_incomplete(
    multiple_api, monkeypatch, kind
):
    client, _, writes, _ = multiple_api
    state = await create(
        multiple_api, monkeypatch, kind, mode="invalid", preselected=False
    )
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    state = await review(client, state, field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    validation = next(
        v
        for v in response.json()["analysis"]["validation"]
        if v["field_id"] == field["field_id"]
    )
    assert (
        not validation["complete"]
        and validation["reason"] == "Browser validation failed"
    )
    assert writes == []


@pytest.mark.asyncio
async def test_native_option_code_changes_and_revocation_require_fresh_analysis(
    multiple_api, monkeypatch
):
    client, _, writes, _ = multiple_api
    state = await create(multiple_api, monkeypatch)
    field = next(f for f in state["analysis"]["fields"] if f["kind"] == "multi_select")
    state = await review(client, state, field)
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.locator("#choices option").first.evaluate(
        "e=>e.value='changed-code'"
    )
    assert (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).status_code == 409
    assert await selected(runtime, "select") == ["Go"]
    monkeypatch.setenv("MULTI_SELECT_FIELDS_ENABLED", "false")
    get_settings.cache_clear()
    path = "/api/v1/application-packets/" + state["packet"]["id"]
    revision = state["packet"]["revision"]
    assert (
        await client.patch(
            path + "/questions/" + field["field_id"],
            json={"expected_revision": revision, "answer": '["Go"]'},
        )
    ).status_code == 422
    assert (
        await client.post(
            path + "/questions/" + field["field_id"] + "/generate",
            json={"expected_revision": revision},
        )
    ).status_code == 422
    assert (
        await client.patch(
            path, json={"expected_revision": revision, "refresh_saved_data": True}
        )
    ).status_code == 422
    assert (
        await client.post(
            path + "/review",
            json={
                "expected_revision": revision,
                "action": "review",
                "reviewed_field_ids": [field["field_id"]],
            },
        )
    ).status_code == 422
    assert (await client.get(path)).json()["revision"] == revision
    assert (
        await action(
            client,
            state,
            "fill",
            confirm_reviewed_values=True,
            confirm_page_context=True,
        )
    ).status_code == 409
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select", "checkbox", "aria"])
async def test_reviewed_next_binds_actual_multiple_values_and_requires_owner_signature(
    multiple_api, monkeypatch, kind
):
    from backend.tests import test_browser_steps as steps

    steps.permission(monkeypatch)
    client, _, writes, _ = multiple_api
    state = await create(
        multiple_api, monkeypatch, kind, mode="step", consent=False, preselected=False
    )
    field = next(
        f
        for f in state["analysis"]["fields"]
        if f["kind"] in {"multi_select", "checkbox_group"}
    )
    state = await review(client, state, field)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    state = response.json()
    view_response = await steps.preview(client, state)
    assert view_response.status_code == 200, view_response.text
    view = view_response.json()
    assert view["complete"]
    value = next(
        v for v in view["values"] if v["kind"] in {"multi_select", "checkbox_group"}
    )
    assert json.loads(value["value"]) == ["Python", "FastAPI"]
    assert (await steps.advance(client, state, view, signed=False)).status_code == 403
    runtime = browser.sessions[state["packet"]["id"]]
    if kind == "select":
        await runtime.page.locator("#choices").select_option(label=["Python"])
    elif kind == "checkbox":
        await runtime.page.locator("#fastapi").uncheck()
    else:
        await runtime.page.locator("#fastapi").click()
    assert (await steps.advance(client, state, view)).status_code == 409
    view = (await steps.preview(client, state)).json()
    assert view["complete"]
    moved = await steps.advance(client, state, view)
    assert moved.status_code == 200, moved.text
    assert moved.json()["analysis"]["diagnostic"] == "next_step_analyzed"
    assert moved.json()["analysis"]["fields"][0]["question"] == "Availability date"
    again = await steps.advance(client, state, view)
    assert (
        again.status_code == 200 and len(again.json()["analysis"]["step_history"]) == 1
    )
    assert writes == []


@pytest.mark.asyncio
async def test_submit_buttons_cannot_be_automated_as_aria_checkboxes(
    multiple_api, monkeypatch
):
    client, _, writes, _ = multiple_api
    state = await create(multiple_api, monkeypatch, "aria", mode="submit-control")
    group = next(
        f for f in state["analysis"]["fields"] if f["kind"] == "checkbox_group"
    )
    assert (
        not group["supported"]
        and "Unsupported checkbox element" in group["manual_reason"]
    )
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200 and writes == []
    assert await selected(browser.sessions[state["packet"]["id"]], "aria") == ["Go"]
