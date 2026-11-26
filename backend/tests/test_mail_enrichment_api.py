"""Phase 5 Layer 2: /api/v1/v2 drafts, enrichment status, mail status and draft-now.

Owner bearer on every route, validation, 404/409/503, idempotency, the 10-portal
roster with adapter badges, and zero secret leaks. Fake IMAP only.
"""

import json

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.api.v1.automation_v2 import (
    get_ai_runtime,
    get_enrichment_service,
    get_mail_service,
    get_v2_store,
)
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.service import EnrichmentService, build_providers
from backend.app.enrichment_v2.store import MemoryEnrichmentStore
from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.service import MailDraftService
from backend.app.main import app
from backend.tests.test_mail_v2 import PASSWORD, FakeIMAP
from backend.tests.test_mail_v2 import mail_service as build_mail

BASE = "/api/v1/v2"
APOLLO_KEY = "TEST_FAKE_TOKEN_ONLY_apollo_key_value"
ROUTES = [("GET", "/drafts"), ("GET", "/enrichment/status"), ("GET", "/mail/status"),
          ("POST", "/applications/00000000-0000-4000-8000-000000000000/draft-now")]


@pytest.fixture
def ctx():
    FakeIMAP.instances.clear()
    memory = MemoryStore(profile={"full_name": "Test Candidate", "verified_skills": ["Python"]})
    runtime = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                              env={}, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    config = EnrichmentConfig(keys={"apollo": APOLLO_KEY}, fetch_pages=False)
    apollo = httpx.MockTransport(lambda r: httpx.Response(200, json={"people": []}))
    enrichment = EnrichmentService(MemoryEnrichmentStore(), config=config, providers=build_providers(config, apollo))
    state = {"mail": build_mail(memory)}

    async def store_override():
        yield memory

    async def ai_override():
        return runtime

    async def mail_override():
        return state["mail"]

    async def enrichment_override():
        return enrichment

    app.dependency_overrides.update({get_v2_store: store_override, get_ai_runtime: ai_override,
                                     get_mail_service: mail_override, get_enrichment_service: enrichment_override})
    yield memory, state
    for dependency in (get_v2_store, get_ai_runtime, get_mail_service, get_enrichment_service):
        app.dependency_overrides.pop(dependency, None)


