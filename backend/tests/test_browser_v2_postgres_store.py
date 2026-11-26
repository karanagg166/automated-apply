"""PostgresStore SQL against a disposable local PostgreSQL with migration 004 applied.

Covers the live control plane: portal_rules revisioned CRUD, worker_control
persistence (restart resumes RUNNING), state transitions + append-only events,
cross-portal dedup lookups, HITL rows, and the API's borrowed pooled connection.
"""

import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import (
    ApplicationQuery,
    PostgresStore,
    RevisionConflict,
    RulesNotFound,
    WorkerState,
)
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")

BOOTSTRAP = """
CREATE ROLE job_agent_owner NOLOGIN; CREATE ROLE job_agent_runtime NOLOGIN CONNECTION LIMIT 5;
GRANT job_agent_owner TO postgres;
CREATE TABLE public.jobs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), title text);
CREATE TABLE public.candidate_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), singleton_key text UNIQUE,
    verified_experience_years numeric, verified_skills jsonb NOT NULL DEFAULT '[]',
    preferences jsonb NOT NULL DEFAULT '{}');
CREATE TABLE public.application_answer_drafts (
    candidate_profile_id uuid, question text, answer text, review_status text);
INSERT INTO public.candidate_profiles (singleton_key, verified_experience_years, verified_skills, preferences)
VALUES ('primary', 2, '["Python"]', '{"target_roles": ["Python Developer"], "notice_period_days": 30}');
"""


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pgstore")
    data, port = tmp / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust"],
                   check=True, capture_output=True)
    server = subprocess.Popen([str(PG_BIN / "postgres"), "-D", str(data), "-p", str(port), "-k", "",
                               "-c", "listen_addresses=127.0.0.1"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    psql = [str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q"]
    try:
        for _ in range(100):
            if subprocess.run([*psql, "-c", "SELECT 1"], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(0.1)
        subprocess.run([*psql, "-c", BOOTSTRAP], check=True, capture_output=True)
        migration = tmp / "004.sql"
        migration.write_text(strip_pgvector(MIGRATION.read_text()))
        subprocess.run([*psql, "-f", str(migration)], check=True, capture_output=True, text=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest_asyncio.fixture
async def store(database):
    import asyncpg

    connection = await asyncpg.connect(database)
    await connection.execute(
        "TRUNCATE public.application_state_events, public.hitl_requests, public.applications CASCADE")
    await connection.execute(
        "UPDATE public.portal_rules SET revision=1, enabled=(platform='naukri'), portal_limit_hit_at=NULL")
    await connection.execute(
        "UPDATE public.worker_control SET desired_state='STOPPED', dry_run=true, run_once_requested_at=NULL")
    yield await PostgresStore.borrowed(connection)
    await connection.close()


def listing(i, platform="naukri", company="Acme Pvt Ltd"):
    return JobListing(platform=platform, external_job_id=f"{platform}-{i}", url=f"https://example.com/{i}",
                      title="Sr. Python Developer", company=company)


async def test_rules_crud_with_revision_and_db_constraints(store):
    rules = {r.platform: r for r in await store.list_rules()}
    assert set(rules) == {"naukri", "instahyre", "internshala", "himalayas", "wellfound", "work_at_a_startup", "we_work_remotely", "hiringcafe", "greenhouse", "lever", "ashby", "smartrecruiters", "remotive", "arbeitnow", "hacker_news"}
    from datetime import time as clock

    updated = await store.update_rules("naukri", {"max_applies_per_day": 40, "active_hours_start": clock(9, 30),
                                                  "unknown_applicants_policy": "skip"}, 1)
    assert updated.revision == 2 and updated.max_applies_per_day == 40
    assert updated.active_hours_start == clock(9, 30) and updated.unknown_applicants_policy == "skip"
    with pytest.raises(RevisionConflict) as conflict:
        await store.update_rules("naukri", {"enabled": False}, 1)
    assert conflict.value.current == 2
    with pytest.raises(RulesNotFound):
        await store.update_rules("linkedin", {"enabled": True}, 1)
    assert (await store.get_rules("naukri")).max_applies_per_day == 40  # worker reload sees it


async def test_worker_control_survives_restart(store, database):
    import asyncpg

    control = await store.set_worker_control(WorkerState.RUNNING, dry_run=False)
    assert control.desired_state is WorkerState.RUNNING and not control.dry_run
    await store.worker_heartbeat("RUNNING", current_platform="naukri", cycle_completed=True)
    fresh = await asyncpg.connect(database)  # a restarted process
    try:
        restarted = await (await PostgresStore.borrowed(fresh)).get_worker_control()
    finally:
        await fresh.close()
    assert restarted.desired_state is WorkerState.RUNNING and restarted.dry_run is False
    assert restarted.current_platform == "naukri" and restarted.last_cycle_at is not None
    once = await store.set_worker_control(run_once=True)
    assert once.run_once_requested_at is not None and once.desired_state is WorkerState.RUNNING
    await store.worker_heartbeat("SLEEPING", clear_run_once=True)
    assert (await store.get_worker_control()).run_once_requested_at is None


async def test_transitions_events_dedup_and_listing(store):
    first = await store.upsert_discovered(listing(1))
    assert first.dedup_key == "acme::senior python developer" and first.state is S.DISCOVERED
    other = await store.upsert_discovered(listing(7, platform="instahyre", company="ACME"))
    scored = await store.transition(first, S.SCORED, "passed_filters")
    applying = await store.transition(scored, S.APPLYING, "apply_started", count_attempt=True)
    applied = await store.transition(applying, S.APPLIED, "confirmation_text", receipt={"source": "dom"})
    assert applied.applied_at is not None and applied.attempts == 1 and applied.receipt == {"source": "dom"}
    duplicates = await store.find_duplicates(other.dedup_key, platform="instahyre", external_job_id="instahyre-7")
    assert [(d.platform, d.state) for d in duplicates] == [("naukri", S.APPLIED)]
    long_reason = "excluded_keyword_in_description: " + "x" * 200
    await store.transition(other, S.FILTERED_OUT, long_reason)
    events = await store.application_events(applied.id)
    assert [e["to_state"] for e in events] == ["SCORED", "APPLYING", "APPLIED"]
    rows, total = await store.list_applications(ApplicationQuery(state="FILTERED_OUT"))
    assert total == 1 and rows[0].reason == long_reason  # full reason kept on the row
    filtered_events = await store.application_events(rows[0].id)
    assert filtered_events[0]["payload"]["reason"] == long_reason and len(filtered_events[0]["event_type"]) == 80
    assert await store.applied_since("naukri", datetime.now(UTC) - timedelta(hours=1)) == 1
    assert await store.application_events("00000000-0000-0000-0000-000000000000") is None


async def test_backlog_hitl_auth_and_portal_limit(store):
    record = await store.upsert_discovered(listing(2))
    await store.transition(record, S.SCORED, "passed_filters")
    assert [r.external_job_id for r in await store.list_by_state("naukri", (S.SCORED,))] == ["naukri-2"]
    assert not await store.open_hitl_exists("naukri", "AUTH")
    await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {"why": "login"})
    assert await store.open_hitl_exists("naukri", "AUTH")
    assert await store.cancel_open_hitl("naukri", "AUTH") == 1
    assert not await store.open_hitl_exists("naukri", "AUTH")
    await store.record_auth("naukri", "AUTH_REQUIRED")
    await store.record_portal_limit("naukri")
    rules = await store.get_rules("naukri")
    assert rules.auth_status == "AUTH_REQUIRED" and rules.portal_limit_hit_at is not None
    assert await store.count_state(S.SCORED, "naukri") == 1
    profile, reviewed = await store.load_profile()
    assert profile["preferences"]["target_roles"] == ["Python Developer"] and reviewed == []


async def test_api_borrows_pooled_connection_and_commits(database):
    """get_v2_store path: raw asyncpg behind SQLAlchemy's pool; writes persist."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.app.api.v1.automation_v2 import get_v2_store

    engine = create_async_engine(database.replace("postgresql://", "postgresql+asyncpg://"),
                                 pool_size=2, max_overflow=1)
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as session:
            generator = get_v2_store(session)
            borrowed = await generator.__anext__()
            await borrowed.set_worker_control(WorkerState.PAUSED)
            await session.commit()
        async with AsyncSession(engine) as session:
            generator = get_v2_store(session)
            again = await generator.__anext__()
            assert (await again.get_worker_control()).desired_state is WorkerState.PAUSED
    finally:
        await engine.dispose()
