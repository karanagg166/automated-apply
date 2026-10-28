"""Fictional discovery integration with isolated PostgreSQL 17 databases."""

import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.base import Base
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.discovery import DiscoveryRun, JobSourceObservation
from backend.app.models.job import Job
from backend.app.schemas.discovery import RunRequest
from backend.app.services.job_discovery_service import (
    IdempotencyConflict,
    JobDiscoveryService,
)
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.tests.test_public_ats import configuration, feed, posting

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("PROFILE_TEST_DATABASE_URL"),
        reason="Requires disposable local PostgreSQL 17",
    ),
]


@pytest_asyncio.fixture
async def postgres():
    parsed = urlsplit(os.environ["PROFILE_TEST_DATABASE_URL"])
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
    ):
        raise ValueError("Only disposable local CI PostgreSQL is permitted")
    admin = await asyncpg.connect(urlunsplit(parsed))
    assert int(await admin.fetchval("SHOW server_version_num")) // 10000 == 17
    database = "candidate_profile_test_ats_" + uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    url = urlunsplit(parsed._replace(path="/" + database))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            profile = CandidateProfile(
                full_name="Alex Fictional", email="alex@example.com"
            )
            session.add(profile)
            await session.flush()
            profile.version = 7
            await session.commit()
        yield factory, engine
    finally:
        await engine.dispose()
        if admin.is_closed():
            admin = await asyncpg.connect(urlunsplit(parsed))
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


def install_mock(monkeypatch, adapter, handler, *, paced=False):
    def get_adapter(source, **kwargs):
        assert (
            source == adapter.source_name
        )  # A paid or submission route fails this test.
        if paced:

            class LocalFeed(adapter):
                def client(self):
                    return httpx.AsyncClient(transport=httpx.MockTransport(handler))

            return LocalFeed(settings=kwargs["settings"])
        return adapter(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            settings=kwargs["settings"],
        )

    monkeypatch.setattr(JobSourceFactory, "get_adapter", get_adapter)


async def execute(factory, request, settings=None):
    async with factory() as session:
        return await JobDiscoveryService(
            session, factory, settings or configuration()
        ).run(request)


@pytest.mark.parametrize("adapter", [LeverAdapter, AshbyAdapter])
async def test_concurrent_discovery_idempotency_and_human_state(
    postgres, monkeypatch, adapter
):
    factory, _ = postgres
    calls = []

    async def handler(request):
        assert request.method == "GET" and request.url.host in {
            "api.lever.co",
            "api.ashbyhq.com",
        }
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=feed(adapter, [posting(adapter)]))

    install_mock(monkeypatch, adapter, handler)
    request = RunRequest(source=adapter.source_name, idempotency_key="same-key")
    results = await asyncio.wait_for(
        asyncio.gather(*(execute(factory, request) for _ in range(4))), 10
    )
    assert len({r["id"] for r in results}) == 1 and len(calls) == 1
    first = await execute(factory, request)
    assert first["status"] == "success" and first["rankings"][0]["profile_version"] == 7
    assert first["usage"]["diagnostics"]["record_attempts"] == 1
    saved_id = UUID(first["job_ids"][0])
    from backend.app.schemas.applications import CreatePacket
    from backend.app.services.application_answer_service import ApplicationAnswerService
    from backend.app.services.applications.service import ApplicationPacketService
    from backend.tests.phase2a_fakes import FakeProvider

    fake_provider = FakeProvider()
    async with factory() as session:
        answer_service = ApplicationAnswerService(
            session, configuration(), fake_provider
        )
        packet = await ApplicationPacketService(session, answer_service).create(
            saved_id, CreatePacket(idempotency_key="fictional-ats-packet")
        )
        packet_id = packet.id
        saved_packet = await session.get(ApplicationPacket, packet_id)
        saved_packet.lifecycle_state = "user_reported_submitted"
        saved_packet.tracking_state = "applied"
        snapshot = saved_packet.snapshot
        await session.commit()
    for status in ("shortlisted", "applied", "rejected"):
        async with factory() as session:
            job = await session.get(Job, saved_id)
            job.status, job.match_score, job.match_explanation = (
                status,
                77,
                "Human explanation",
            )
            await session.commit()
        keys = [
            RunRequest(source=adapter.source_name, idempotency_key=f"{status}-{i}")
            for i in range(2)
        ]
        repeat = await asyncio.gather(*(execute(factory, key) for key in keys))
        assert all(
            r["counts"]["inserted"] == 0 and r["job_ids"] == first["job_ids"]
            for r in repeat
        )
        async with factory() as session:
            job = await session.get(Job, saved_id)
            assert (job.status, job.match_score, job.match_explanation) == (
                status,
                77,
                "Human explanation",
            )
            assert await session.scalar(select(func.count()).select_from(Job)) == 1
            assert (
                await session.scalar(
                    select(func.count()).select_from(JobSourceObservation)
                )
                == 1
            )
            preserved = await session.get(ApplicationPacket, packet_id)
            assert (
                preserved.lifecycle_state == "user_reported_submitted"
                and preserved.tracking_state == "applied"
            )
            assert preserved.snapshot == snapshot
            assert (
                await session.scalar(
                    select(func.count()).select_from(ApplicationPacket)
                )
                == 1
            )
    assert fake_provider.calls == []
    with pytest.raises(IdempotencyConflict):
        await execute(
            factory,
            request.model_copy(
                update={"query": request.query.model_copy(update={"limit": 1})}
            ),
        )


