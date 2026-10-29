"""Company retrieval is bounded, credential-free, permissioned and evidence-only."""

import asyncio
import json
import time
from uuid import UUID, uuid4

import pytest

from backend.app.browser.company_source_html import extract
from backend.app.browser.company_source_policy import robots_permit, source_url
from backend.app.browser.company_source_worker import fetch
from backend.app.browser.owner_approval import approval_header
from backend.app.browser.runner import browser
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.knowledge.opportunity import reviewed_context
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.tests import test_browser_assistant as fixture
from backend.tests.company_source_employers import company_site

browser_api = fixture.browser_api
KEY = "fictional-company-source-owner-key-separate"  # pragma: allowlist secret — fixture only


async def signed(client, path, data):
    raw = json.dumps(data).encode()
    return await client.post(
        path,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": approval_header(
                KEY, path, raw, nonce=uuid4().hex, timestamp=int(time.time())
            ),
        },
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/about",
        "https://user:pass@example.com/about",  # pragma: allowlist secret — fictional rejected URL, never fetched
        "https://example.com/about?",
        "https://example.com/about?q=private",
        "https://example.com/about#token",
        "https://example.com/../about",
        "https://example.com/%61bout",
        "https://example.com/api/about",
        "https://example.com/account/about",
        "https://example.com/sign-in",
        "https://example.com/robots.txt",
        "https://naukri.com/about",
        "https://linkedin.com/about",
        "https://127.0.0.1/about",
        "https://example.internal/about",
        "https://example.com/about\r\nHeader:x",
    ],
)
def test_company_source_url_rejects_unreviewable_or_restricted_targets(url):
    with pytest.raises(ValueError):
        source_url(url)


@pytest.mark.parametrize(
    "rules,path,expected",
    [
        ("User-agent: *\nDisallow: /private", "/about", True),
        ("User-agent: *\nDisallow: /", "/about", False),
        (
            "User-agent: OtherBot\nDisallow: /about\nUser-agent: *\nAllow: /about",
            "/about",
            False,
        ),
        ("User-agent: *\nDisallow: /ab*out$", "/about", False),
        ("User-agent: *\nDisallow: /about$", "/about-us", True),
        ("User-agent: *\nCrawl-delay: 5", "/about", False),
        ("User-agent: *\nRequest-rate: 1/60", "/about", False),
        ("Disallow: /%61bout", "/about", False),
        ("unsupported syntax", "/about", False),
    ],
)
def test_conservative_robots_rules_never_establish_access_permission(
    rules, path, expected
):
    assert robots_permit(rules, path) is expected


def test_public_html_excludes_forms_hidden_scripts_and_unrelated_sections():
    html = """<title>Example Circuit</title><main><h2>About us</h2><p>We build Python services.</p>
    <form><p>PRIVATE FORM CONTENT</p><textarea>SECRET</textarea></form><p aria-hidden=true>HIDDEN</p>
    <p style='display: none'>HIDDEN</p><script>SECRET</script><h2>Other section</h2><p>UNRELATED</p></main>"""
    result = extract(html, "Example Circuit")
    assert result["company_text"] == "We build Python services."
    with pytest.raises(ValueError, match="identity"):
        extract(html, "Example Circuitous")
    with pytest.raises(ValueError, match="Ambiguous"):
        extract(
            "<h1>Example Circuit</h1><div data-company-description>A</div><div data-company-description>B</div>",
            "Example Circuit",
        )
    with pytest.raises(ValueError, match="No supported"):
        extract(
            "<h1>Example Circuit</h1><script>loadDescription()</script>",
            "Example Circuit",
        )


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "robots_deny",
        "robots_redirect",
        "redirect",
        "auth",
        "quota",
        "mime",
        "oversized",
        "encoding",
        "wrong_company",
        "captcha",
        "auth_wall",
    ],
)
def test_actual_public_http_reader_stops_at_access_and_content_boundaries(mode):
    with company_site() as (base, reads):
        reads.mode = mode
        payload = {
            "url": base + "/about",
            "testing": True,
            "address": "127.0.0.1",
            "company_name": "Example Circuit",
        }
        if mode == "valid":
            result = fetch(payload)
            assert (
                result["company_text"]
                == "Example Circuit builds reliable Python task management tools."
            )
        else:
            with pytest.raises(ValueError):
                fetch(payload)
        assert all(r["path"] in {"/robots.txt", "/about"} for r in reads)
        if mode in {"robots_deny", "robots_redirect", "auth", "quota"}:
            assert [r["path"] for r in reads] == ["/robots.txt"]
        for read in reads:
            headers = {k.lower(): v for k, v in read["headers"].items()}
            assert (
                not {"cookie", "authorization", "referer", "proxy-authorization"}
                & headers.keys()
            )
            assert "Alex" not in json.dumps(headers)


