"""Phase 9B store foundation: early-bird priority queue, circuit breaker, watcher state.

Every behavioural test runs against MemoryStore AND PostgresStore (disposable PostgreSQL with
followups 004 + 005) so both implementations stay identical.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    Decision,
    evaluate_experience,
)
from backend.app.browser_v2.schemas import PortalRulesPatch, PortalRulesRead
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import (
    SEEN_IDS_CAP,
    DiscoveryMeta,
    MemoryStore,
    PostgresStore,
    WatcherState,
)
from backend.tests.test_browser_v2_postgres_store import database  # noqa: F401 - module fixture
from backend.tests.test_v2_migration_sql import PG_BIN

NO_PG = PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1"


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield MemoryStore()
        return
    if NO_PG:
        pytest.skip("local PostgreSQL binaries not available")
    import asyncpg

    connection = await asyncpg.connect(request.getfixturevalue("database"))
    await connection.execute("TRUNCATE public.application_state_events, public.hitl_requests, "
                             "public.applications, public.watcher_state CASCADE")
    await connection.execute("UPDATE public.portal_rules SET circuit_failures=0, circuit_level=0, "
                             "circuit_open_until=NULL, circuit_reason=NULL, last_fresh_sweep_at=NULL")
    yield await PostgresStore.borrowed(connection)
    await connection.close()


def listing(i: int, platform: str = "naukri") -> JobListing:
    return JobListing(platform=platform, external_job_id=f"{platform}-{i}", url=f"https://example.com/{i}",
                      title="Python Developer", company="Acme")


async def backdate(store, record, *, hours: float) -> None:
    """Pretend the row was discovered `hours` ago."""
    at = datetime.now(UTC) - timedelta(hours=hours)
    if isinstance(store, MemoryStore):
        store.records[(record.platform, record.external_job_id)].created_at = at
    else:
        await store.connection.execute("UPDATE public.applications SET created_at=$2 WHERE id=$1::uuid",
                                        record.id, at)


async def test_insert_then_existing_and_least_promotion(store):
    first = await store.upsert_discovered_meta(listing(1), None)
    assert first.inserted and not first.promoted
    assert (first.record.priority, first.record.priority_reason) == (2, None)
    again = await store.upsert_discovered_meta(listing(1), DiscoveryMeta(priority=2, priority_reason="same"))
    assert not again.inserted and not again.promoted and again.record.id == first.record.id
    promoted = await store.upsert_discovered_meta(
        listing(1), DiscoveryMeta(priority=0, priority_reason="posted_within_2h", discovered_via="naukri:fresh"))
    assert promoted.promoted and promoted.record.priority == 0
    assert promoted.record.priority_reason == "posted_within_2h" and promoted.record.discovered_via == "naukri:fresh"
    lower = await store.upsert_discovered_meta(
        listing(1), DiscoveryMeta(priority=1, priority_reason="posted_within_24h", discovered_via="naukri:other"))
    assert not lower.promoted and lower.record.priority == 0
    assert lower.record.priority_reason == "posted_within_2h" and lower.record.discovered_via == "naukri:fresh"
    assert lower.record.state is S.DISCOVERED and lower.record.version == first.record.version
    legacy = await store.upsert_discovered(listing(2), DiscoveryMeta(priority=1, priority_reason="job_alert_email"))
    assert legacy.priority == 1 and (await store.upsert_discovered(listing(2))).priority == 1
    assert legacy.public()["priority"] == 1 and "posted_precision" in legacy.public()


async def test_terminal_and_in_flight_rows_are_never_reprioritised(store):
    applied = await store.upsert_discovered(listing(1))
    applied = await store.transition(applied, S.APPLYING, "apply_started")
    applied = await store.transition(applied, S.APPLIED, "confirmation_text")
    filtered = await store.transition(await store.upsert_discovered(listing(2)), S.FILTERED_OUT, "title")
    waiting = await store.transition(await store.upsert_discovered(listing(3)), S.APPLYING, "apply_started")
    waiting = await store.transition(waiting, S.WAITING_FOR_USER, "question")
    for record in (applied, filtered, waiting):
        result = await store.upsert_discovered_meta(listing(int(record.external_job_id.rsplit("-", 1)[1])),
                                                    DiscoveryMeta(priority=0, priority_reason="owner_requested"))
        assert not result.promoted and result.record.priority == 2 and result.record.state == record.state
        assert result.record.version == record.version
    scored = await store.transition(await store.upsert_discovered(listing(4)), S.SCORED, "passed_filters")
    assert (await store.upsert_discovered_meta(listing(4), DiscoveryMeta(priority=0))).promoted
    assert (await store.get_application(scored.id)).version == scored.version


async def test_posted_at_filled_and_upgraded_only_by_better_precision(store):
    day = datetime(2026, 11, 25, tzinfo=UTC)
    hour = datetime(2026, 11, 25, 9, 15, tzinfo=UTC)
    first = await store.upsert_discovered_meta(listing(1), DiscoveryMeta(posted_at=day, posted_precision="day"))
    assert (first.record.posted_at, first.record.posted_precision) == (day, "day")
    same = await store.upsert_discovered_meta(listing(1), DiscoveryMeta(posted_at=hour, posted_precision="unknown"))
    assert (same.record.posted_at, same.record.posted_precision) == (day, "day")
    better = await store.upsert_discovered_meta(listing(1), DiscoveryMeta(posted_at=hour, posted_precision="hour"))
    assert (better.record.posted_at, better.record.posted_precision) == (hour, "hour")
    worse = await store.upsert_discovered_meta(listing(1), DiscoveryMeta(posted_at=day, posted_precision="day"))
    assert (worse.record.posted_at, worse.record.posted_precision) == (hour, "hour")
    blank = await store.upsert_discovered(listing(2))
    filled = await store.upsert_discovered_meta(listing(2), DiscoveryMeta(posted_at=day))
    assert blank.posted_at is None and (filled.record.posted_at, filled.record.posted_precision) == (day, "unknown")


async def test_list_by_state_orders_by_tier_then_newest_and_honours_retry_after(store):
    now = datetime.now(UTC)
    old = await store.upsert_discovered(listing(1), DiscoveryMeta(posted_at=now - timedelta(days=3)))
    new = await store.upsert_discovered(listing(2), DiscoveryMeta(posted_at=now - timedelta(hours=5)))
    urgent = await store.upsert_discovered(listing(3), DiscoveryMeta(priority=1, posted_at=now - timedelta(days=6)))
    backlog = await store.upsert_discovered(listing(4), DiscoveryMeta(priority=3))
    blocked = await store.transition(await store.upsert_discovered(listing(5), DiscoveryMeta(priority=0)),
                                     S.FAILED, "transient", retry_after=now + timedelta(hours=1))
    due = await store.transition(await store.upsert_discovered(listing(6)), S.FAILED, "transient",
                                 retry_after=now - timedelta(minutes=1))
    rows = await store.list_by_state("naukri", (S.DISCOVERED, S.FAILED))
    assert [r.id for r in rows] == [urgent.id, due.id, new.id, old.id, backlog.id]
    assert blocked.id not in {r.id for r in rows}
    assert [r.id for r in await store.list_by_state("naukri", (S.DISCOVERED,), limit=2)] == [urgent.id, new.id]


async def test_priority_candidates_skip_open_hitl_terminal_and_low_tiers(store):
    now = datetime.now(UTC)
    p0 = await store.upsert_discovered(listing(1), DiscoveryMeta(priority=0, posted_at=now - timedelta(hours=1)))
    p1 = await store.transition(await store.upsert_discovered(listing(2), DiscoveryMeta(priority=1)),
                                S.SCORED, "passed_filters")
    asked = await store.transition(await store.upsert_discovered(listing(3), DiscoveryMeta(priority=0)),
                                   S.SCORED, "passed_filters")
    await store.create_hitl(asked, "naukri", "QUESTION", "Notice period?", {})
    done = await store.transition(await store.upsert_discovered(listing(4), DiscoveryMeta(priority=0)),
                                  S.APPLYING, "apply_started")
    await store.transition(done, S.APPLIED, "confirmation_text")
    await store.upsert_discovered(listing(5))  # P2: below the default max_priority
    await store.transition(await store.upsert_discovered(listing(6), DiscoveryMeta(priority=0)), S.SCORED, "ok",
                           retry_after=now + timedelta(hours=2))
    other = await store.upsert_discovered(listing(7, platform="greenhouse"), DiscoveryMeta(priority=1))
    rows = await store.priority_candidates(now)
    assert [r.id for r in rows] == [p0.id, p1.id, other.id] or [r.id for r in rows] == [p0.id, other.id, p1.id]
    assert [r.id for r in await store.priority_candidates(now, platforms=["greenhouse"])] == [other.id]
    assert [r.id for r in await store.priority_candidates(now, max_priority=0)] == [p0.id]
    assert len(await store.priority_candidates(now, max_priority=3, limit=2)) == 2
    assert len(await store.priority_candidates(now, max_priority=3)) == 4


async def test_set_priority_keeps_version_and_state(store):
    record = await store.transition(await store.upsert_discovered(listing(1)), S.SCORED, "passed_filters")
    assert await store.set_priority(record.id, 0, "owner_requested")
    fresh = await store.get_application(record.id)
    assert (fresh.priority, fresh.priority_reason, fresh.version, fresh.state) == (
        0, "owner_requested", record.version, S.SCORED)
    await store.transition(record, S.APPLYING, "apply_started")  # optimistic version still valid
    assert not await store.set_priority("00000000-0000-0000-0000-000000000000", 1, None)
    with pytest.raises(ValueError):
        await store.set_priority(record.id, 4, "bad")


async def test_decay_moves_stale_tiers_down_only_for_queued_rows(store):
    now = datetime.now(UTC)
    fresh_p0 = await store.upsert_discovered(listing(1), DiscoveryMeta(priority=0))
    stale_p0 = await store.upsert_discovered(listing(2), DiscoveryMeta(priority=0))
    ancient_p0 = await store.upsert_discovered(listing(3), DiscoveryMeta(priority=0))
    stale_p1 = await store.upsert_discovered(listing(4), DiscoveryMeta(priority=1))
    young_p1 = await store.upsert_discovered(listing(5), DiscoveryMeta(priority=1))
    applied = await store.upsert_discovered(listing(6), DiscoveryMeta(priority=0))
    await store.transition(await store.transition(applied, S.APPLYING, "go"), S.APPLIED, "done")
    for record, hours in ((stale_p0, 3), (ancient_p0, 30), (stale_p1, 27), (young_p1, 25), (applied, 40)):
        await backdate(store, record, hours=hours)
    assert await store.decay_priorities(now) == 3
    tiers = {r.id: (r.priority, r.priority_reason) for r in [await store.get_application(x.id) for x in
                                                             (fresh_p0, stale_p0, ancient_p0, stale_p1, young_p1,
                                                              applied)]}
    assert tiers[fresh_p0.id][0] == 0 and tiers[young_p1.id][0] == 1 and tiers[applied.id][0] == 0
    assert tiers[stale_p0.id] == (1, "decayed_from_p0") and tiers[ancient_p0.id] == (2, "decayed_from_p0")
    assert tiers[stale_p1.id] == (2, "decayed_from_p1")
    assert await store.decay_priorities(now) == 0


async def test_circuit_and_fresh_sweep_round_trip(store):
    until = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    await store.record_circuit("naukri", failures=3, level=2, open_until=until, reason="x" * 400)
    await store.record_fresh_sweep("naukri", until - timedelta(hours=1))
    rules = await store.get_rules("naukri")
    assert (rules.circuit_failures, rules.circuit_level, rules.circuit_open_until) == (3, 2, until)
    assert rules.circuit_reason == "x" * 300 and rules.last_fresh_sweep_at == until - timedelta(hours=1)
    assert rules.revision == 1  # system-managed: never conflicts with an open dashboard form
    read = PortalRulesRead.from_rules(rules)
    assert (read.circuit_level, read.circuit_open_until) == (2, until)
    with pytest.raises(Exception, match="extra"):
        PortalRulesPatch.model_validate({"revision": 1, "circuit_level": 0})
    await store.record_circuit("naukri", failures=0, level=0, open_until=None, reason=None)
    assert (await store.get_rules("naukri")).circuit_open_until is None
    with pytest.raises(ValueError):
        await store.record_circuit("naukri", failures=1, level=11, open_until=None, reason=None)


async def test_watcher_state_round_trip_and_seen_ids_cap(store):
    assert await store.get_watcher_state("greenhouse:stripe") is None
    state = WatcherState(source="greenhouse:stripe", etag='W/"abc"', body_hash="a" * 64,
                         seen_ids=tuple(str(i) for i in range(2100)), last_status=200,
                         budget_day=datetime(2026, 11, 27).date(), budget_used=4,
                         baseline_at=datetime(2026, 11, 27, 1, tzinfo=UTC))
    assert len(state.seen_ids) == SEEN_IDS_CAP and state.seen_ids[0] == "100" and state.seen_ids[-1] == "2099"
    saved = await store.save_watcher_state(state)
    loaded = await store.get_watcher_state("greenhouse:stripe")
    assert loaded == saved == state and loaded.updated_at is not None
    bumped = await store.save_watcher_state(replace(loaded.with_seen(["2100", "100"]), etag=None, failures=2))
    assert bumped.seen_ids[-2:] == ("2100", "100") and "101" not in bumped.seen_ids and bumped.seen_ids[0] == "102"
    assert (await store.get_watcher_state("greenhouse:stripe")) == bumped and bumped.etag is None
    with pytest.raises(ValueError):
        WatcherState(source="Bad Source")


async def test_phase9_ready(store):
    assert await store.phase9_ready() is True


async def test_postgres_phase9_ready_false_without_the_migration():
    class Broken:
        async def fetchval(self, *args):
            raise RuntimeError('column "priority" does not exist')

    assert await PostgresStore(Broken(), owns_connection=False).phase9_ready() is False


def test_discovery_meta_validation():
    with pytest.raises(ValueError):
        DiscoveryMeta(priority=4)
    with pytest.raises(ValueError):
        DiscoveryMeta(posted_precision="minute")
    with pytest.raises(ValueError):
        DiscoveryMeta(discovered_via="Bad Via")
    meta = DiscoveryMeta(priority_reason="r" * 300, posted_at=datetime(2026, 11, 27, 9))
    assert len(meta.priority_reason or "") == 200 and meta.posted_at is not None and meta.posted_at.tzinfo is UTC


@pytest.mark.parametrize(("text", "decision"), [
    ("Fresher", Decision.PASS), ("0-2 yrs", Decision.PASS), ("1-3 yrs", Decision.FILTERED),
    ("3+ years", Decision.FILTERED), (None, Decision.PASS),
])
def test_experience_max_rule_with_max_zero(text, decision):
    prefs = CandidatePreferences.from_profile({"preferences": {"max_required_experience_years": 0,
                                                               "total_experience_years": 5}})
    result = evaluate_experience(text, prefs)
    assert result.decision is decision
    if decision is Decision.FILTERED and text == "1-3 yrs":
        assert result.reasons == ("experience_above_max: needs 1-3 yrs, max 0",)


def test_experience_without_max_keeps_the_tolerance_rule():
    prefs = CandidatePreferences.from_profile({"preferences": {"total_experience_years": 1}})
    assert prefs.max_required_experience_years is None
    assert evaluate_experience("2-4 yrs", prefs).decision is Decision.PASS
    assert evaluate_experience("3-5 yrs", prefs).reasons[0].startswith("experience_above_profile")


def test_new_preference_fields_validate_and_are_settable():
    from backend.app.browser_v2.facts_cli import SETTABLE
    from backend.app.browser_v2.schemas.screening import SCREENING_FIELDS
    from backend.app.schemas.candidate_profile import JobSearchPreferences

    new = ("max_required_experience_years", "headline", "internship_months", "graduation_month",
           "open_to_internships", "notify_early_bird")
    assert set(new) <= set(SETTABLE) and set(new) <= set(SCREENING_FIELDS)
    ok = JobSearchPreferences.model_validate({"max_required_experience_years": 1.5, "headline": "Backend dev",
                                              "internship_months": 6, "graduation_month": "2026-06",
                                              "open_to_internships": True, "notify_early_bird": False})
    assert ok.graduation_month == "2026-06"
    for bad in ({"max_required_experience_years": 31}, {"headline": "h" * 251}, {"internship_months": 61},
                {"graduation_month": "2026-13"}, {"graduation_month": "June 2026"}, {"notify_early_bird": "yes"}):
        with pytest.raises(ValueError):
            JobSearchPreferences.model_validate(bad)


async def test_facts_set_writes_new_keys():
    from backend.app.browser_v2.facts_cli import set_fact

    store = MemoryStore(profile={"full_name": "Test", "preferences": {}})
    assert (await set_fact(store, "max_required_experience_years", "2"))["ok"]
    assert (await set_fact(store, "notify_early_bird", "yes"))["ok"]
    assert not (await set_fact(store, "graduation_month", "2026/06"))["ok"]
    assert store.profile["preferences"] == {"max_required_experience_years": 2.0, "notify_early_bird": True}
