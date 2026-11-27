"""Milestone 2 ops API: telemetry snapshot, guarded dry-run toggle, Telegram mute sync, rules explain,
breaker reset, profile-hash stamping, semantic-cache explain trace — owner bearer on every route."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.ai_v2.semantic_cache import QuestionContext
from backend.app.api.v1.v2.routers.events import get_event_hub
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerState
from backend.app.browser_v2.telemetry import percentile
from backend.app.events_v2.hub import EventHub
from backend.app.main import app
from backend.tests.test_ai_v2_api import BASE, ai  # noqa: F401 - fixture


@pytest.fixture
def ops(ai):  # noqa: F811
    from backend.app.api.v1.automation_v2 import get_v2_store

    memory = MemoryStore(rules={"lever": PortalRules(platform="lever", enabled=True, auto_apply_enabled=True,
                                                     max_applies_per_day=5, max_applies_per_hour=2),
                                "naukri": PortalRules(platform="naukri", enabled=True,
                                                      auth_status="AUTH_REQUIRED")},
                         profile={"preferences": {"target_roles": ["Backend Engineer"]}})
    hub = EventHub()

    async def store_override():
        yield memory

    app.dependency_overrides[get_v2_store] = store_override
    app.dependency_overrides[get_event_hub] = lambda: hub
    yield memory, hub, ai
    app.dependency_overrides.pop(get_event_hub, None)


async def test_ops_routes_require_owner_bearer(async_client, phase2_auth, ops):
    for method, path in [("GET", "/worker/telemetry"), ("POST", "/worker/dry-run"), ("POST", "/telegram/mute"),
                         ("POST", "/rules/explain"), ("POST", "/portal-rules/lever/breaker/reset"),
                         ("POST", "/semantic-cache/stamp-profile")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_telemetry_snapshot(async_client, phase2_auth, ops):
    memory, _, _ = ops
    await memory.set_worker_control(WorkerState.RUNNING, dry_run=True)
    await memory.worker_heartbeat("RUNNING", current_platform="lever")
    now = datetime.now(UTC)
    for n, lag in ((1, 120), (2, 600)):
        record = await memory.upsert_discovered(JobListing(platform="lever", external_job_id=f"j{n}",
                                                           url="https://jobs.lever.co/x", company="Acme"))
        record = await memory.transition(record, S.APPLYING, "apply_started")
        await memory.transition(record, S.APPLIED, "confirmed", payload={"answers": [
            {"question": "q", "answer": "a", "source": "semantic_cache" if n == 1 else "llm"}]},
            receipt={"timing": {"first_mover_lag_seconds": lag}, "email_verified": n == 1})
    stuck = await memory.upsert_discovered(JobListing(platform="lever", external_job_id="j3", url="https://x"))
    stuck = await memory.transition(stuck, S.APPLYING, "apply_started")
    stuck = await memory.transition(stuck, S.SUBMISSION_UNKNOWN, "confirmation_ambiguous")
    memory.records[("lever", "j3")].updated_at = now - timedelta(hours=30)
    await memory.record_circuit("lever", failures=3, level=1, open_until=now + timedelta(minutes=10),
                                reason="DOM_CHANGED token=abcdefSECRET")
    body = (await async_client.get(f"{BASE}/worker/telemetry", headers=phase2_auth)).json()
    assert body["status"] == "DRY_RUN" and body["worker"]["current_platform"] == "lever"
    portals = {p["platform"]: p for p in body["portals"]}
    assert portals["lever"]["breaker_state"] == "open" and portals["lever"]["health"] == "red"
    assert "abcdefSECRET" not in portals["lever"]["breaker_reason"]
    assert portals["lever"]["applied_today"] == 2 and portals["lever"]["daily_cap"] == 5
    assert portals["naukri"]["health"] == "red" and portals["naukri"]["health_reason"] == "auth_required"
    assert body["first_mover"] == {"p50_seconds": 120, "p95_seconds": 600, "samples": 2}
    kpis = body["kpis"]
    assert kpis["applied_today"] == 2 and kpis["verified_receipts_today"] == 1
    assert kpis["needs_reconciliation"] == 1 and kpis["cache_hit_rate"] == 0.5 and kpis["pending_hitl"] == 0
    assert body["telegram"]["push_budget_per_hour"] >= 1
    assert percentile([], 0.5) is None and percentile([5.0], 0.95) == 5


async def test_dry_run_off_needs_typed_live_and_is_audited(async_client, phase2_auth, ops):
    memory, hub, _ = ops
    sub = hub.subscribe()
    refused = await async_client.post(f"{BASE}/worker/dry-run", headers=phase2_auth, json={"dry_run": False})
    assert refused.status_code == 428 and (await memory.get_worker_control()).dry_run is True
    live = await async_client.post(f"{BASE}/worker/dry-run", headers=phase2_auth,
                                   json={"dry_run": False, "confirm": "LIVE"})
    assert live.status_code == 200 and live.json()["dry_run"] is False
    back = await async_client.post(f"{BASE}/worker/dry-run", headers=phase2_auth, json={"dry_run": True})
    assert back.json()["dry_run"] is True
    outcomes = [e.outcome for e in await memory.list_audit(10, "dashboard_dry_run")]
    assert outcomes == ["ok", "ok", "refused"]
    assert sub.queue.qsize() == 2 and sub.queue.get_nowait().type == "worker.state"


async def test_mute_shares_the_bot_state(async_client, phase2_auth, ops):
    memory, _, _ = ops
    muted = (await async_client.post(f"{BASE}/telegram/mute", headers=phase2_auth, json={"minutes": 60})).json()
    state = await memory.get_telegram_state()
    assert muted["muted_until"] and state.muted_until is not None
    assert timedelta(minutes=59) < state.muted_until - datetime.now(UTC) <= timedelta(minutes=60)
    off = (await async_client.post(f"{BASE}/telegram/mute", headers=phase2_auth, json={"minutes": None})).json()
    assert off["muted_until"] is None and (await memory.get_telegram_state()).muted_until is None
    bad = await async_client.post(f"{BASE}/telegram/mute", headers=phase2_auth, json={"minutes": 99999})
    assert bad.status_code == 422


async def test_rules_explain_reports_each_stage(async_client, phase2_auth, ops):
    body = {"url": "https://jobs.lever.co/acme/123e4567-e89b-42d3-a456-426614174000", "title": "Backend Engineer",
            "company": "Acme", "posted_age_days": 1, "applicants": 20, "description": "Python FastAPI"}
    result = (await async_client.post(f"{BASE}/rules/explain", headers=phase2_auth, json=body)).json()
    assert result["platform"] == "lever" and result["passed"] is True and result["decision"] == "pass"
    names = {c["name"]: c["passed"] for c in result["checks"]}
    assert names["posting_age_and_applicants"] and names["title_matches_target_role"]
    assert result["score"]["total"] == 1.0 and result["score"]["priority"] is not None
    old = (await async_client.post(f"{BASE}/rules/explain", headers=phase2_auth,
                                   json={**body, "posted_age_days": 60})).json()
    assert old["passed"] is False and "posting_too_old" in old["reasons"]


async def test_breaker_reset(async_client, phase2_auth, ops):
    memory, hub, _ = ops
    sub = hub.subscribe()
    await memory.record_circuit("lever", failures=4, level=2, open_until=datetime.now(UTC) + timedelta(hours=1),
                                reason="DOM_CHANGED")
    reset = await async_client.post(f"{BASE}/portal-rules/lever/breaker/reset", headers=phase2_auth)
    assert reset.status_code == 200
    rules = await memory.get_rules("lever")
    assert rules.circuit_level == 0 and rules.circuit_open_until is None and rules.circuit_failures == 0
    assert sub.queue.get_nowait().type == "portal.breaker_changed"
    missing = await async_client.post(f"{BASE}/portal-rules/nope/breaker/reset", headers=phase2_auth)
    assert missing.status_code == 404


async def test_stamp_profile_and_stale_counts(async_client, phase2_auth, ops):
    _, _, runtime = ops
    await runtime.cache.put("screening_qa", "What is your current location?", "Faridabad", "user",
                            context=QuestionContext(field_kind="text"))
    stamped = (await async_client.post(f"{BASE}/semantic-cache/stamp-profile", headers=phase2_auth)).json()
    assert stamped["scope"] == "unstamped" and stamped["stamped"] >= 0 and stamped["stale_remaining"] >= 0
    again = (await async_client.post(f"{BASE}/semantic-cache/stamp-profile", headers=phase2_auth,
                                     json={"scope": "owner_verified"})).json()
    assert again["stale_remaining"] == 0 and again["profile_hash"] == stamped["profile_hash"]
    stats = (await async_client.get(f"{BASE}/semantic-cache/stats", headers=phase2_auth)).json()
    assert stats["stale_entries"] == 0 and stats["profile_hash"] == stamped["profile_hash"]


async def test_cache_explain_trace(async_client, phase2_auth, ops):
    _, _, runtime = ops
    await runtime.cache.put("screening_qa", "Are you willing to work night shifts?", "No", "user")
    trace = (await async_client.post(f"{BASE}/semantic-cache/explain", headers=phase2_auth,
                                     json={"question": "Are you willing to work night shifts?"})).json()
    assert trace["decision"] == "exact_hit" and trace["candidates"][0]["decision"] == "served"
    miss = (await async_client.post(f"{BASE}/semantic-cache/explain", headers=phase2_auth,
                                    json={"question": "Why do you want to join our company?"})).json()
    assert miss["decision"] in ("never_cache", "miss") and miss["reason"]