async def test_single_connection_pacing_claim_and_profile_are_compatible(
    postgres, monkeypatch
):
    factory, _ = postgres
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=feed(AshbyAdapter, [posting(AshbyAdapter)]))

    install_mock(monkeypatch, AshbyAdapter, handler, paced=True)
    first, second = await asyncio.wait_for(
        asyncio.gather(
            *(
                execute(
                    factory, RunRequest(source="ashby", idempotency_key=f"paced-{i}")
                )
                for i in range(2)
            )
        ),
        10,
    )
    assert {first["status"], second["status"]} == {"success", "rate_limited"}
    assert len(calls) == 1


@pytest.mark.parametrize("adapter", [LeverAdapter, AshbyAdapter])
async def test_job_led_startup_single_connection_persists_and_replays(
    postgres, monkeypatch, adapter
):
    from backend.app.services.startup_discovery.schemas import StartupRunRequest
    from backend.app.services.startup_discovery.service import StartupDiscoveryService

    factory, _ = postgres
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=feed(adapter, [posting(adapter)]))

    install_mock(monkeypatch, adapter, handler, paced=True)
    request = StartupRunRequest(
        source=adapter.source_name,
        mode="job_led",
        idempotency_key="startup-single-connection",
    )

    async def run():
        async with factory() as session:
            return await StartupDiscoveryService(
                session, factory, configuration()
            ).run(request)

    first = await asyncio.wait_for(run(), 5)
    assert first["status"] == "success", first
    assert first["counts"]["companies_observed"] == 1
    assert len(first["rankings"]) == 1
    assert first["rankings"][0]["profile_version"] == 7
    assert await asyncio.wait_for(run(), 5) == first
    assert len(calls) == 1
    async with factory() as session:
        parent = await session.get(DiscoveryRun, UUID(first["id"]))
        child = await session.get(
            DiscoveryRun, UUID(parent.query_summary["child_run_id"])
        )
        assert child.status == "success"
        assert child.rankings[0]["profile_version"] == 7
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(JobSourceObservation))
            == 1
        )


async def test_discovery_concurrency_is_bounded(postgres, monkeypatch):
    factory, _ = postgres
    active = maximum = calls = 0

    async def handler(request):
        nonlocal active, maximum, calls
        calls += 1
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.02)
            return httpx.Response(200, json=feed(LeverAdapter, [posting(LeverAdapter)]))
        finally:
            active -= 1

    install_mock(monkeypatch, LeverAdapter, handler)
    settings = configuration(DISCOVERY_MAX_CONCURRENCY=1)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                execute(
                    factory,
                    RunRequest(source="lever", idempotency_key=f"bounded-{i}"),
                    settings,
                )
                for i in range(4)
            )
        ),
        10,
    )
    assert maximum == 1 and calls == 4
    assert sum(r["counts"]["inserted"] for r in results) == 1