async def parked(store, i=1, jd="Mail careers@acme.io"):
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"n-{i}",
                                                      url=f"https://example.com/{i}", title="Backend Engineer",
                                                      company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters", payload={"contact_hints": {"jd_excerpt": jd}})
    return await store.transition(record, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")


async def test_every_phase5_route_requires_the_owner_bearer(async_client, phase2_auth, ctx):
    for method, path in ROUTES:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path
        assert (await async_client.request(method, BASE + path)).status_code == 401, path


async def test_mail_status_is_locked_read_and_draft_only_without_secrets(async_client, phase2_auth, ctx):
    response = await async_client.get(f"{BASE}/mail/status", headers=phase2_auth)
    body = response.json()
    assert response.status_code == 200 and body["permission"] == "READ_AND_DRAFT_ONLY"
    assert body["permission_label"] == "Gmail Permission: Read + Draft Only (Sending Disabled)"
    assert body["active_channel"] == "imap" and body["imap_email"] == "ow•••@example.com"
    assert PASSWORD not in response.text and "owner.test@example.com" not in response.text


async def test_mail_status_unconfigured(async_client, phase2_auth, ctx):
    ctx[1]["mail"] = MailDraftService(ctx[0], MailConfig(mail_app_disabled=True))
    body = (await async_client.get(f"{BASE}/mail/status", headers=phase2_auth)).json()
    assert (body["active_channel"], body["imap_configured"], body["mail_app_available"]) == \
        ("unconfigured", False, False)


async def test_enrichment_status_reports_credit_meters_without_keys(async_client, phase2_auth, ctx):
    response = await async_client.get(f"{BASE}/enrichment/status", headers=phase2_auth)
    body = response.json()
    by = {p["provider"]: p for p in body["providers"]}
    assert response.status_code == 200 and set(by) == {"apollo", "apify", "signalhire"}
    assert by["apollo"]["configured"] and by["apollo"]["daily_cap"] == 10 and by["apollo"]["state"] == "available"
    assert by["apify"]["state"] == "unconfigured" and by["apify"]["key_env"] == "APIFY_API_TOKEN"
    assert APOLLO_KEY not in response.text and body["cached_domains"] == 0


async def test_draft_now_creates_exactly_one_draft_and_is_idempotent(async_client, phase2_auth, ctx):
    store, _ = ctx
    record = await parked(store)
    url = f"{BASE}/applications/{record.id}/draft-now"
    first = (await async_client.post(url, headers=phase2_auth)).json()
    assert (first["ok"], first["code"], first["channel"]) == (True, "drafted", "imap")
    assert first["enrichment_status"] == "FOUND" and first["enrichment_source"] == "jd_text"
    assert first["draft"]["recipient_email"] == "careers@acme.io" and first["draft"]["status"] == "CREATED"
    second = (await async_client.post(url, headers=phase2_auth)).json()
    assert (second["ok"], second["code"]) == (True, "already_drafted")
    assert len(store.drafts) == 1 and sum(1 for i in FakeIMAP.instances for c in i.calls if c[0] == "append") == 1
    assert (await store.get_application(record.id)).state is S.QUOTA_HIT_PENDING  # state untouched


async def test_draft_now_without_any_email_makes_no_draft(async_client, phase2_auth, ctx):
    store, _ = ctx
    record = await parked(store, jd="No contact here.")
    body = (await async_client.post(f"{BASE}/applications/{record.id}/draft-now", headers=phase2_auth)).json()
    assert (body["ok"], body["code"], body["draft"]) == (False, "no_email_found", None) and store.drafts == []


async def test_draft_now_errors(async_client, phase2_auth, ctx):
    store, state = ctx
    missing = await async_client.post(f"{BASE}/applications/00000000-0000-4000-8000-000000000000/draft-now",
                                      headers=phase2_auth)
    garbage = await async_client.post(f"{BASE}/applications/not-a-uuid/draft-now", headers=phase2_auth)
    assert missing.status_code == 404 and garbage.status_code == 404
    record = await parked(store)
    store.records[("naukri", "n-1")].state = S.APPLYING
    assert (await async_client.post(f"{BASE}/applications/{record.id}/draft-now",
                                    headers=phase2_auth)).status_code == 409
    store.records[("naukri", "n-1")].state = S.QUOTA_HIT_PENDING
    state["mail"] = MailDraftService(store, MailConfig(mail_app_disabled=True))
    unconfigured = await async_client.post(f"{BASE}/applications/{record.id}/draft-now", headers=phase2_auth)
    assert unconfigured.status_code == 503 and "GMAIL_IMAP_APP_PASSWORD" in unconfigured.json()["detail"]


async def test_drafts_list_shows_retry_status_and_filters(async_client, phase2_auth, ctx):
    store, _ = ctx
    record = await parked(store)
    await async_client.post(f"{BASE}/applications/{record.id}/draft-now", headers=phase2_auth)
    from datetime import UTC, datetime

    retry = datetime(2026, 11, 27, 2, 30, tzinfo=UTC)
    await store.transition(await store.get_application(record.id), S.DRAFTED_AND_QUEUED,
                           "quota_hit_drafted_and_queued", retry_after=retry)
    page = (await async_client.get(f"{BASE}/drafts", headers=phase2_auth)).json()
    (item,) = page["items"]
    assert page["total"] == 1 and item["company_name"] == "Acme" and item["channel"] == "imap"
    assert item["application_state"] == "DRAFTED_AND_QUEUED" and item["retry_after"].startswith("2026-11-27T02:30")
    assert item["subject"] and item["body_preview"] and len(item["body_preview"]) <= 280
    assert (await async_client.get(f"{BASE}/drafts?platform=instahyre", headers=phase2_auth)).json()["total"] == 0
    assert (await async_client.get(f"{BASE}/drafts?platform=Bad!", headers=phase2_auth)).status_code == 422
    assert (await async_client.get(f"{BASE}/drafts?limit=500", headers=phase2_auth)).status_code == 422


async def test_portal_rules_expose_ten_portals_with_adapter_badges(async_client, phase2_auth, ctx):
    rows = (await async_client.get(f"{BASE}/portal-rules", headers=phase2_auth)).json()
    by = {row["platform"]: row for row in rows}
    assert len(by) == 15 and by["naukri"]["adapter_status"] == "ready" and by["naukri"]["enabled"]
    # Phase 6A: every portal has an adapter; the nine new ones stay disabled until the owner opts in.
    assert all(row["adapter_status"] == "ready" and not row["enabled"]
               for name, row in by.items() if name != "naukri")
    assert all(row["quota_fallback_daily_cap"] == 10 and row["quota_drafts_per_cycle"] == 5 for row in rows)
    assert by["greenhouse"]["requires_login"] is False and by["work_at_a_startup"]["label"] == "YC Work at a Startup"


async def test_applications_expose_draft_created_at(async_client, phase2_auth, ctx):
    store, _ = ctx
    record = await parked(store)
    await async_client.post(f"{BASE}/applications/{record.id}/draft-now", headers=phase2_auth)
    items = (await async_client.get(f"{BASE}/applications", headers=phase2_auth)).json()["items"]
    assert items[0]["draft_created_at"] is not None


def test_openapi_has_no_delivery_route():
    paths = app.openapi()["paths"]
    phase5 = [p for p in paths if p.startswith(BASE) and ("draft" in p or "mail" in p or "enrichment" in p)]
    assert sorted(phase5) == sorted([f"{BASE}/drafts", f"{BASE}/enrichment/status", f"{BASE}/mail/status",
                                     f"{BASE}/applications/{{application_id}}/draft-now",
                                     f"{BASE}/mail/replies"])  # Phase 6A: READ-ONLY reply feed (GET only)
    assert set(paths[f"{BASE}/mail/replies"]) == {"get"}
    assert "send" not in json.dumps({p: paths[p] for p in phase5}).lower().replace("sending disabled", "")
