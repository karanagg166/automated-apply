"""Executable fictional end-to-end demonstration. In-memory SQLite and fake Gemini only."""

import asyncio
import json
import os


async def demo():
    # Override before importing settings/models. Never use a configured production database.
    os.environ.update(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        DATABASE_SCHEMA="job_agent",
        ENVIRONMENT="testing",
        GEMINI_API_KEY="",
        LLM_MODEL="",
        GMAIL_SENDING_ENABLED="false",
        MCP_REMOTE_ENABLED="false",
        LOG_LEVEL="ERROR",
    )
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.config import Settings
    from backend.app.db import session as db_module
    from backend.app.models import Base
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.applications import (
        QuestionInput,
        RevisionInput,
        SubmissionInput,
    )
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.app.services.application_answer_service import ApplicationAnswerService
    from backend.app.services.applications.review import ApplicationReview
    from backend.app.services.applications.service import ApplicationPacketService
    from backend.app.services.applications.tracker import ApplicationTracker
    from backend.tests.phase2a_fakes import PROJECT, FakeProvider
    from backend.tests.phase5a_fakes import approve, create, target

    async def deny_http(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the offline demonstration")

    httpx.AsyncHTTPTransport.handle_async_request = deny_http
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    db_module._engine, db_module._session_factory = engine, factory
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(
                CandidateProfileCreate(
                    full_name="Alex Example",
                    email="alex@example.com",
                    github_url="https://github.com/example",
                    linkedin_url="https://www.linkedin.com/in/example",
                    projects=[PROJECT],
                    verified_skills=["Python", "FastAPI"],
                )
            )
            job, _ = await target(session, profile)
            provider = FakeProvider()
            settings = Settings(
                _env_file=None,
                GEMINI_API_KEY="fictional-demo-key",
                LLM_MODEL="gemini-test-model",
            )
            service = ApplicationPacketService(
                session, ApplicationAnswerService(session, settings, provider)
            )
            packet = await create(
                service,
                job,
                questions=[
                    QuestionInput(
                        question="Describe your most technically challenging project",
                        writing_style="technical",
                    )
                ],
            )
            states = [packet.lifecycle_state]
            packet = await service.generate(
                packet.id,
                packet.fields[-1].id,
                RevisionInput(expected_revision=packet.revision),
            )
            await session.commit()
            states.append(packet.lifecycle_state)
            packet = await approve(service, packet)
            states.append(packet.lifecycle_state)
            handoff = await ApplicationReview(service).handoff(packet.id)
            evidence = await ApplicationTracker(service).report(
                packet.id,
                SubmissionInput(
                    expected_revision=packet.revision,
                    idempotency_key="fictional-demo-submission",
                    human_confirmed=True,
                    confirmation="I submitted this application on the official website",
                    receipt_reference="Fictional offline receipt ABC",
                ),
            )
            await session.commit()
            packet = await service.read(packet.id)
            states.append(packet.lifecycle_state)
            print(
                json.dumps(
                    {
                        "fictional_offline_demo": True,
                        "provider": "injected_fake_gemini",
                        "network_calls": 0,
                        "job": handoff.job_title,
                        "company": handoff.company,
                        "profile": profile.full_name,
                        "resume": handoff.resume.selected.model_dump(mode="json"),
                        "resume_upload_status": handoff.resume.upload_status,
                        "question": handoff.fields[-1].question,
                        "answer": handoff.fields[-1].effective_answer,
                        "evidence": handoff.fields[-1].provenance.model_dump(
                            mode="json"
                        ),
                        "review_status": "approved",
                        "approved_revision": handoff.approved_revision,
                        "handoff_url": handoff.application_url,
                        "handoff_submitted": handoff.submitted,
                        "manual_steps": handoff.manual_steps,
                        "lifecycle": states,
                        "submission_evidence": evidence.model_dump(mode="json"),
                        "final_tracking": packet.tracking_state,
                        "job_status_unchanged": job.status,
                        "events": [
                            e.event_type
                            for e in await ApplicationTracker(service).events(packet.id)
                        ],
                    },
                    indent=2,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(demo())