async def test_profile_loading_obeys_overall_deadline(postgres, monkeypatch):
    from backend.app.services.candidate_profile_service import CandidateProfileService

    factory, _ = postgres

    async def slow_profile(service):
        await asyncio.sleep(10)

    monkeypatch.setattr(CandidateProfileService, "get_profile", slow_profile)
    request = RunRequest(source="manual", idempotency_key="profile-deadline")
    settings = configuration().model_copy(update={"DISCOVERY_TIMEOUT_SECONDS": 0.1})
    result = await execute(factory, request, settings)
    assert (
        result["status"] == "upstream_error"
        and result["usage"]["diagnostics"]["last_phase"] == "profile"
    )


@pytest.mark.parametrize("existing_identity", [False, True])
async def test_company_cache_never_overrides_new_ambiguity(postgres, existing_identity):
    factory, _ = postgres

    def record(identifier, domain=None):
        return {
            "source_name": "manual",
            "source_job_id": identifier,
            "title": "Engineer " + identifier,
            "original_url": "https://example.com/" + identifier,
            "company_name": "Shared Name",
            "company_domain": domain,
        }

    async with factory() as session:
        ingestion = JobIngestionService(session)
        if existing_identity:
            await ingestion.ingest_jobs(
                [
                    record("known-one", "one.example.com"),
                    record("known-two", "two.example.com"),
                ]
            )
            await session.commit()
            batch = [record("known-one"), record("new-unknown")]
        else:
            batch = [
                record("first-unknown"),
                record("known-one", "one.example.com"),
                record("known-two", "two.example.com"),
                record("new-unknown"),
            ]
        result = await ingestion.ingest_jobs(batch)
        assert not result.errors
        job = await session.get(Job, UUID(result.job_ids[-1]))
        company = await session.get(Company, job.company_id)
        assert (
            company.domain is None
            and company.metadata_["identity_review_required"] is True
        )


async def test_disconnect_rolls_back_batch_and_retains_failure(postgres, monkeypatch):
    factory, engine = postgres
    original = JobIngestionService.ingest_jobs

    async def disconnect(ingestion, records, **kwargs):
        await original(ingestion, records, **kwargs)
        pid = await ingestion.session.scalar(text("SELECT pg_backend_pid()"))
        # Use a separate administrative connection; the runtime pool remains size one.
        parsed = urlsplit(os.environ["PROFILE_TEST_DATABASE_URL"])
        admin = await asyncpg.connect(
            urlunsplit(parsed._replace(path="/" + engine.url.database))
        )
        try:
            await admin.execute("SELECT pg_terminate_backend($1)", pid)
        finally:
            await admin.close()
        raise RuntimeError("Fictional database disconnect")

    monkeypatch.setattr(JobIngestionService, "ingest_jobs", disconnect)
    request = RunRequest(
        source="manual",
        idempotency_key="disconnect",
        manual_jobs=[
            {
                "source_name": "manual",
                "source_job_id": "fictional",
                "title": "Fictional Engineer",
                "original_url": "https://example.com/fictional",
                "company_name": "Fictional Employer",
            }
        ],
    )
    result = await execute(factory, request)
    assert result["status"] == "failed" and result["counts"]["inserted"] == 0
    assert result["usage"]["diagnostics"]["last_phase"] == "ingestion"
    assert await execute(factory, request) == result
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(JobSourceObservation))
            == 0
        )


