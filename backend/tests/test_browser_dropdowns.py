"""Actual Chromium transient list discovery, source handoff and side-effect checks."""

import asyncio

import pytest
from fastapi import HTTPException

from backend.app.browser.runner import browser
from backend.tests import browser_employers
from backend.tests import test_browser_assistant as fixture
from backend.tests.dropdown_employers import application

browser_api = fixture.browser_api
action = fixture.action


async def create(client, base, monkeypatch, **kwargs):
    monkeypatch.setitem(browser_employers.FORMS, "/transient", application(**kwargs))
    return await fixture.create(client, base, "/transient")


async def review_city(client, state):
    field = next(f for f in state["analysis"]["fields"] if f["kind"] == "combobox")
    assert field["supported"] and field["choices_on_open"]
    assert field["options"] == ["Pune", "Bengaluru"]
    path = f"/api/v1/application-packets/{state['packet']['id']}"
    edited = await client.patch(
        path + "/questions/" + field["field_id"],
        json={"expected_revision": state["packet"]["revision"], "answer": "Pune"},
    )
    assert edited.status_code == 200, edited.text
    state["packet"] = edited.json()
    reviewed = await client.post(
        path + "/review",
        json={
            "expected_revision": state["packet"]["revision"],
            "action": "review",
            "reviewed_field_ids": [field["field_id"]],
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    state["packet"] = reviewed.json()
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "button,mode", [(False, "local"), (True, "local"), (False, "delayed")]
)
async def test_open_only_dropdowns_are_inspected_without_value_changes_then_reviewed_and_filled(
    browser_api, monkeypatch, button, mode
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, button=button, mode=mode)
    runtime = browser.sessions[state["packet"]["id"]]
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    assert await runtime.page.locator("#city-options").count() == 0
    assert await runtime.page.locator("#city-code").input_value() == ""
    assert not await runtime.page.locator("#consent").is_checked()
    assert await runtime.page.locator("[name=name]").input_value() == ""
    state = await review_city(client, state)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await runtime.page.locator("#city-code").input_value() == "pune"
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    assert not await runtime.page.locator("#consent").is_checked()
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mutate", "get", "submit", "unclosable"])
async def test_inspection_stops_on_value_mutation_network_submission_attempt_or_unclosable_popup(
    browser_api, monkeypatch, mode
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, mode=mode)
    response = await action(client, state, "analyze")
    assert response.status_code == 409, response.text
    runtime = browser.sessions[state["packet"]["id"]]
    assert runtime.in_page_mode and not runtime.manual
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert await runtime.page.locator("#city-code").input_value() == ""
    assert not any(path.startswith("/save-draft") for path in writes.reads)
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ambiguous", "consent", "disabled", "multi"])
async def test_ambiguous_or_consent_choices_are_never_filled(
    browser_api, monkeypatch, mode
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, mode=mode)
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = response.json()
    field = next(f for f in state["analysis"]["fields"] if f["kind"] == "combobox")
    assert not field["supported"]
    assert field["choices_on_open"]
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("#city-code").input_value() == ""
    assert writes == []


@pytest.mark.asyncio
async def test_changed_choice_catalog_requires_reanalysis_and_new_review(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch)
    state = (await action(client, state, "analyze")).json()
    state = await review_city(client, state)
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.evaluate("window.fixtureChoices=['Mumbai','Delhi']")
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 409, response.text
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert await runtime.page.locator("#city-code").input_value() == ""
    assert writes == []


@pytest.mark.asyncio
async def test_dependent_question_interrupts_filling_before_later_answers(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, mode="dependent")
    state = (await action(client, state, "analyze")).json()
    state = await review_city(client, state)
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["analysis"]["diagnostic"]
        == "interrupted_reanalyze_before_retry"
    )
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.locator("#city-code").input_value() == "pune"
    assert await runtime.page.locator("[name=email]").input_value() == ""
    assert writes == []


@pytest.mark.asyncio
async def test_server_loaded_choices_require_manual_takeover_before_local_inspection(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, mode="remote")
    response = await action(client, state, "analyze")
    assert response.status_code == 409, response.text
    assert "/choice-options" not in writes.reads
    runtime = browser.sessions[state["packet"]["id"]]
    assert (await action(client, state, "take_over")).status_code == 200
    # Simulates the owner loading/closing this one known fictional dropdown.
    await runtime.page.locator("#city").click()
    await runtime.page.get_by_role("option", name="Pune", exact=True).wait_for()
    await runtime.page.locator("#city").press("Escape")
    assert writes.reads.count("/choice-options") == 1
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    state = await review_city(client, response.json())
    response = await action(
        client, state, "fill", confirm_reviewed_values=True, confirm_page_context=True
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert writes.reads.count("/choice-options") == 1
    assert await runtime.page.locator("#city-code").input_value() == "pune"
    assert not runtime.manual and runtime.in_page_mode
    assert writes == []


@pytest.mark.asyncio
async def test_actual_reopened_options_are_rechecked_before_selecting(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch)
    runtime = browser.sessions[state["packet"]["id"]]
    fields, _ = await runtime.scan()
    combo = next(f for f in fields if f["kind"] == "combobox")
    await runtime.page.evaluate("window.fixtureChoices=['Mumbai','Delhi']")
    with pytest.raises(HTTPException) as error:
        await runtime.fill(combo, value="Pune")
    assert error.value.status_code == 409
    assert await runtime.page.locator("#city-code").input_value() == ""
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra", ['<iframe title="Embedded ATS"></iframe>', "<input type=password>"]
)
async def test_embedded_or_authentication_pages_never_probe_dropdowns(
    browser_api, monkeypatch, extra
):
    client, base, writes, _ = browser_api
    monkeypatch.setitem(browser_employers.FORMS, "/transient", application() + extra)
    state = await fixture.create(client, base, "/transient")
    response = await action(client, state, "analyze")
    assert response.status_code == (200 if "iframe" in extra else 409)
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.evaluate("window.fixtureOpens") == 0
    assert writes == []


