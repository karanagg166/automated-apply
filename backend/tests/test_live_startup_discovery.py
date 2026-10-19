from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.app.db.session import get_session_factory
from backend.app.models.company import Company
from backend.app.models.discovery import DiscoveryRun, now
from backend.app.models.job import Job
from backend.app.models.startup import CompanySourceObservation, StartupShortlistEntry
from backend.app.services.job_discovery_service import IdempotencyConflict
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.startup_discovery.evidence import ingest_company
from backend.app.services.startup_discovery.schemas import (
    ShortlistInput,
    StartupFilters,
    StartupRunRequest,
)
from backend.app.services.startup_discovery.service import StartupDiscoveryService
from backend.tests.discovery_fakes import job, settings
from backend.tests.startup_fakes import observed


@pytest.mark.asyncio
async def test_company_first_persists_without_fake_job_and_replay(
    db_session, phase2_profile
):
    request = StartupRunRequest(
        idempotency_key="startup-first-001",
        companies=[observed()],
        permission_confirmed=True,
    )
    service = StartupDiscoveryService(db_session, get_session_factory(), settings())
    result = await service.run(request)
    assert result["status"] == "success", result
    assert result["counts"]["companies_observed"] == 1
    assert result["rankings"][0]["hiring_status"] == "hiring_unknown"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0
    repeated = await service.run(request)
    assert repeated["id"] == result["id"]
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CompanySourceObservation)
        )
        == 1
    )
    with pytest.raises(IdempotencyConflict):
        await service.run(request.model_copy(update={"allow_paid": True}))


@pytest.mark.asyncio
async def test_aliases_domains_source_conflicts_and_append_only_snapshots(db_session):
    first = await ingest_company(db_session, observed())
    alias = await ingest_company(
        db_session, observed(name="Fictional Robotics Pvt Ltd")
    )
    assert first.id == alias.id and first.name == "Fictional Robotics"
    other = await ingest_company(
        db_session, observed(source_company_id="different", domain="another.example")
    )
    assert other.id != first.id
    with pytest.raises(ValueError, match="conflicts"):
        await ingest_company(db_session, observed(domain="conflict.example"))
    item = observed(source="official", source_company_id="reported")
    await ingest_company(db_session, item)
    await ingest_company(db_session, item)
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CompanySourceObservation)
        )
        == 4
    )


@pytest.mark.asyncio
async def test_unknown_size_and_conflicting_size_are_visible(db_session):
    company = await ingest_company(db_session, observed(employee_count=None))
    service = StartupDiscoveryService(db_session)
    assert (await service.detail(company.id))[
        "team_size_evidence_status"
    ] == "team_size_unknown"
    assert (await service.search(StartupFilters()))["total"] == 1
    assert (await service.search(StartupFilters(include_unknown_size=False)))[
        "total"
    ] == 0
    await ingest_company(db_session, observed(employee_count=18))
    await ingest_company(db_session, observed(source="other", employee_count=250))
    info = await service.detail(company.id)
    assert info["team_size_evidence_status"] == "conflicting"
    assert info["employee_count"] is None
    assert (await service.search(StartupFilters(include_unknown_size=False)))[
        "total"
    ] == 0


@pytest.mark.asyncio
async def test_historical_size_does_not_override_human_review(db_session):
    company = await ingest_company(
        db_session, observed(employee_count=18, verification_status="human_confirmed")
    )
    await ingest_company(db_session, observed(source="official", employee_count=100))
    await ingest_company(
        db_session, observed(source="historical", employee_count=1000, historical=True)
    )
    result = await StartupDiscoveryService(db_session).detail(company.id)
    assert (
        result["employee_count"] == 18
        and result["team_size_evidence_status"] == "human_confirmed"
    )
    assert len(result["team_size_evidence"]) == 3