async def test_deadline_covers_profile_and_ingestion_and_never_commits_partial(
    postgres, monkeypatch
):
    factory, _ = postgres
    original = JobIngestionService.ingest_jobs

    async def slow(ingestion, records, **kwargs):
        await original(ingestion, records, **kwargs)
        await asyncio.sleep(10)

    monkeypatch.setattr(JobIngestionService, "ingest_jobs", slow)
    request = RunRequest(
        source="manual",
        idempotency_key="deadline",
        manual_jobs=[
            {
                "source_name": "manual",
                "title": "Fictional",
                "original_url": "https://example.com/timeout",
            }
        ],
    )
    settings = configuration().model_copy(update={"DISCOVERY_TIMEOUT_SECONDS": 0.5})
    result = await execute(factory, request, settings)
    assert result["status"] == "upstream_error" and result["counts"]["inserted"] == 0
    assert "ingestion" in result["errors"][0]
    assert (await execute(factory, request, settings))["id"] == result["id"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 0


async def test_lost_commit_acknowledgement_returns_saved_result_without_replay(
    postgres, monkeypatch
):
    factory, _ = postgres
    request = RunRequest(
        source="manual",
        idempotency_key="lost-ack",
        manual_jobs=[
            {
                "source_name": "manual",
                "title": "Fictional",
                "original_url": "https://example.com/commit",
            }
        ],
    )
    async with factory() as session:
        original = session.commit

        async def commit_then_disconnect():
            await original()
            raise RuntimeError("Lost commit acknowledgement")

        monkeypatch.setattr(session, "commit", commit_then_disconnect)
        result = await JobDiscoveryService(session, factory, configuration()).run(
            request
        )
    assert result["status"] == "success" and result["counts"]["inserted"] == 1
    assert await execute(factory, request) == result
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 1


async def test_rollback_erases_jobs_and_stale_run_requires_explicit_recovery(postgres):
    factory, _ = postgres
    async with factory() as session:
        result = await JobIngestionService(session).ingest_jobs(
            [
                {
                    "source_name": "ashby",
                    "title": "Fictional",
                    "original_url": "https://jobs.ashbyhq.com/fictional/rollback",
                }
            ]
        )
        assert result.inserted_count == 1
        await session.rollback()
    request = RunRequest(source="ashby", idempotency_key="interrupted")
    async with factory() as session:
        run_id, claimed = await JobDiscoveryService(session, factory).claim(request)
        assert claimed
    async with factory() as session:
        run = await session.get(DiscoveryRun, run_id)
        run.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await session.commit()
    result = await execute(factory, request)
    assert result["status"] == "recovery_required" and result["finished_at"] is None
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 0
        assert (await session.get(DiscoveryRun, run_id)).status == "running"


@pytest.mark.skipif(
    not os.environ.get("P22_TEST_POSTGRES_CONTAINER"),
    reason="Explicit disposable Docker restart target required",
)
async def test_actual_disposable_postgres_restart_and_recovery(postgres, monkeypatch):
    factory, _ = postgres
    container = os.environ["P22_TEST_POSTGRES_CONTAINER"]
    parsed = urlsplit(os.environ["PROFILE_TEST_DATABASE_URL"])
    assert (container, parsed.port) in {
        ("codex-p22-pg17", 55432),
        ("codex-phase2-final-pg17", 55437),
        ("codex-p3-pg17", 55434),
        ("automated-apply-p35-postgres", 55435),
        ("automated-apply-phase35-integrated-test", 55436),
        ("codex-phase4-pg17", 55438),
        ("automated-apply-phase4-integrated-test", 55439),
    }
    original = JobIngestionService.ingest_jobs

    async def restart_after_writes(ingestion, records, **kwargs):
        await original(ingestion, records, **kwargs)
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "restart", "--time", "1", container],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        # Startup readiness only; never repeat discovery or an external operation.
        for _ in range(50):
            try:
                connection = await asyncpg.connect(urlunsplit(parsed), timeout=1)
                await connection.close()
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("Disposable PostgreSQL did not restart")
        raise RuntimeError("Interrupted by disposable server restart")

    monkeypatch.setattr(JobIngestionService, "ingest_jobs", restart_after_writes)
    request = RunRequest(
        source="manual",
        idempotency_key="restart",
        manual_jobs=[
            {
                "source_name": "manual",
                "title": "Fictional",
                "original_url": "https://example.com/restart",
            }
        ],
    )
    result = await execute(factory, request)
    assert result["status"] == "failed" and result["counts"]["inserted"] == 0
    assert await execute(factory, request) == result
    monkeypatch.setattr(JobIngestionService, "ingest_jobs", original)
    fresh = await execute(
        factory,
        request.model_copy(update={"idempotency_key": "owner-requested-after-review"}),
    )
    assert fresh["status"] == "success" and fresh["counts"]["inserted"] == 1


