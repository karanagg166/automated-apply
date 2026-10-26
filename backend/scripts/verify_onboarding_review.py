"""Resume selection and context CAS on a uniquely created disposable PostgreSQL DB."""

import asyncio
import hashlib
import io
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
    ):
        raise ValueError("only_disposable_local_postgresql_allowed")
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_" + uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    engine = None
    try:
        from cryptography.fernet import Fernet
        from fastapi import HTTPException
        from pypdf import PdfWriter
        from sqlalchemy import func, select, text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.candidate_context.common import ContextError
        from backend.app.candidate_context.configuration import (
            CandidateConfiguration,
            ProjectConfiguration,
        )
        from backend.app.candidate_context.persistence import SQLRecordStore
        from backend.app.candidate_context.projects import EvidenceReference, make_fact
        from backend.app.candidate_context.service import CandidateContextService
        from backend.app.core.config import Settings, configure_operator

        key = Fernet.generate_key()
        configure_operator(
            Settings(
                _env_file=None,
                ENVIRONMENT="testing",
                DATABASE_SCHEMA="job_agent",
                DATABASE_URL=isolated.replace(
                    "postgresql://", "postgresql+asyncpg://", 1
                ),
                RESUME_ENCRYPTION_KEY=key.decode(),
                DB_REMOTE_ONLY=False,
            )
        )
        from backend.app.dashboard.models import PrivateResume
        from backend.app.dashboard.router import confirm_resume
        from backend.app.dashboard.schemas import ResumeConfirm
        from backend.app.main import app
        from backend.app.models.application_answer import CandidateResource
        from backend.app.models.base import Base
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.applications.resume_selector import select_resume

        assert app.routes
        engine = create_async_engine(
            isolated.replace("postgresql://", "postgresql+asyncpg://", 1)
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA job_agent"))
            await conn.run_sync(Base.metadata.create_all)
            version = await conn.scalar(text("SHOW server_version"))
            assert version.startswith("17."), version
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        output = io.BytesIO()
        writer.write(output)
        raw = output.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(
                CandidateProfileCreate(
                    full_name="Alex Fictional",
                    email="alex@example.org",
                    verified_skills=["Python"],
                )
            )
            profile_id = profile.id
            resumes = [
                PrivateResume(
                    label="Fictional.pdf",
                    ciphertext=Fernet(key).encrypt(raw),
                    sha256=digest,
                )
                for _ in range(2)
            ]
            session.add_all(resumes)
            await session.commit()
            ids = [r.id for r in resumes]

        async def confirm(resume_id):
            async with factory() as session:
                try:
                    result = await confirm_resume(
                        resume_id,
                        ResumeConfirm(
                            owner_confirmed=True,
                            primary=True,
                            expected_sha256=digest,
                            expected_profile_version=1,
                        ),
                        session,
                    )
                    await session.commit()
                    return result
                except HTTPException as error:
                    await session.rollback()
                    assert error.status_code == 409
                    return "conflict"

        selected = await asyncio.gather(*(confirm(id) for id in ids))
        assert selected.count("conflict") == 1
        async with factory() as session:
            resources = list((await session.scalars(select(CandidateResource))).all())
            assert len(resources) == 1 and select_resume(resources).selected is not None
            assert (
                await CandidateProfileRepository(session).get_primary_profile()
            ).version == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PrivateResume)
                    .where(PrivateResume.confirmed.is_(True))
                )
                == 1
            )
            session.add(
                CandidateResource(
                    candidate_profile_id=profile_id,
                    resource_type="resume",
                    label="Duplicate primary",
                    url="https://example.org/fictional.pdf",
                    source_type="user",
                    user_confirmed=True,
                    is_primary=True,
                )
            )
            try:
                await session.flush()
                raise AssertionError("duplicate_primary_accepted")
            except IntegrityError:
                await session.rollback()

        async def cas(value):
            async with factory() as session:
                try:
                    await SQLRecordStore(session).compare_and_swap(
                        "onboarding_cas_fixture", 0, {"revision": 1, "value": value}
                    )
                    await session.commit()
                    return "saved"
                except ContextError:
                    await session.rollback()
                    return "conflict"

        assert sorted(await asyncio.gather(cas("one"), cas("two"))) == [
            "conflict",
            "saved",
        ]
        ref = EvidenceReference(
            file="private-resume/fictional.pdf", content_sha256=digest
        )
        claim = make_fact(
            "contribution",
            "I implemented fictional inventory workflows.",
            "owner_supplied",
            (ref,),
            personal_claim=True,
        )
        async with factory() as session:
            service = CandidateContextService(SQLRecordStore(session))
            config = await service.save_configuration(
                CandidateConfiguration(
                    projects=(
                        ProjectConfiguration(
                            id="project-employment",
                            name="Fictional employment project",
                            priority=1,
                        ),
                    )
                ),
                expected_revision=0,
                owner_ref="fixture",
            )
            _, k = await service.build(
                "project-employment",
                expected_configuration_revision=config.revision,
                owner_facts=(claim,),
            )
            candidate = k.candidate
            await session.commit()
        async with factory() as session:
            svc = CandidateContextService(SQLRecordStore(session))
            with_approval = await svc.approve(
                "project-employment",
                expected_revision=candidate.revision,
                fact_ids=(claim.id,),
                owner_ref="fixture",
                owner_confirmed=True,
            )
            await session.commit()
            assert with_approval.commit_sha is None

        # Distinct source changes race against the same saved project revision.
        async def rebuild(text_value):
            async with factory() as session:
                svc = CandidateContextService(SQLRecordStore(session))
                # Barrier after reading the previous version forces a real CAS race.
                previous = await svc.project("project-employment")
                await barrier.wait()
                try:
                    await svc._save_project(
                        "project-employment", previous, built_at=text_value
                    )
                    await session.commit()
                    return "saved"
                except ContextError:
                    await session.rollback()
                    return "conflict"

        barrier = asyncio.Barrier(2)
        assert sorted(await asyncio.gather(rebuild("one"), rebuild("two"))) == [
            "conflict",
            "saved",
        ]
        async with factory() as session:
            svc = CandidateContextService(SQLRecordStore(session))
            revised = make_fact(
                "contribution",
                "I implemented corrected fictional inventory.",
                "owner_supplied",
                (ref,),
                personal_claim=True,
            )
            await svc.build(
                "project-employment",
                expected_configuration_revision=1,
                owner_facts=(revised,),
            )
            assert not await svc.approved_projects()
            try:
                await svc.approve(
                    "project-employment",
                    expected_revision=candidate.revision,
                    fact_ids=(claim.id,),
                    owner_ref="fixture",
                    owner_confirmed=True,
                )
                raise AssertionError("stale_project_accepted")
            except ContextError:
                await session.rollback()
        print(
            "PostgreSQL 17: canonical resume race, duplicate-primary constraint, profile preservation, record CAS, project CAS, document provenance and stale approval passed"
        )
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