@pytest.mark.asyncio
async def test_owner_reviewed_external_company_source_has_distinct_durable_attribution(
    browser_api, monkeypatch
):
    client, base, writes, session = browser_api
    with company_site() as (public, reads):
        monkeypatch.setenv("OPPORTUNITY_CONTEXT_ENABLED", "true")
        monkeypatch.setenv("COMPANY_SOURCE_FETCH_ENABLED", "true")
        monkeypatch.setenv("COMPANY_SOURCE_URLS", json.dumps([public + "/about"]))
        monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", KEY)
        get_settings.cache_clear()
        state = await fixture.create(client, base, "/opportunity")
        packet = state["packet"]
        await browser.sessions[packet["id"]].page.evaluate(
            "document.cookie='fictional_session=PRIVATE-COOKIE; path=/'"
        )
        route = "/api/v1/browser-applications/" + packet["id"]
        body = {
            "expected_revision": packet["revision"],
            "source_url": public + "/about",
            "confirm_public_source_permission": True,
        }
        assert (
            await client.post(route + "/company-source-preview", json=body)
        ).status_code == 403
        assert reads == []
        response = await signed(client, route + "/company-source-preview", body)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["company_source_url"].endswith("/about")
        assert "PRIVATE" not in response.text and "HIDDEN" not in response.text
        assert [r["path"] for r in reads] == ["/robots.txt", "/about"]
        cached = await signed(client, route + "/company-source-preview", body)
        assert cached.status_code == 200 and cached.json() == preview
        assert len(reads) == 2
        assert not any(
            cookie["name"] == "company_poison"
            for cookie in await browser.sessions[packet["id"]].context.cookies()
        )
        assert all(
            "cookie" not in {key.lower() for key in read["headers"]} for read in reads
        )
        # No company evidence changes until the exact excerpt is reviewed.
        job = await session.get(Job, UUID(packet["job_id"]))
        company = await session.get(Company, job.company_id)
        assert reviewed_context(job, company) == []
        approval = {
            k: preview[k]
            for k in (
                "expected_revision",
                "capture_digest",
                "job_text",
                "company_text",
                "company_source_token",
            )
        }
        approval["confirm_company_job_and_source"] = True
        forged = await signed(
            client,
            route + "/opportunity-approve",
            {**approval, "company_text": "I managed 50 engineers."},
        )
        assert forged.status_code == 422
        response = await signed(client, route + "/opportunity-approve", approval)
        assert response.status_code == 200, response.text
        facts = reviewed_context(job, company)
        assert len(facts) == 2
        assert next(
            f for f in facts if f["reference"]["source_type"] == "opportunity_company"
        )["source_url"].endswith("/about")
        assert next(
            f for f in facts if f["reference"]["source_type"] == "opportunity_job"
        )["source_url"].endswith("/opportunity")
        rate = await session.get(OwnerPreference, "cs-rate:" + str(job.id))
        assert rate.value["requests"] == 1
        assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "permission",
        "disabled",
        "unconfigured",
        "domain",
        "injection",
        "expired",
        "reload",
        "policy_revoked",
        "private_dns",
    ],
)
async def test_external_source_rejects_changed_identity_permission_or_preview(
    browser_api, monkeypatch, failure
):
    client, base, writes, session = browser_api
    with company_site() as (public, reads):
        monkeypatch.setenv("OPPORTUNITY_CONTEXT_ENABLED", "true")
        monkeypatch.setenv("COMPANY_SOURCE_FETCH_ENABLED", "true")
        monkeypatch.setenv("COMPANY_SOURCE_URLS", json.dumps([public + "/about"]))
        monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", KEY)
        get_settings.cache_clear()
        state = await fixture.create(client, base, "/opportunity")
        packet = state["packet"]
        route = "/api/v1/browser-applications/" + packet["id"]
        body = {
            "expected_revision": packet["revision"],
            "source_url": public + "/about",
            "confirm_public_source_permission": failure != "permission",
        }
        if failure == "private_dns":
            get_settings().COMPANY_SOURCE_URLS = ["https://official.example:443/about"]
            body["source_url"] = "https://official.example:443/about"

            async def private_address(*args, **kwargs):
                return [(2, 1, 6, "", ("10.0.0.1", 443))]

            monkeypatch.setattr(
                asyncio.get_running_loop(), "getaddrinfo", private_address
            )
        if failure == "disabled":
            get_settings().COMPANY_SOURCE_FETCH_ENABLED = False
        if failure == "unconfigured":
            body["source_url"] = public + "/another-page"
        if failure == "domain":
            job = await session.get(Job, UUID(packet["job_id"]))
            company = await session.get(Company, job.company_id)
            company.domain = "another-employer.example"
            await session.commit()
        if failure == "injection":
            reads.mode = "injection"
        response = await signed(client, route + "/company-source-preview", body)
        if failure in {
            "permission",
            "disabled",
            "unconfigured",
            "domain",
            "private_dns",
        }:
            assert response.status_code in {403, 409, 422, 503}, response.text
            assert reads == []
            return
        assert response.status_code == 200, response.text
        preview = response.json()
        runtime = browser.sessions[packet["id"]]
        if failure == "expired":
            runtime.company_capture["expires"] = 0
        if failure == "reload":
            await runtime.set_manual(True)
            await runtime.page.reload()
            await runtime.set_manual(False)
        if failure == "policy_revoked":
            get_settings().COMPANY_SOURCE_URLS = []
        body = {
            k: preview[k]
            for k in (
                "expected_revision",
                "capture_digest",
                "job_text",
                "company_text",
                "company_source_token",
            )
        }
        body["confirm_company_job_and_source"] = True
        response = await signed(client, route + "/opportunity-approve", body)
        assert response.status_code in {403, 409, 422}, response.text
        assert len(reads) == 2 and writes == []