async def test_27_listing_batch_query_budget_and_idempotent_retry(postgres):
    factory, engine = postgres
    statements = []

    def count_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.split()[0])

    event.listen(engine.sync_engine, "before_cursor_execute", count_sql)
    request = RunRequest(
        source="manual", idempotency_key="27-listing-query-budget", query={"limit": 27},
        manual_jobs=[{
            "source_name": "manual", "source_job_id": str(i),
            "title": "Fictional Engineer", "company_name": "Fictional Company",
            "original_url": f"https://example.com/fixture/{i}",
        } for i in range(27)],
    )
    try:
        result = await execute(factory, request)
        assert result["status"] == "success" and result["counts"]["inserted"] == 27
        # Bound database round trips while retaining savepoints and every audit.
        # The pre-optimization implementation performed 140 SELECTs here.
        assert statements.count("SELECT") <= 115
        phases = result["usage"]["diagnostics"]["phase_seconds"]
        assert {"claim", "claim_checkout", "profile_checkout", "ingestion_checkout", "matching"} <= phases.keys()
        statements.clear()
        assert await execute(factory, request) == result
        assert "SAVEPOINT" not in statements and "UPDATE" not in statements
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Job)) == 27
            assert await session.scalar(select(func.count()).select_from(JobSourceObservation)) == 27
        assert engine.pool.checkedout() == 0
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_sql)


async def test_gmail_selected_sync_survives_pool_restart_and_rate_limit_isolates_accounts(postgres):
    from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
    from backend.app.integrations.google_oauth import GoogleOAuth
    from backend.app.integrations.token_store import ConnectionError
    from backend.tests.phase4a_fakes import GoogleFixture, oauth_settings
    from backend.tests.test_phase3_gmail_readonly import connect

    factory, engine = postgres
    settings = oauth_settings(DATABASE_SCHEMA="public", GMAIL_READ_SYNC_ENABLED=True)
    fake = GoogleFixture()
    calls = []
    fail_resume = True

    def messages(request):
        nonlocal fail_resume
        assert request.method == "GET" and "q" not in request.url.params
        token = request.headers["Authorization"]
        calls.append((token, request.url.path, request.url.params.get("pageToken")))
        assert token in {"Bearer first@example.com-access", "Bearer second@example.com-access"}
        if request.url.path.endswith("/messages"):
            assert request.url.params.get_list("labelIds") == ["Label_jobs"]
            if "second@" in token:
                assert "pageToken" not in request.url.params
            if request.url.params.get("pageToken") and fail_resume:
                fail_resume = False
                return httpx.Response(429)
            return httpx.Response(200, json={"messages": [{"id": "same-id"}], **(
                {"nextPageToken": "first-next"}
                if "first@" in token and not request.url.params.get("pageToken") else {}
            )})
        assert request.url.params["format"] == "metadata"
        return httpx.Response(200, json={
            "id": "same-id", "threadId": "same-thread",
            "internalDate": str(int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)),
            "labelIds": ["Label_jobs"], "payload": {"headers": [
                {"name": "From", "value": "jobs@example.com"},
                {"name": "Subject", "value": "Job alert"},
            ]},
        })

    async with fake.client() as oauth, httpx.AsyncClient(transport=httpx.MockTransport(messages)) as gmail:
        async with factory() as session:
            first = await connect(session, settings, fake, oauth, "first@example.com")
            second = await connect(session, settings, fake, oauth, "second@example.com")
            service = GmailReadService(session, settings, google=GoogleOAuth(settings, oauth), client=gmail)
            for account_id in (first, second):
                await service.configure(account_id, ReadPolicy(expected_version=0, enabled=True, label_allowlist=["Label_jobs"]))
            assert (await service.sync(first))["sync"]["status"] == "partial"
        await engine.dispose()  # Durable cursors/tokens must outlive every pooled connection.
        async with factory() as session:
            service = GmailReadService(session, settings, google=GoogleOAuth(settings, oauth), client=gmail)
            with pytest.raises(ConnectionError, match="rate_limited"):
                await service.sync(first)
        await engine.dispose()
        async with factory() as session:
            service = GmailReadService(session, settings, google=GoogleOAuth(settings, oauth), client=gmail)
            assert (await service.sync(first))["sync"]["status"] == "completed"
            assert not await service.evidence(second)
            assert (await service.sync(second))["sync"]["status"] == "completed"
            a, b = await service.evidence(first), await service.evidence(second)
            assert len(a) == len(b) == 1
            assert a[0]["id"] != b[0]["id"] and a[0]["account_id"] != b[0]["account_id"]
            assert all(not row["submission_confirmed"] for row in a + b)
    assert len([call for call in calls if call[1].endswith("/same-id")]) == 2
    assert engine.pool.checkedout() == 0