@pytest.mark.asyncio
async def test_ranking_uses_saved_profile_and_multiple_real_job_observations(
    db_session, phase2_profile
):
    company = await ingest_company(db_session, observed(domain="example.com"))
    jobs = [
        job(
            source_name="greenhouse",
            source_job_id=str(i),
            original_url=f"https://boards.greenhouse.io/example/jobs/{i}",
            is_confirmed_current=True,
            source_verification_status="source_reported",
        )
        for i in (1, 2)
    ]
    await JobIngestionService(db_session).ingest_jobs(jobs)
    detail = await StartupDiscoveryService(db_session).detail(company.id)
    assert detail["current_job_count"] >= 1
    assert detail["hiring_status"] == "hiring_confirmed"
    assert detail["profile_version"] == phase2_profile.version
    assert detail["startup_match_score"] > 0
    assert detail["matching_roles"] >= 1
    assert any("saved-profile" in r for r in detail["ranking_reasons"])


@pytest.mark.asyncio
async def test_shortlist_is_idempotent_and_preserves_first_human_note(db_session):
    company = await ingest_company(db_session, observed())
    await db_session.commit()
    service = StartupDiscoveryService(db_session)
    first = await service.shortlist(
        company.id, ShortlistInput(note="Reviewed by owner")
    )
    second = await service.shortlist(
        company.id, ShortlistInput(note="Do not overwrite")
    )
    assert first["created"] and not second["created"]
    assert (
        await db_session.get(StartupShortlistEntry, company.id)
    ).note == "Reviewed by owner"
    assert (await service.search(StartupFilters(), shortlisted=True))["total"] == 1


@pytest.mark.asyncio
async def test_unsupported_directory_does_not_make_network_calls(db_session):
    result = await StartupDiscoveryService(
        db_session, get_session_factory(), settings()
    ).run(StartupRunRequest(source="yc_directory", idempotency_key="startup-yc-001"))
    assert result["status"] == "unsupported"
    assert result["counts"]["companies_observed"] == 0


@pytest.mark.asyncio
async def test_crash_rolls_back_company_batch_and_retains_audit(
    db_session, monkeypatch
):
    from backend.app.services.startup_discovery import service as module

    calls = 0
    original = module.ingest_company

    async def crash(session, item, run_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("fixture secret must never escape")
        return await original(session, item, run_id)

    monkeypatch.setattr(module, "ingest_company", crash)
    request = StartupRunRequest(
        idempotency_key="startup-crash-001",
        permission_confirmed=True,
        companies=[
            observed(),
            observed(source_company_id="second", domain="second.example"),
        ],
    )
    result = await StartupDiscoveryService(
        db_session, get_session_factory(), settings()
    ).run(request)
    assert result["status"] == "failed"
    assert "secret" not in str(result)
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 0


@pytest.mark.asyncio
async def test_expired_execution_is_recovery_required_without_replay(db_session):
    run = DiscoveryRun(
        source="startup_manual",
        request_hash="a" * 64,
        started_at=now() - timedelta(hours=1),
        status="running",
    )
    db_session.add(run)
    await db_session.flush()
    assert (await StartupDiscoveryService(db_session).read_run(run.id))[
        "status"
    ] == "recovery_required"
    with pytest.raises(LookupError):
        await StartupDiscoveryService(db_session).read_run(uuid4())


@pytest.mark.asyncio
async def test_filters_and_deterministic_pagination(db_session, phase2_profile):
    for index in range(3):
        await ingest_company(
            db_session,
            observed(
                name=f"Fictional {index}",
                source_company_id=str(index),
                domain=f"company-{index}.example",
            ),
        )
    service = StartupDiscoveryService(db_session)
    first = await service.search(StartupFilters(limit=1))
    second = await service.search(StartupFilters(limit=1, page=2))
    assert first["total"] == 3
    assert first["startups"][0]["company_id"] != second["startups"][0]["company_id"]
    for filters in [
        StartupFilters(stages=["series_c"]),
        StartupFilters(yc_batch="W99"),
        StartupFilters(locations=["Tokyo"], remote_preference="onsite"),
        StartupFilters(skills=["Haskell"]),
        StartupFilters(has_leader_evidence=True),
        StartupFilters(hiring_status="not_currently_hiring"),
        StartupFilters(source="missing"),
    ]:
        assert (await service.search(filters))["total"] == 0
    assert (await service.search(StartupFilters(skills=["Python"])))["total"] == 3
    with pytest.raises(LookupError):
        await service.detail(UUID(int=0))


@pytest.mark.asyncio
async def test_job_led_run_reuses_existing_ingestion_and_matching(
    db_session, monkeypatch, phase2_profile
):
    import httpx

    from backend.app.services.job_sources.direct_api import ArbeitnowAdapter
    from backend.app.services.job_sources.factory import JobSourceFactory

    payload = {
        "data": [
            {
                "slug": "fictional-role",
                "url": "https://fictional.example/jobs/backend",
                "title": "Backend Engineer",
                "company_name": "Fictional Engineering",
                "remote": True,
                "tags": ["Python"],
                "created_at": int(now().timestamp()),
            }
        ]
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        monkeypatch.setattr(
            JobSourceFactory,
            "get_adapter",
            staticmethod(lambda *a, **k: ArbeitnowAdapter(client)),
        )
        service = StartupDiscoveryService(db_session, get_session_factory(), settings())
        result = await service.run(
            StartupRunRequest(
                mode="job_led",
                source="arbeitnow",
                idempotency_key="job-led-startup-001",
            )
        )
    assert result["status"] == "success", result
    assert result["counts"]["companies_observed"] == 1
    assert result["rankings"][0]["team_size_band"] == "unknown"
    assert result["rankings"][0]["hiring_status"] == "hiring_possible"
    saved = await service.read_run(UUID(result["id"]))
    assert saved["query"]["child_run_id"]
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.asyncio
async def test_company_retention_preserves_human_evidence(db_session):
    from backend.app.services.startup_discovery.retention import prune_startup_data

    await ingest_company(db_session, observed(observed_at=now() - timedelta(days=365)))
    await ingest_company(
        db_session,
        observed(
            source="official",
            observed_at=now() - timedelta(days=365),
            verification_status="human_confirmed",
        ),
    )
    counts = await prune_startup_data(db_session)
    assert counts["company_snapshots_deleted"] == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CompanySourceObservation)
        )
        == 1
    )
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1


