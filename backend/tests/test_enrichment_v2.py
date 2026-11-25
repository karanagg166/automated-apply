"""Phase 5 Layer 1: the cost-protected recruiter email waterfall (enrichment_v2).

Domain cache hit/miss/TTL + negative cache, JD regex filtering and ranking, the
SSRF-guarded careers-page fetch, Apollo plan-restricted cooldown, Apify/SignalHire
daily caps, and the clean NO_EMAIL_FOUND outcome. All HTTP is MockTransport.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.extract import (
    PageFetcher,
    UnsafeTarget,
    assert_public_url,
    extract_emails,
    infer_company_domain,
    normalize_domain,
)
from backend.app.enrichment_v2.service import (
    NOT_FOUND_TTL,
    TRANSIENT_NOT_FOUND_TTL,
    EnrichmentService,
    build_providers,
    period_key,
)
from backend.app.enrichment_v2.store import MemoryEnrichmentStore

NOW = datetime(2026, 11, 26, 6, 30, tzinfo=UTC)
KEYS = {"apollo": "TEST_FAKE_TOKEN_ONLY", "apify": "TEST_FAKE_TOKEN_ONLY", "signalhire": "TEST_FAKE_TOKEN_ONLY"}


class Api:
    """Scripted provider endpoints keyed by host; records every request."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for marker, reply in self.routes.items():
            if marker in str(request.url):
                status, body = reply if isinstance(reply, tuple) else (200, reply)
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    def hosts(self):
        return [request.url.host for request in self.calls]


async def public_resolver(host):
    return ["93.184.216.34"]


def service(api=None, *, keys=None, caps=None, pages=None, store=None, fetch=False, clock=NOW):
    api = api or Api()
    config = EnrichmentConfig(keys=KEYS if keys is None else keys,
                              caps=caps or {"apollo": 10, "apify": 5, "signalhire": 5}, fetch_pages=fetch)
    transport = httpx.MockTransport(api.handler)
    page_api = pages or Api()
    fetcher = PageFetcher(transport=httpx.MockTransport(page_api.handler), resolver=public_resolver)
    return EnrichmentService(store or MemoryEnrichmentStore(), config=config,
                             providers=build_providers(config, transport), fetcher=fetcher,
                             clock=lambda: clock), api


# --- Tier 1 extraction + ranking -------------------------------------------------------
def test_jd_regex_rejects_noise_and_prefers_recruiting_inboxes_on_the_company_domain():
    jd = """Apply: careers@acme.io or write to priya.sharma@acme.io. Questions? support@acme.io.
    Do not reply to noreply@acme.io. Example: you@example.com. Logo: logo@2x.png.
    Our vendor: sales@vendorcorp.com. Spam trap: x@mailinator.com. Old address hr [at] acme [dot] io."""
    found = extract_emails(jd, source="jd_text", company_domain="acme.io")
    assert [c.email for c in found] == ["careers@acme.io", "hr@acme.io", "priya.sharma@acme.io"]
    assert found[0].kind == "recruiting" and found[-1].kind == "person"


def test_free_mail_is_accepted_only_when_published_as_a_hiring_inbox():
    jd = "Send CVs to hr.acmejobs@gmail.com. Founder personal: rahul1990@gmail.com"
    found = extract_emails(jd, source="jd_text")
    assert [c.email for c in found] == ["hr.acmejobs@gmail.com"] and found[0].kind == "freemail_recruiting"


@pytest.mark.parametrize("value,expected", [
    ("https://www.Acme.co.in/careers?x=1", "acme.co.in"), ("hr@Careers.Acme.com", "careers.acme.com"),
    ("http://10.0.0.1/admin", None), ("localhost", None), ("not a domain", None), ("", None)])
def test_normalize_domain(value, expected):
    assert normalize_domain(value) == expected


def test_infer_domain_skips_job_portals_and_social_links():
    jd = "Apply on https://www.naukri.com/job/123 or see https://linkedin.com/company/x. Site: https://acme.dev/about"
    assert infer_company_domain(None, "https://www.naukri.com/job-listings-1", jd) == "acme.dev"
    assert infer_company_domain(None, "https://www.naukri.com/job-listings-1", "no links") is None
    assert infer_company_domain("ACME.dev", None, None) == "acme.dev"


