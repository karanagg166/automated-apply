"""Milestone 2 API: application proof receipt, owner reconcile, ATS watchlist + SSRF-safe probe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.api.v1.automation_v2 import get_v2_store
from backend.app.api.v1.v2.routers import watchers as watchers_router
from backend.app.api.v1.v2.routers.proof_views import tier_label
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import DEFAULT_RULES, PortalRules
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.browser_v2.watchers import probe as probe_module
from backend.app.main import app

BASE = "/api/v1/v2"


@pytest.fixture
def store():
    memory = MemoryStore(rules=dict(DEFAULT_RULES), profile={
        "full_name": "Test Owner", "preferences": {"target_titles": ["Backend Engineer"],
                                                   "greenhouse_boards": {"acme": "Acme"}}})

    async def override():
        yield memory

    app.dependency_overrides[get_v2_store] = override
    yield memory
    app.dependency_overrides.pop(get_v2_store, None)


async def submitted(store, i, state, *, receipt=None, payload=None):
    record = await store.upsert_discovered(JobListing(platform="greenhouse", external_job_id=str(i),
                                                      url=f"https://example.com/{i}", title="Backend Engineer",
                                                      company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters")
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    return await store.transition(record, state, "confirmed" if state == S.APPLIED else "confirmation_ambiguous",
                                  receipt=receipt, payload=payload)


@pytest.mark.parametrize(("source", "similarity", "match", "label"), [
    ("profile", None, None, "Tier 1 Fact"), ("semantic_cache", 1.0, "exact", "Tier 2 Exact"),
    ("semantic_cache", 0.9612, "semantic", "Tier 3 Semantic 0.96"), ("llm", None, None, "Tier 4 LLM"),
    ("human_hitl", None, None, "HITL Human"), ("resume_picker", None, None, "Resume"), ("weird", None, None, "Unknown"),
])
def test_tier_labels(source, similarity, match, label):
    assert tier_label(source, similarity, match) == label


async def test_proof_receipt_timing_answers_and_safe_screenshot(async_client, phase2_auth, store):
    receipt = {"source": "dom", "screenshot": "/Users/someone/Library/receipts/greenhouse-1.png",
               "resume_variant_used": "backend", "email_verified": True, "confirmed_at": "2026-11-28T06:00:00+00:00",
               "timing": {"posted_at": "2026-11-28T04:00:00+00:00", "started_at": "2026-11-28T05:00:00+00:00",
                          "submitted_at": "2026-11-28T05:01:00+00:00", "first_mover_lag_seconds": 3660},
               "answers": [{"question": "Authorized in India?", "answer": "Yes", "source": "profile"},
                           {"question": "Notice period?", "answer": "Immediately", "source": "semantic_cache",
                            "similarity": 0.9612, "cache_entry_id": "abc-1"},
                           {"question": "Why us?", "answer": "Because", "source": "llm"}]}
    record = await submitted(store, 1, S.APPLIED, receipt=receipt)
    response = await async_client.get(f"{BASE}/applications/{record.id}/proof", headers=phase2_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["screenshot"] == "greenhouse-1.png" and "/Users" not in response.text
    assert [a["tier_label"] for a in body["answers"]] == ["Tier 1 Fact", "Tier 3 Semantic 0.96", "Tier 4 LLM"]
    assert body["answers"][1]["cache_entry_id"] == "abc-1"
    assert body["timing"]["first_mover_lag_seconds"] == 3660 and body["timing"]["queued_at"] is not None
    assert body["resume_variant_used"] == "backend" and body["email_verified"] is True
    assert body["needs_reconciliation"] is False and body["outreach_draft"] is None
    missing = await async_client.get(f"{BASE}/applications/00000000-0000-0000-0000-000000000000/proof", headers=phase2_auth)
    assert missing.status_code == 404


async def test_reconcile_confirm_and_release(async_client, phase2_auth, store):
    unknown = await submitted(store, 1, S.SUBMISSION_UNKNOWN)
    store.records[("greenhouse", "1")].updated_at = datetime.now(UTC) - timedelta(hours=30)
    proof = (await async_client.get(f"{BASE}/applications/{unknown.id}/proof", headers=phase2_auth)).json()
    assert proof["needs_reconciliation"] is True
    url = f"{BASE}/applications/{unknown.id}/reconcile"
    refused = await async_client.post(url, headers=phase2_auth, json={"action": "release_not_submitted", "confirm": "yes"})
    assert refused.status_code == 422
    since = datetime.now(UTC) - timedelta(days=2)
    assert await store.ambiguous_submits_since("greenhouse", since) == 1
    released = await async_client.post(url, headers=phase2_auth, json={"action": "release_not_submitted", "confirm": "RELEASE"})
    assert released.status_code == 200 and released.json()["state"] == "FAILED"
    assert released.json()["reason"] == "owner_verified_not_submitted"
    assert await store.ambiguous_submits_since("greenhouse", since) == 0
    again = await async_client.post(url, headers=phase2_auth, json={"action": "confirm_applied"})
    assert again.status_code == 409  # only SUBMISSION_UNKNOWN rows
    other = await submitted(store, 2, S.SUBMISSION_UNKNOWN)
    confirmed = await async_client.post(f"{BASE}/applications/{other.id}/reconcile", headers=phase2_auth, json={"action": "confirm_applied"})
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "APPLIED"


async def test_watchlist_list_add_pause_resume(async_client, phase2_auth, store):
    rows = (await async_client.get(f"{BASE}/portals/watchers", headers=phase2_auth)).json()
    assert {(r["platform"], r["slug"], r["active"]) for r in rows} >= {("greenhouse", "acme", True)}
    added = await async_client.post(f"{BASE}/portals/watchers", headers=phase2_auth, json={"platform": "lever", "slug": "globex"})
    assert added.status_code == 200 and added.json()["board_url"] == "https://jobs.lever.co/globex"
    assert store.profile["preferences"]["lever_boards"] == {"globex": None}
    paused = await async_client.post(f"{BASE}/portals/watchers", headers=phase2_auth,
                                     json={"platform": "greenhouse", "slug": "acme", "active": False})
    assert paused.json()["active"] is False
    assert store.profile["preferences"]["paused_watch_boards"] == ["greenhouse:acme"]
    from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter

    adapter = GreenhouseAdapter()
    adapter.configure(store.profile)
    assert "acme" not in adapter.boards  # the sweep honours the pause too
    resumed = await async_client.post(f"{BASE}/portals/watchers", headers=phase2_auth,
                                      json={"platform": "greenhouse", "slug": "acme", "active": True})
    assert resumed.json()["active"] is True and store.profile["preferences"]["paused_watch_boards"] == []
    bad = await async_client.post(f"{BASE}/portals/watchers", headers=phase2_auth, json={"platform": "workday", "slug": "x"})
    assert bad.status_code == 422


@pytest.mark.parametrize("target", [
    "http://boards.greenhouse.io/acme",            # non-HTTPS
    "https://127.0.0.1/careers",                    # loopback literal
    "https://10.0.0.5/jobs",                        # private literal
    "https://169.254.169.254/latest/meta-data",     # link-local metadata
    "https://user:pw@careers.example.com/jobs",     # credentials
    "file:///etc/passwd",                           # non-HTTP scheme
    "https://intranet.local/jobs",                  # local-only TLD
])
async def test_probe_rejects_unsafe_targets(async_client, phase2_auth, store, target):
    response = await async_client.post(f"{BASE}/portals/watchers/probe", headers=phase2_auth, json={"target": target})
    assert response.status_code == 422, (target, response.text)


async def test_probe_dns_to_private_address_is_refused():
    async def resolver(host):
        return ["192.168.1.10"]

    with pytest.raises(probe_module.ProbeError) as error:
        await probe_module.guarded_page("https://careers.example.com/jobs", resolver=resolver)
    assert error.value.code == "unsafe_url"


def test_detection_from_urls_and_html():
    assert probe_module.board_from_url("https://boards.greenhouse.io/embed/job_board?for=acme").slug == "acme"
    assert probe_module.board_from_url("https://jobs.lever.co/globex/abc").slug == "globex"
    assert probe_module.board_from_url("https://boards-api.greenhouse.io/v1/boards/initech/jobs").slug == "initech"
    ref = probe_module.board_from_html('<iframe src="https://jobs.ashbyhq.com/umbrella?embed=true"></iframe>')
    assert (ref.platform, ref.slug) == ("ashby", "umbrella")


async def test_probe_reads_only_the_fixed_ats_host_and_scores_sample():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        assert request.url.host == "boards-api.greenhouse.io"
        now = datetime.now(UTC).isoformat()
        return httpx.Response(200, json={"jobs": [
            {"id": 11, "title": "Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/11",
             "updated_at": now, "first_published": now, "location": {"name": "Remote"}},
            {"id": 12, "title": "Head of Sales", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/12",
             "updated_at": now, "first_published": now, "location": {"name": "Remote"}}]})

    async def page(url):
        return '<a href="https://boards.greenhouse.io/acme">Jobs</a>'

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ref = await probe_module.detect_board("https://careers.example.com/", page_fetcher=page)
        result = await probe_module.probe(f"{ref.platform}:{ref.slug}", rules=PortalRules(platform="greenhouse"),
                                          preferences={"target_titles": ["Backend Engineer"],
                                                       "greenhouse_boards": {"acme": None}}, client=client)
    assert seen == ["boards-api.greenhouse.io"]
    assert (result["platform"], result["slug"], result["already_watched"]) == ("greenhouse", "acme", True)
    assert result["job_count"] == 2 and result["sample"][0]["title"] == "Backend Engineer"
    assert result["matched_count"] == sum(1 for s in result["sample"] if s["passes"])


async def test_probe_endpoint_uses_seam(async_client, phase2_auth, store, monkeypatch):
    async def fake(target, store):
        return {"platform": "lever", "slug": "globex", "board_url": "https://jobs.lever.co/globex", "job_count": 3,
                "matched_count": 1, "sample": [], "already_watched": False}

    monkeypatch.setattr(watchers_router, "_probe", fake)
    response = await async_client.post(f"{BASE}/portals/watchers/probe", headers=phase2_auth, json={"target": "lever:globex"})
    assert response.status_code == 200 and response.json()["job_count"] == 3
