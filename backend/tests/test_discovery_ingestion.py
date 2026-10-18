import asyncio
import pytest
from sqlalchemy import select
from backend.app.db.session import get_session_factory
from backend.app.models.discovery import DiscoveryRun
from backend.app.services.job_discovery_service import JobDiscoveryService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.schemas.discovery import RunRequest, DiscoveryResult
from backend.tests.discovery_fakes import job


@pytest.mark.asyncio
async def test_failed_provider_persists_honest_run(db_session, monkeypatch):
    class Adapter:
        async def discover(self, *args, **kwargs):
            return DiscoveryResult(
                source="arbeitnow",
                status="upstream_error",
                errors=["Provider transport failed"],
            )

    monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **k: Adapter())
    output = await JobDiscoveryService(db_session, get_session_factory()).run(
        RunRequest(source="arbeitnow")
    )
    assert output["status"] == "upstream_error" and output["finished_at"]
    assert output["counts"]["inserted"] == 0 and output["errors"]


@pytest.mark.asyncio
async def test_cancelled_provider_run_is_durable(db_session, monkeypatch):
    class Adapter:
        async def discover(self, *args, **kwargs):
            raise asyncio.CancelledError()

    monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **k: Adapter())
    with pytest.raises(asyncio.CancelledError):
        await JobDiscoveryService(db_session, get_session_factory()).run(
            RunRequest(source="arbeitnow")
        )
    run = await db_session.scalar(select(DiscoveryRun))
    assert run.status == "cancelled" and run.finished_at


@pytest.mark.asyncio
async def test_source_identity_violation_never_ingests(db_session, monkeypatch):
    class Adapter:
        async def discover(self, *args, **kwargs):
            return DiscoveryResult(
                source="arbeitnow", status="success", jobs=[job(source_name="naukri")]
            )

    monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **k: Adapter())
    output = await JobDiscoveryService(db_session, get_session_factory()).run(
        RunRequest(source="arbeitnow")
    )
    assert output["status"] == "upstream_error" and output["counts"]["inserted"] == 0


@pytest.mark.asyncio
async def test_explicit_filters_preserve_unknown_metadata(db_session):
    data = [
        job(source_job_id="remote", remote_type="remote"),
        job(
            source_job_id="onsite",
            original_url="https://example.com/jobs/onsite",
            remote_type="onsite",
        ),
        job(
            source_job_id="unknown",
            original_url="https://example.com/jobs/unknown",
            remote_type="unknown",
            description="A different role",
        ),
    ]
    output = await JobDiscoveryService(db_session, get_session_factory()).run(
        RunRequest(
            source="manual",
            query={"remote_preference": "remote"},
            manual_jobs=[j.model_dump(mode="json") for j in data],
        )
    )
    assert output["counts"]["inserted"] == 2 and output["counts"]["skipped"] == 1