@pytest.mark.asyncio
async def test_worker_cancellation_reaps_a_process_born_after_stop(monkeypatch):
    from backend.app.browser import company_source_fetch as module

    release, born = asyncio.Event(), asyncio.Event()

    class Process:
        returncode = None

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

        async def communicate(self, payload):
            pytest.fail("Stopped worker must receive no input or make a request")

    process = Process()

    async def create(*args, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        born.set()
        await release.wait()
        return process

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    reader = module.SourceFetch()
    request = asyncio.create_task(reader.fetch({"url": "unused"}))
    await born.wait()
    reader.seal()
    release.set()
    with pytest.raises(ValueError):
        await request
    await reader.close()
    assert process.returncode == -9
    assert not reader.births and not reader.processes and not reader.cleanup


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["headings", "duplicate", "ambiguous_explicit"])
async def test_semantic_description_sections_exclude_private_and_ambiguous_content(
    browser_api, monkeypatch, mode
):
    from backend.tests.browser_employers import FORMS

    client, base, _, _ = browser_api
    monkeypatch.setenv("OPPORTUNITY_CONTEXT_ENABLED", "true")
    get_settings.cache_clear()
    html = """<h1>Example Circuit — Backend Engineer</h1><main><h2>About the role</h2>
      <p>Build Python services.</p><p>Partial <span hidden>PRIVATE-HIDDEN</span> description.</p>
      <form><h2>About us</h2><p>PRIVATE-FORM</p><label>Full name<input value=PRIVATE-VALUE></label></form>
      <h2>About us</h2><p>We build task tools.</p><p hidden>PRIVATE-HIDDEN</p></main>"""
    if mode == "duplicate":
        html += "<h2>About the role</h2><p>A different job.</p>"
    if mode == "ambiguous_explicit":
        html += "<div data-job-description>Different role</div><div data-job-description>Another role</div>"
    monkeypatch.setitem(FORMS, "/semantic-context", html)
    state = await fixture.create(client, base, "/semantic-context")
    response = await client.post(
        "/api/v1/browser-applications/"
        + state["packet"]["id"]
        + "/opportunity-preview",
        json={"expected_revision": state["packet"]["revision"]},
    )
    if mode != "headings":
        assert response.status_code == 409, response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["job_text"] == "Build Python services."
        assert response.json()["company_text"] == "We build task tools."
        assert "PRIVATE" not in response.text