# --- Tier 0 cache ----------------------------------------------------------------------
async def test_tier1_jd_hit_is_cached_and_the_next_lookup_is_a_zero_credit_cache_hit():
    svc, api = service()
    first = await svc.find_recruiter_email("Acme", "acme.io", jd_text="Mail talent@acme.io")
    assert (first.status, first.email, first.source, first.cached) == ("FOUND", "talent@acme.io", "jd_text", False)
    second = await svc.find_recruiter_email("Acme", "acme.io")
    assert (second.email, second.cached, second.source) == ("talent@acme.io", True, "cache:jd_text")
    assert api.calls == [] and second.credits_spent == {}
    entry = await svc.store.get_cache("acme.io")
    assert entry.expires_at == NOW + timedelta(days=30)


async def test_expired_cache_entry_is_refreshed():
    store = MemoryEnrichmentStore()
    await store.put_cache("acme.io", status="FOUND", emails=[{"email": "old@acme.io", "source": "apollo"}],
                          source="apollo", expires_at=NOW - timedelta(seconds=1))
    svc, _ = service(store=store, keys={})
    result = await svc.find_recruiter_email("Acme", "acme.io", jd_text="jobs@acme.io")
    assert result.email == "jobs@acme.io" and not result.cached


async def test_negative_cache_skips_paid_tiers_but_still_reads_the_free_jd():
    store = MemoryEnrichmentStore()
    await store.put_cache("acme.io", status="NO_EMAIL_FOUND", emails=[], source="waterfall_exhausted",
                          expires_at=NOW + NOT_FOUND_TTL)
    svc, api = service(store=store)
    blocked = await svc.find_recruiter_email("Acme", "acme.io")
    assert (blocked.status, blocked.cached, api.calls) == ("NO_EMAIL_FOUND", True, [])
    free = await svc.find_recruiter_email("Acme", "acme.io", jd_text="Reach hiring@acme.io")
    assert free.email == "hiring@acme.io" and api.calls == []


# --- Tier 1b careers page + SSRF ---------------------------------------------------------
async def test_careers_page_fetch_finds_the_company_inbox():
    pages = Api({"acme.io/careers": None})
    pages.handler = lambda request: httpx.Response(
        200, headers={"content-type": "text/html"},
        text='<a href="mailto:careers@acme.io">Careers</a> <p>press@acme.io</p>')  # type: ignore[method-assign]
    svc, api = service(pages=pages, fetch=True, keys={})
    result = await svc.find_recruiter_email("Acme", "acme.io")
    assert (result.email, result.source) == ("careers@acme.io", "careers_page") and api.calls == []


@pytest.mark.parametrize("url,addresses,reason", [
    ("https://intranet.acme.io/", ["10.0.0.5"], "resolves_to_private_address"),
    ("https://meta.acme.io/", ["169.254.169.254"], "resolves_to_private_address"),
    ("https://v6.acme.io/", ["::1"], "resolves_to_private_address"),
    ("https://mapped.acme.io/", ["::ffff:127.0.0.1"], "resolves_to_private_address"),
    ("https://127.0.0.1/", ["127.0.0.1"], "ip_literal_not_allowed"),
    ("https://localhost/", ["127.0.0.1"], "host_not_public"),
    ("file:///etc/passwd", [], "scheme_not_allowed"),
    ("https://acme.io:8080/", ["93.184.216.34"], "port_not_allowed"),
    ("https://user:pw@acme.io/", ["93.184.216.34"], "credentials_in_url"),
])
async def test_ssrf_guard_rejects_private_and_odd_targets(url, addresses, reason):
    async def resolver(host):
        return addresses

    with pytest.raises(UnsafeTarget, match=reason):
        await assert_public_url(url, resolver)


