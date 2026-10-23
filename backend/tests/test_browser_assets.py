"""Actual Chromium uses approved public assets without sharing its account cookies."""

import asyncio
import json

import pytest
import pytest_asyncio

from backend.app.browser.runner import browser, origin
from backend.app.core.config import get_settings
from backend.tests import browser_employers
from backend.tests import test_browser_submissions as execution_fixture
from backend.tests.asset_employers import application_html, static_site

execution_tables = execution_fixture.execution_tables
submission_api = execution_fixture.submission_api


@pytest_asyncio.fixture
async def assets_api(submission_api, monkeypatch):
    with static_site() as (assets, reads):
        client, base, writes, session = submission_api
        monkeypatch.setenv("BROWSER_ASSET_ORIGINS", json.dumps([assets]))
        monkeypatch.setitem(
            browser_employers.FORMS, "/assets", application_html(assets)
        )
        get_settings.cache_clear()
        yield client, base, assets, reads, writes


async def prepare(client, base):
    response = await client.post(
        "/api/v1/browser-applications",
        json={
            "application_url": base + "/assets",
            "company_name": "Example Circuit",
            "job_title": "Backend Engineer asset fixture",
            "idempotency_key": "fictional-asset-packet-001",
        },
    )
    assert response.status_code == 200, response.text
    packet = response.json()
    return "/api/v1/browser-applications/" + packet["id"], packet


async def open_page(client, route, packet, *, digest=None, approve=True):
    if digest is None:
        digest = (await client.get("/api/v1/browser-applications/policy")).json()[
            "digest"
        ]
    return await client.post(
        route + "/open",
        json={
            "expected_revision": packet["revision"],
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
            "confirm_asset_permissions": approve,
            "asset_policy_digest": digest,
        },
    )


@pytest.mark.asyncio
async def test_approved_cross_origin_assets_render_and_fill_without_cookie_or_auth_sharing(
    assets_api,
):
    client, base, assets, reads, writes = assets_api
    route, packet = await prepare(client, base)
    assert (await open_page(client, route, packet, approve=False)).status_code == 422
    assert (await open_page(client, route, packet, digest="a" * 64)).status_code == 422
    response = await open_page(client, route, packet)
    assert response.status_code == 200, response.text
    runtime = browser.sessions[packet["id"]]
    assert (
        await runtime.page.locator("#application").evaluate(
            "e => getComputedStyle(e).borderTopWidth"
        )
        == "3px"
    )
    assert await runtime.page.locator("[name=name]").count() == 1
    assert {entry["path"] for entry in reads} == {"/form.js", "/theme.css"}
    for entry in reads:
        headers = {name.lower(): value for name, value in entry["headers"].items()}
        assert (
            not {"cookie", "authorization", "referer", "proxy-authorization"}
            & headers.keys()
        )
        assert headers["user-agent"] == "AutomatedApply-PublicAssets/1"
    cookies = await runtime.context.cookies()
    assert any(
        cookie["name"] == "application_session" and cookie["httpOnly"]
        for cookie in cookies
    )
    assert not any(cookie["name"] == "asset_poison" for cookie in cookies)
    response = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["assets"]["sealed"]
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
    assert response.json()["analysis"]["diagnostic"] == "filled_review_on_website"
    assert await runtime.page.locator("[name=name]").input_value() == "Alex Example"
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    assert (
        await runtime.page.locator("[type=file]").evaluate("e => e.files.length") == 1
    )
    await runtime.page.locator("[type=submit]").click()
    assert writes == []


@pytest.mark.asyncio
async def test_filling_and_takeover_do_not_reopen_external_asset_loading(
    assets_api, monkeypatch
):
    client, base, assets, reads, _ = assets_api
    monkeypatch.setitem(
        browser_employers.FORMS, "/assets", application_html(assets, late=True)
    )
    route, packet = await prepare(client, base)
    assert (await open_page(client, route, packet)).status_code == 200
    analyzed = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "analyze"},
    )
    revision = analyzed.json()["packet"]["revision"]
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
        response.json()["analysis"]["diagnostic"]
        == "network_activity_requires_takeover"
    )
    assert not any(entry["path"] == "/late.js" for entry in reads)
    assert (
        await client.post(
            route + "/actions",
            json={"expected_revision": revision, "action": "take_over"},
        )
    ).status_code == 200
    runtime = browser.sessions[packet["id"]]
    await runtime.page.evaluate(
        "base => {const s=document.createElement('script');s.src=base+'/late.js';document.head.append(s)}",
        assets,
    )
    await runtime.page.wait_for_timeout(100)
    assert runtime.assets.sealed and not any(
        entry["path"] == "/late.js" for entry in reads
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script", ["form.js?token=fixture", "redirect.js", "auth.js", "wrong.js"]
)
async def test_queries_redirects_authenticated_assets_and_wrong_mime_require_handoff(
    assets_api, monkeypatch, script
):
    client, base, assets, reads, writes = assets_api
    monkeypatch.setitem(
        browser_employers.FORMS, "/assets", application_html(assets, script=script)
    )
    route, packet = await prepare(client, base)
    opened = await open_page(client, route, packet)
    assert opened.status_code == 200, opened.text
    assert (
        await client.post(
            route + "/actions",
            json={"expected_revision": packet["revision"], "action": "analyze"},
        )
    ).status_code == 409
    assert not any(
        entry["path"] in {"/never.js", "/form.js?token=fixture"} for entry in reads
    )
    assert writes == []


@pytest.mark.asyncio
async def test_policy_metadata_requires_authentication_and_never_approves_third_party_apis(
    assets_api, monkeypatch
):
    client, base, assets, reads, _ = assets_api
    assert (
        await client.get(
            "/api/v1/browser-applications/policy",
            headers={"Authorization": "Bearer invalid"},
        )
    ).status_code == 401
    assert (
        await client.get(
            "/api/v1/browser-applications/policy",
            headers={"Origin": "https://untrusted.invalid"},
        )
    ).status_code == 403
    monkeypatch.setitem(
        browser_employers.FORMS,
        "/assets",
        application_html(assets)
        + f"<script>fetch('{assets}/candidate.js',{{credentials:'include'}}).catch(()=>{{}})</script>",
    )
    route, packet = await prepare(client, base)
    assert (await open_page(client, route, packet)).status_code == 200
    assert not any(entry["path"] == "/candidate.js" for entry in reads)
    assert (
        origin(assets)
        in (await client.get("/api/v1/browser-applications/policy")).json()["origins"]
    )


@pytest.mark.asyncio
async def test_cancelling_an_opening_asset_request_reaps_its_worker(
    assets_api, monkeypatch
):
    client, base, assets, reads, _ = assets_api
    monkeypatch.setitem(
        browser_employers.FORMS, "/assets", application_html(assets, script="slow.js")
    )
    route, packet = await prepare(client, base)
    task = asyncio.create_task(open_page(client, route, packet))
    try:
        for _ in range(100):
            if reads.started.is_set():
                break
            await asyncio.sleep(0.05)
        assert reads.started.is_set()
        resources = browser.opening_resources[packet["id"]]
        children = list(resources.assets.processes)
        assert children
        control = (await client.get(route + "/operation")).json()["active_operation"]
        stopped = await client.post(
            route + "/actions",
            json={
                "action": "cancel",
                "expected_revision": control["expected_revision"],
                "operation_id": control["id"],
            },
        )
        assert stopped.status_code == 200, stopped.text
        assert (await task).status_code == 409
        assert not resources.assets.inflight and all(
            child.returncode is not None for child in children
        )
        assert not stopped.json()["connected"]
    finally:
        reads.release.set()
        await task