@pytest.mark.asyncio
async def test_domainless_job_never_selects_arbitrary_namesake(db_session):
    from backend.app.repositories.company import CompanyRepository

    repo = CompanyRepository(db_session)
    first, _ = await repo.get_or_create("Shared Fictional Name", "first.example")
    second, _ = await repo.get_or_create("Shared Fictional Name", "second.example")
    assert first.id != second.id
    assert await repo.get_by_name("Shared Fictional Name") is None
    item = job(
        company_name="Shared Fictional Name",
        company_domain=None,
        source_job_id="ambiguous-job",
        original_url="https://fictional.example/ambiguous",
    )
    result = await JobIngestionService(db_session).ingest_jobs([item])
    assert result.inserted_count == 1
    saved = await db_session.get(Job, UUID(result.job_ids[0]))
    company = await db_session.get(Company, saved.company_id)
    assert company.id not in {first.id, second.id} and company.domain is None
    assert company.metadata_["identity_review_required"]
    repeat = await JobIngestionService(db_session).ingest_jobs([item])
    assert repeat.duplicate_count == 1 and repeat.job_ids == result.job_ids
    assert (await StartupDiscoveryService(db_session).detail(company.id))[
        "identity_review_required"
    ]
    new, _ = await repo.get_or_create("Shared Fictional Name", "third.example")
    assert new.id != company.id and company.domain is None
    confirmed = await ingest_company(
        db_session,
        observed(
            name="Shared Fictional Name",
            domain="fourth.example",
            source_company_id="fourth",
            verification_status="human_confirmed",
        ),
    )
    assert confirmed.id != company.id and company.domain is None


@pytest.mark.asyncio
async def test_existing_job_observation_preserves_company_when_name_becomes_ambiguous(
    db_session,
):
    from backend.app.repositories.company import CompanyRepository

    repo = CompanyRepository(db_session)
    item = job(
        company_name="Shared Fictional Name",
        company_domain="first.example",
        source_job_id="known-job",
        original_url="https://fictional.example/known",
    )
    original = await JobIngestionService(db_session).ingest_jobs([item])
    first = await db_session.get(Job, UUID(original.job_ids[0]))
    await repo.get_or_create("Shared Fictional Name", "second.example")
    repeated = await JobIngestionService(db_session).ingest_jobs(
        [item.model_copy(update={"company_domain": None})]
    )
    assert repeated.duplicate_count == 1 and repeated.rejected_count == 0
    assert first.company_id == (await repo.get_by_domain("first.example")).id
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 2