@pytest.mark.asyncio
async def test_source_budget_survives_browser_restart_and_never_refetches_automatically(
    browser_api, monkeypatch
):
    client, base, _, session = browser_api
    with company_site() as (public, reads):
        for name, value in {
            "OPPORTUNITY_CONTEXT_ENABLED": "true",
            "COMPANY_SOURCE_FETCH_ENABLED": "true",
            "COMPANY_SOURCE_URLS": json.dumps([public + "/about"]),
            "BROWSER_OWNER_APPROVAL_KEY": KEY,
        }.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        state = await fixture.create(client, base, "/opportunity")
        packet = state["packet"]
        route = "/api/v1/browser-applications/" + packet["id"]
        data = {
            "expected_revision": packet["revision"],
            "source_url": public + "/about",
            "confirm_public_source_permission": True,
        }
        assert (
            await signed(client, route + "/company-source-preview", data)
        ).status_code == 200
        await browser.close(packet["id"])
        assert (
            await client.post(
                route + "/open",
                json={
                    "expected_revision": packet["revision"],
                    "executor": "isolated_browser",
            "approve_dedicated_profile": True,
                    "confirm_destination_permission": True,
                },
            )
        ).status_code == 200
        response = await signed(client, route + "/company-source-preview", data)
        assert response.status_code == 429, response.text
        rate = await session.get(OwnerPreference, "cs-rate:" + packet["job_id"])
        rate.value = {**rate.value, "last": time.time() - 61, "requests": 4}
        await session.commit()
        response = await signed(client, route + "/company-source-preview", data)
        assert response.status_code == 429, response.text
        assert len(reads) == 2


@pytest.mark.asyncio
async def test_cancelling_source_read_closes_worker_and_preserves_application(
    browser_api, monkeypatch
):
    client, base, writes, _ = browser_api
    with company_site() as (public, reads):
        reads.mode = "slow"
        for name, value in {
            "OPPORTUNITY_CONTEXT_ENABLED": "true",
            "COMPANY_SOURCE_FETCH_ENABLED": "true",
            "COMPANY_SOURCE_URLS": json.dumps([public + "/about"]),
            "BROWSER_OWNER_APPROVAL_KEY": KEY,
        }.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        state = await fixture.create(client, base, "/opportunity")
        packet = state["packet"]
        runtime = browser.sessions[packet["id"]]
        route = "/api/v1/browser-applications/" + packet["id"]
        request = asyncio.create_task(
            signed(
                client,
                route + "/company-source-preview",
                {
                    "expected_revision": packet["revision"],
                    "source_url": public + "/about",
                    "confirm_public_source_permission": True,
                },
            )
        )
        try:
            assert await asyncio.to_thread(reads.started.wait, 10)
            operation = (await client.get(route + "/operation")).json()[
                "active_operation"
            ]
            assert operation["kind"] == "company_source_preview"
            result = await client.post(
                route + "/actions",
                json={
                    "action": "cancel",
                    "expected_revision": packet["revision"],
                    "operation_id": operation["id"],
                },
            )
            assert result.status_code == 200, result.text
            assert (await request).status_code == 409
            assert not runtime.resources.company_source.processes
            assert runtime.company_capture is None and writes == []
            assert result.json()["packet"]["tracking_state"] == "not_applied"
        finally:
            reads.release.set()
            await request
