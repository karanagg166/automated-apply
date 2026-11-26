"""v2 control-plane API: portal rules CRUD, screening facts, applications, status, worker control."""

from dataclasses import replace

import pytest

from backend.app.api.v1.automation_v2 import get_v2_store
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import DEFAULT_RULES
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.main import app

BASE = "/api/v1/v2"


@pytest.fixture
def store():
    memory = MemoryStore(rules=dict(DEFAULT_RULES))

    async def override():
        yield memory

    app.dependency_overrides[get_v2_store] = override
    yield memory
    app.dependency_overrides.pop(get_v2_store, None)


async def test_every_v2_route_requires_owner_bearer(async_client, phase2_auth, store):
    for method, path in [("GET", "/portal-rules"), ("PATCH", "/portal-rules/naukri"),
                         ("GET", "/screening-profile"), ("GET", "/status"), ("GET", "/applications"),
                         ("POST", "/worker/start"), ("POST", "/worker/run-once")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_portal_rules_list_and_patch_increments_revision(async_client, phase2_auth, store):
    listed = (await async_client.get(f"{BASE}/portal-rules", headers=phase2_auth)).json()
    naukri = next(r for r in listed if r["platform"] == "naukri")
    assert naukri["max_applies_per_day"] == 50 and naukri["active_hours_start"] == "08:00"
    assert {r["platform"] for r in listed} == {"naukri", "instahyre", "internshala", "himalayas", "wellfound", "work_at_a_startup", "we_work_remotely", "hiringcafe", "greenhouse", "lever", "ashby", "smartrecruiters", "remotive", "arbeitnow", "hacker_news"}
    response = await async_client.patch(f"{BASE}/portal-rules/naukri", headers=phase2_auth, json={
        "revision": naukri["revision"], "max_applies_per_day": 40, "max_job_age_days": 5,
        "unknown_applicants_policy": "needs_review", "min_delay_sec": 60, "max_delay_sec": 120,
        "active_hours_start": "09:30", "auto_apply_enabled": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == naukri["revision"] + 1 and body["max_applies_per_day"] == 40
    assert body["active_hours_start"] == "09:30" and body["unknown_applicants_policy"] == "needs_review"
    # Worker reads the same store row on its next cycle: no restart needed.
    assert (await store.get_rules("naukri")).max_job_age_days == 5


async def test_stale_revision_is_409(async_client, phase2_auth, store):
    first = await async_client.patch(f"{BASE}/portal-rules/naukri", headers=phase2_auth,
                                     json={"revision": 1, "enabled": False})
    assert first.status_code == 200
    stale = await async_client.patch(f"{BASE}/portal-rules/naukri", headers=phase2_auth,
                                     json={"revision": 1, "enabled": True})
    assert stale.status_code == 409 and "revision 2" in stale.json()["detail"]


@pytest.mark.parametrize("patch", [
    {"min_delay_sec": 4},
    {"min_delay_sec": 200, "max_delay_sec": 100},
    {"max_delay_sec": 30},  # below current min 45
    {"max_applies_per_day": 0},
    {"max_applies_per_hour": 60},  # above current per-day 50
    {"max_job_age_days": 0},
    {"unknown_applicants_policy": "maybe"},
    {"timezone": "Mars/Olympus"},
    {"enabled": None},
    {"auth_status": "OK"},  # system-managed
    {},
])
async def test_portal_rule_validation(async_client, phase2_auth, store, patch):
    response = await async_client.patch(f"{BASE}/portal-rules/naukri", headers=phase2_auth,
                                        json={"revision": 1, **patch})
    assert response.status_code == 422, (patch, response.text)
    assert (await store.get_rules("naukri")).revision == 1


async def test_unknown_portal_is_404(async_client, phase2_auth, store):
    response = await async_client.patch(f"{BASE}/portal-rules/linkedin", headers=phase2_auth,
                                        json={"revision": 1, "enabled": True})
    assert response.status_code == 404


async def test_worker_control_persists_desired_state(async_client, phase2_auth, store):
    started = (await async_client.post(f"{BASE}/worker/start", headers=phase2_auth,
                                       json={"dry_run": False})).json()
    assert started["desired_state"] == "RUNNING" and started["dry_run"] is False and started["stale"]
    assert store.worker.desired_state.value == "RUNNING"
    default_start = (await async_client.post(f"{BASE}/worker/start", headers=phase2_auth)).json()
    assert default_start["dry_run"] is False  # unchanged when omitted
    assert (await async_client.post(f"{BASE}/worker/pause", headers=phase2_auth)).json()["desired_state"] == "PAUSED"
    once = (await async_client.post(f"{BASE}/worker/run-once", headers=phase2_auth)).json()
    assert once["desired_state"] == "PAUSED" and once["run_once_requested_at"]
    assert (await async_client.post(f"{BASE}/worker/stop", headers=phase2_auth)).json()["desired_state"] == "STOPPED"
    bad = await async_client.post(f"{BASE}/worker/start", headers=phase2_auth, json={"dry_run": "no"})
    assert bad.status_code == 422


async def test_status_reports_quota_auth_and_waiting_queue(async_client, phase2_auth, store):
    store.rules["naukri"] = replace(store.rules["naukri"], max_applies_per_day=2)
    for i, target in ((1, S.APPLIED), (2, S.WAITING_FOR_USER)):
        record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=str(i),
                                                          url=f"https://example.com/{i}"))
        record = await store.transition(record, S.APPLYING, "apply_started")
        await store.transition(record, target, "test")
    await store.record_auth("instahyre", "AUTH_REQUIRED")
    body = (await async_client.get(f"{BASE}/status", headers=phase2_auth)).json()
    assert body["gmail_permission_label"] == "Gmail Permission: Read + Draft Only (Sending Disabled)"
    assert body["waiting_for_user"] == 1 and body["worker"]["desired_state"] == "STOPPED"
    by = {p["platform"]: p for p in body["portals"]}
    assert by["naukri"]["applied_today"] == 1 and by["naukri"]["applied_this_hour"] == 1
    assert by["naukri"]["max_applies_per_day"] == 2 and not by["naukri"]["daily_limit_hit"]
    assert by["naukri"]["waiting_for_user"] == 1 and by["instahyre"]["auth_status"] == "AUTH_REQUIRED"


async def test_applications_filter_and_events(async_client, phase2_auth, store):
    for i in range(3):
        record = await store.upsert_discovered(JobListing(
            platform="naukri", external_job_id=str(i), url=f"https://example.com/{i}",
            title="Python Developer", company=f"Co {i}"))
        if i == 0:
            await store.transition(record, S.FILTERED_OUT, "company_blacklisted: Co 0")
    page = (await async_client.get(f"{BASE}/applications", params={"state": "FILTERED_OUT"},
                                   headers=phase2_auth)).json()
    assert page["total"] == 1 and page["items"][0]["reason"] == "company_blacklisted: Co 0"
    everything = (await async_client.get(f"{BASE}/applications", params={"platform": "naukri", "limit": 2},
                                         headers=phase2_auth)).json()
    assert everything["total"] == 3 and len(everything["items"]) == 2
    events = (await async_client.get(f"{BASE}/applications/{page['items'][0]['id']}/events",
                                     headers=phase2_auth)).json()
    assert events[0]["to_state"] == "FILTERED_OUT" and events[0]["event_type"] == "company_blacklisted: Co 0"
    assert (await async_client.get(f"{BASE}/applications", params={"state": "NOPE"},
                                   headers=phase2_auth)).status_code == 422
    missing = await async_client.get(f"{BASE}/applications/00000000-0000-0000-0000-000000000000/events",
                                     headers=phase2_auth)
    assert missing.status_code == 404


async def test_screening_profile_round_trip_and_version_conflict(async_client, phase2_auth, phase2_profile):
    current = (await async_client.get(f"{BASE}/screening-profile", headers=phase2_auth)).json()
    assert current["has_profile"] and current["notice_period_days"] == 30 and current["target_roles"] == []
    response = await async_client.patch(f"{BASE}/screening-profile", headers=phase2_auth, json={
        "version": current["version"], "current_ctc": 6, "expected_ctc": 10.5, "min_ctc": 9,
        "total_experience_years": 2, "current_location": "Bengaluru", "willing_to_relocate": False,
        "skill_years": {"python": 2, "react": 2, "typescript": 2, "postgresql": 2},
        "target_roles": ["Python Developer", "Backend Engineer"], "keywords_excluded": ["php"],
        "company_blacklist": ["Acme"], "remote_policy": "hybrid_ok"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == current["version"] + 1 and body["expected_ctc"] == 10.5
    assert body["skill_years"]["python"] == 2 and body["notice_period_days"] == 30  # untouched keys kept
    stale = await async_client.patch(f"{BASE}/screening-profile", headers=phase2_auth,
                                     json={"version": current["version"], "current_ctc": 7})
    assert stale.status_code == 409
    # The existing profile API still validates and preserves the new keys.
    profile = (await async_client.get("/api/v1/profile", headers=phase2_auth)).json()
    assert profile["preferences"]["company_blacklist"] == ["Acme"]


@pytest.mark.parametrize("patch", [
    {"current_ctc": -1}, {"notice_period_days": 5000}, {"remote_policy": "mars"},
    {"skill_years": {"python": 99}}, {"willing_to_relocate": "yes"}, {"surprise": 1},
])
async def test_screening_profile_validation(async_client, phase2_auth, phase2_profile, patch):
    response = await async_client.patch(f"{BASE}/screening-profile", headers=phase2_auth,
                                        json={"version": phase2_profile.version, **patch})
    assert response.status_code == 422, patch


async def test_screening_profile_without_profile(async_client, phase2_auth):
    body = (await async_client.get(f"{BASE}/screening-profile", headers=phase2_auth)).json()
    assert body["has_profile"] is False
    response = await async_client.patch(f"{BASE}/screening-profile", headers=phase2_auth,
                                        json={"version": 1, "current_ctc": 5})
    assert response.status_code == 404


async def test_sqlite_without_v2_tables_returns_503(async_client, phase2_auth):
    response = await async_client.get(f"{BASE}/portal-rules", headers=phase2_auth)
    assert response.status_code == 503
