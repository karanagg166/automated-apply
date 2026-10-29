"""Disposable PostgreSQL proof; fictional jobs only, no provider requests."""

import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("disposable_local_candidate_profile_test_required")
    cluster = await asyncpg.connect(url)
    database = "candidate_profile_test_naukri_" + uuid4().hex[:12]
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child_url = urlunsplit(parsed._replace(path="/" + database))
    engine = None
    try:
        assert int(await cluster.fetchval("SHOW server_version_num")) // 10000 == 17
        from backend.app.core.config import Settings, configure_operator

        configure_operator(
            Settings(
                _env_file=None,
                ENVIRONMENT="testing",
                DATABASE_SCHEMA="public",
                DATABASE_URL=child_url.replace(
                    "postgresql://", "postgresql+asyncpg://"
                ),
            )
        )
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.agent.tools import ToolDenied
        from backend.app.execution import recurring, store
        from backend.app.execution.contracts import (
            AutomationControl,
            AutomationPolicy,
            AutomationPolicyUpdate,
            ImportJob,
        )
        from backend.app.execution.naukri import normalize
        from backend.app.execution.worker import ExecutionWorker
        from backend.app.local_agent.profile_confirmation import confirm_profile
        from backend.app.main import app  # noqa: F401 -- model registration
        from backend.app.models.application_answer import CandidateResource
        from backend.app.models.application_packet import ApplicationPacket
        from backend.app.models.base import Base
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.job_ingestion import JobIngestionService

        engine = create_async_engine(
            child_url.replace("postgresql://", "postgresql+asyncpg://")
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with factory() as session, session.begin():
            profile = await CandidateProfileRepository(session).create_primary_profile(
                CandidateProfileCreate(
                    full_name="Alex Fictional",
                    email="alex@example.com",
                    verified_experience_years=2,
                    verified_skills=["Python"],
                    preferences={
                        "target_titles": ["Backend Developer"],
                        "preferred_locations": ["India"],
                    },
                )
            )
            session.add(
                CandidateResource(
                    candidate_profile_id=profile.id,
                    resource_type="resume",
                    label="Fictional reviewed resume",
                    url="https://example.com/resume",
                    is_primary=True,
                    user_confirmed=True,
                )
            )
            await session.flush()
            await confirm_profile(session, profile, profile.version)
            _, _, resume = await recurring.context(session)
            policy = AutomationPolicy(
                profile_version=profile.version,
                resume_resource_id=resume.resource_id,
                resume_version=resume.resource_version,
                allowed_roles=["Backend Developer"],
                allowed_locations=["India"],
                experience_min=0,
                experience_max=3,
                max_preparations_per_day=2,
                interval_seconds=900,
            )
            await recurring.configure(
                session, AutomationPolicyUpdate(expected_revision=0, policy=policy)
            )
            await recurring.control(
                session, AutomationControl(action="start", expected_revision=1)
            )
            now = datetime.now(timezone.utc)
            await JobIngestionService(session).ingest_jobs(
                [
                    normalize(
                        ImportJob(
                            url=f"https://www.naukri.com/job-listings-fictional-backend-{281026123450 + i}",
                            title="Backend Developer",
                            employer="Fictional Circuit",
                            location="India",
                            remote_type="remote",
                            required_skills=["Python"],
                            experience_min=0,
                            experience_max=3,
                            experience_requirement="required",
                            posting_status="active",
                            observed_at=now,
                            posted_at=now,
                        )
                    )
                    for i in range(3)
                ]
            )

        async def tick():
            async with factory() as session, session.begin():
                await recurring.tick(session)

        await asyncio.gather(*[tick() for _ in range(8)])
        async with factory() as session, session.begin():
            assert (
                len(await store.rows(session)) == 2
            )  # cap reserved under the owner lock
            view = await recurring.status(session)
            assert view["counts"]["submitted_confirmed"] == 0
            assert any(
                d["reason"] == "daily_preparation_limit" for d in view["decisions"]
            )
        # New pools/process state recover only persisted cadence and reservations.
        await engine.dispose()
        await asyncio.gather(*[ExecutionWorker(factory).tick() for _ in range(4)])
        async with factory() as session, session.begin():
            packets = (await session.scalars(select(ApplicationPacket))).all()
            assert len(packets) == 2 and all(
                p.resume_resource_id == policy.resume_resource_id for p in packets
            )
            current = await recurring.record(session)
            await recurring.control(
                session,
                AutomationControl(action="stop", expected_revision=current["revision"]),
            )
        await engine.dispose()
        assert await ExecutionWorker(factory).tick() is None
        async with factory() as session, session.begin():
            assert (await recurring.status(session))["state"] == "STOPPED"
            assert await store.claim(session) is None
            try:
                await recurring.require_enabled(session)
                raise AssertionError("Stop admitted new work")
            except ToolDenied:
                pass
        print(
            "Naukri recurring PostgreSQL PASS: 8 concurrent schedulers, durable UTC cap, 4 workers, two factual packets, pool restart, Stop; zero provider requests/submissions. Fictional fixtures only."
        )
    finally:
        if engine:
            await engine.dispose()
        await cluster.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await cluster.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