async def test_redirect_to_a_private_host_is_blocked():
    def handler(request):
        if request.url.host == "acme.io":
            return httpx.Response(302, headers={"location": "http://internal.acme.io/secrets"})
        return httpx.Response(200, text="admin@acme.io")

    async def resolver(host):
        return ["10.1.2.3"] if host.startswith("internal") else ["93.184.216.34"]

    fetcher = PageFetcher(transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(UnsafeTarget):
        await fetcher.fetch("https://acme.io/careers")


# --- Tier 2 providers ---------------------------------------------------------------------
APOLLO_PEOPLE = {"people": [
    {"first_name": "Asha", "title": "Senior Technical Recruiter", "email": "asha@acme.io",
     "linkedin_url": "https://www.linkedin.com/in/asha-test"},
    {"first_name": "Dev", "title": "Software Engineer", "email": "dev@acme.io"},
    {"first_name": "Hidden", "title": "Recruiter", "email": "email_not_unlocked@domain.com"},
]}


async def test_apollo_finds_a_recruiter_and_spends_exactly_one_credit():
    svc, api = service(Api({"api.apollo.io": APOLLO_PEOPLE}))
    result = await svc.find_recruiter_email("Acme", "acme.io", role_title="Backend Engineer")
    assert (result.email, result.source, result.first_name) == ("asha@acme.io", "apollo", "Asha")
    assert result.credits_spent == {"apollo": 1} and api.hosts() == ["api.apollo.io"]
    body = json.loads(api.calls[0].content)
    assert body["q_organization_domains_list"] == ["acme.io"] and api.calls[0].headers["x-api-key"]
    credit = await svc.store.credit("apollo", "2026-11-26")
    assert (credit.used, credit.limit_cap) == (1, 10)


async def test_apollo_plan_restricted_403_sets_a_24h_cooldown_instead_of_retrying():
    api = Api({"api.apollo.io": (403, {"error": "Your plan does not include this endpoint"}),
               "api.apify.com": [], "signalhire.com": []})
    svc, _ = service(api)
    first = await svc.find_recruiter_email("Acme", "acme.io")
    assert first.status == "NO_EMAIL_FOUND"
    assert {"tier": 2, "provider": "apollo", "outcome": "plan_restricted", "candidates": 0,
            "cooldown_sec": 86400, "error": "http_403_plan_restricted"} in first.attempts
    assert await svc.store.cooldown_until("apollo") == NOW + timedelta(hours=24)
    api.calls.clear()
    await svc.find_recruiter_email("Other", "other.io")
    assert "api.apollo.io" not in api.hosts()  # cooling down: no credit reserved, no call
    assert (await svc.store.credit("apollo", "2026-11-26")).used == 1


async def test_apify_and_signalhire_daily_caps_are_enforced_before_any_call():
    api = Api({"api.apollo.io": {"people": []}, "api.apify.com": [{"emails": ["sales@x.io"]}]})
    svc, _ = service(api, keys={"apify": "TEST_FAKE_TOKEN_ONLY"}, caps={"apollo": 10, "apify": 1, "signalhire": 5})
    await svc.find_recruiter_email("One", "one.io")
    second = await svc.find_recruiter_email("Two", "two.io")
    assert api.hosts() == ["api.apify.com"]  # the second domain never reached Apify
    assert {"tier": 2, "provider": "apify", "outcome": "daily_cap_reached", "cap": 1} in second.attempts
    assert (await svc.store.credit("apify", "2026-11-26")).used == 1
    zero, zero_api = service(keys={"signalhire": "TEST_FAKE_TOKEN_ONLY"}, caps={"apollo": 0, "apify": 0,
                                                                                "signalhire": 0})
    await zero.find_recruiter_email("Three", "three.io")
    assert zero_api.calls == []


async def test_apify_actor_keeps_only_company_domain_addresses():
    api = Api({"api.apify.com": [{"emails": ["jobs@acme.io", "someone@gmail.com", "info@partner.com"]}]})
    svc, _ = service(api, keys={"apify": "TEST_FAKE_TOKEN_ONLY"})
    result = await svc.find_recruiter_email("Acme", "acme.io")
    assert (result.email, result.source) == ("jobs@acme.io", "apify")
    assert api.calls[0].headers["authorization"].startswith("Bearer ") and "token=" not in str(api.calls[0].url)


async def test_signalhire_needs_an_identifier_and_uses_apollo_linkedin_ids():
    alone, alone_api = service(keys={"signalhire": "TEST_FAKE_TOKEN_ONLY"})
    result = await alone.find_recruiter_email("Acme", "acme.io")
    assert alone_api.calls == [] and {"tier": 2, "provider": "signalhire", "outcome": "needs_identifier"} \
        in result.attempts
    no_email_people = {"people": [{"first_name": "Asha", "title": "Recruiter",
                                   "linkedin_url": "https://www.linkedin.com/in/asha-test"}]}
    signalhire = [{"item": "https://www.linkedin.com/in/asha-test", "status": "success", "candidate": {
        "fullName": "Asha Test", "experience": [{"current": True, "position": "Talent Partner"}],
        "contacts": [{"type": "email", "subType": "work", "value": "asha.t@acme.io"}]}}]
    api = Api({"api.apollo.io": no_email_people, "api.apify.com": [], "signalhire.com": signalhire})
    svc, _ = service(api)
    found = await svc.find_recruiter_email("Acme", "acme.io")
    assert (found.email, found.source) == ("asha.t@acme.io", "signalhire")
    assert found.credits_spent == {"apollo": 1, "apify": 1, "signalhire": 1}


async def test_no_email_anywhere_is_a_clean_negative_result_never_a_guess():
    api = Api({"api.apollo.io": {"people": []}, "api.apify.com": [], "signalhire.com": []})
    svc, _ = service(api)
    result = await svc.find_recruiter_email("Acme Labs", "acme.io", jd_text="No contact info here.")
    assert (result.status, result.email) == ("NO_EMAIL_FOUND", None)
    entry = await svc.store.get_cache("acme.io")
    assert (entry.status, entry.expires_at) == ("NO_EMAIL_FOUND", NOW + NOT_FOUND_TTL)


async def test_transient_skips_shorten_the_negative_cache_ttl():
    api = Api({"api.apollo.io": (500, {})})
    svc, _ = service(api, keys={"apollo": "TEST_FAKE_TOKEN_ONLY"})
    result = await svc.find_recruiter_email("Acme", "acme.io")
    assert result.status == "NO_EMAIL_FOUND"
    assert (await svc.store.get_cache("acme.io")).expires_at == NOW + TRANSIENT_NOT_FOUND_TTL


async def test_unconfigured_providers_make_no_http_calls():
    svc, api = service(keys={})
    result = await svc.find_recruiter_email("Acme", "acme.io")
    assert api.calls == [] and result.status == "NO_EMAIL_FOUND"
    assert [a["outcome"] for a in result.attempts if a.get("tier") == 2] == ["unconfigured"] * 3


async def test_company_without_domain_uses_a_name_key_and_no_paid_lookup():
    svc, api = service()
    result = await svc.find_recruiter_email("Initech Pvt Ltd", None, job_url="https://www.naukri.com/job-1")
    assert result.status == "NO_EMAIL_FOUND" and api.calls == []
    assert (await svc.store.get_cache("name:initech")).status == "NO_EMAIL_FOUND"


async def test_status_reports_caps_usage_and_never_keys():
    svc, _ = service(Api({"api.apollo.io": APOLLO_PEOPLE}))
    await svc.find_recruiter_email("Acme", "acme.io")
    status = await svc.status()
    by = {p["provider"]: p for p in status["providers"]}
    assert by["apollo"]["used_today"] == 1 and by["apollo"]["state"] == "available"
    assert by["apify"]["daily_cap"] == 5 and status["cached_domains"] == 1
    assert "TEST_FAKE_TOKEN_ONLY" not in json.dumps(status, default=str)


def test_config_from_env_defaults_overrides_and_period_key_is_ist():
    config = EnrichmentConfig.from_env({"APOLLO_API_KEY": "TEST_FAKE_TOKEN_ONLY", "ENRICHMENT_APIFY_DAILY_CAP": "3",
                                        "ENRICHMENT_SIGNALHIRE_DAILY_CAP": "9999"})
    assert config.caps == {"apollo": 10, "apify": 3, "signalhire": 100}
    assert config.configured("apollo") and not config.configured("apify")
    assert "TEST_FAKE_TOKEN_ONLY" not in repr(build_providers(config))
    assert period_key(datetime(2026, 11, 26, 20, 0, tzinfo=UTC)) == "2026-11-27"