@pytest.mark.asyncio
async def test_browser_disconnection_during_inspection_stops_without_replay(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    state = await create(client, base, monkeypatch, mode="delayed")
    runtime = browser.sessions[state["packet"]["id"]]
    task = asyncio.create_task(action(client, state, "analyze"))
    await runtime.page.wait_for_function("window.fixtureOpens > 0")
    await browser.close(state["packet"]["id"])
    assert (await task).status_code == 409
    assert not browser.operations.public(state["packet"]["id"])
    saved = (
        await client.get("/api/v1/browser-applications/" + state["packet"]["id"])
    ).json()
    assert not saved["connected"] and saved["packet"]["tracking_state"] == "not_applied"
    assert writes == []


@pytest.mark.asyncio
async def test_large_number_of_transient_dropdowns_stays_within_inspection_budget(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    html = "<h1>Example Circuit careers</h1><form>"
    for index in range(4):
        html += f'<input readonly role=combobox aria-label="Preferred city {index}" aria-expanded=false>'
    html += """</form><script>window.fixtureOpens=0;
    for(const [i,e] of [...document.querySelectorAll('[role=combobox]')].entries()) {
      e.addEventListener('click',()=>{
        window.fixtureOpens++;e.setAttribute('aria-expanded','true');e.setAttribute('aria-controls','list-'+i);
        const list=document.createElement('ul');list.id='list-'+i;list.setAttribute('role','listbox');
        list.innerHTML='<li role=option>Pune</li><li role=option>Mumbai</li>';document.body.append(list);
      });
      e.addEventListener('keydown',event=>{if(event.key==='Escape'){
        document.getElementById('list-'+i)?.remove();e.removeAttribute('aria-controls');e.setAttribute('aria-expanded','false');
      }});
    }</script>"""
    monkeypatch.setitem(browser_employers.FORMS, "/transient", html)
    state = await fixture.create(client, base, "/transient")
    response = await action(client, state, "analyze")
    assert response.status_code == 200, response.text
    fields = response.json()["analysis"]["fields"]
    assert len(fields) == 4 and sum(f["supported"] for f in fields) == 3
    runtime = browser.sessions[state["packet"]["id"]]
    assert await runtime.page.evaluate("window.fixtureOpens") == 3
    assert not fields[-1]["supported"]
    assert writes == []


@pytest.mark.asyncio
async def test_analysis_blocks_network_from_passive_dom_inspection_before_clicking(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    html = (
        application()
        + """<script>
      const observer=new MutationObserver(()=>{
        observer.disconnect();fetch('/save-draft?source=dom-observer').catch(()=>{});
      });observer.observe(document.forms[0],{subtree:true,attributes:true,attributeFilter:['data-aa-field']});
    </script>"""
    )
    monkeypatch.setitem(browser_employers.FORMS, "/transient", html)
    state = await fixture.create(client, base, "/transient")
    response = await action(client, state, "analyze")
    assert response.status_code == 409, response.text
    runtime = browser.sessions[state["packet"]["id"]]
    assert runtime.in_page_mode and runtime.blocked_step_requests
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert not any(path.startswith("/save-draft") for path in writes.reads)
    assert writes == []


@pytest.mark.asyncio
async def test_inspection_detects_resume_bytes_changed_with_identical_file_metadata(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    html = application().replace(
        "</form><script>",
        '<label>Upload resume<input type=file id=cv accept=".pdf"></label></form><script>',
    )
    monkeypatch.setitem(browser_employers.FORMS, "/transient", html)
    state = await fixture.create(client, base, "/transient")
    runtime = browser.sessions[state["packet"]["id"]]
    await runtime.page.locator("#cv").set_input_files(
        {
            "name": "resume.pdf",
            "mimeType": "application/pdf",
            "buffer": b"%PDF-fictional-resume-A",
        }
    )
    before = await runtime.page.locator("#cv").evaluate(
        "e=>[e.files[0].name,e.files[0].size,e.files[0].lastModified]"
    )
    await runtime.page.evaluate("""() => {
      document.getElementById('city').addEventListener('click',()=>{
        const input=document.getElementById('cv'), old=input.files[0], transfer=new DataTransfer();
        transfer.items.add(new File(['%PDF-fictional-resume-B'],old.name,{type:old.type,lastModified:old.lastModified}));
        input.files=transfer.files;
      });
    }""")
    response = await action(client, state, "analyze")
    assert response.status_code == 409, response.text
    assert (
        await runtime.page.locator("#cv").evaluate(
            "e=>[e.files[0].name,e.files[0].size,e.files[0].lastModified]"
        )
        == before
    )
    assert (
        await runtime.page.locator("#cv").evaluate("e=>e.files[0].text()")
        == "%PDF-fictional-resume-B"
    )
    assert await runtime.page.locator("[name=name]").input_value() == ""
    assert runtime.in_page_mode and writes == []
