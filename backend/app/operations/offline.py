"""A fictional integrated exercise, isolated from all configured databases and accounts."""

import tempfile
from pathlib import Path
from uuid import UUID

from backend.app.core.config import Settings, configure_operator


async def offline_demo():
    with tempfile.TemporaryDirectory(prefix="phase6b-offline-") as directory:
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_URL="sqlite+aiosqlite:///" + str(Path(directory) / "demo.db"),
            DATABASE_SCHEMA="job_agent",
            GEMINI_API_KEY="fictional-offline-model",
            LLM_MODEL="gemini-offline-fixture",
            GREENHOUSE_BOARDS={"fictional": "Fictional Robotics"},
            GMAIL_SENDING_ENABLED=False,
            MCP_REMOTE_ENABLED=False,
            LOG_LEVEL="ERROR",
        )
        configure_operator(settings)
        import httpx
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.ai.schemas import (
            EvidenceReference,
            ModelAnswer,
            ProviderAnswer,
            SupportedClaim,
        )
        from backend.app.ai.usage import LLMUsageManager
        from backend.app.models import Base
        from backend.app.models.application_answer import CandidateResource
        from backend.app.models.discovery import now
        from backend.app.models.job import Job
        from backend.app.operations.network import NetworkAudit
        from backend.app.operations.pilot import PilotRequest, run_pilot
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.applications import ReviewInput, RevisionInput
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.application_answer_service import (
            ApplicationAnswerService,
        )
        from backend.app.services.applications.review import ApplicationReview
        from backend.app.services.applications.service import ApplicationPacketService
        from backend.app.services.job_sources.direct_api import GreenhouseAdapter
        from backend.app.services.job_sources.factory import JobSourceFactory
        from backend.app.services.startup_discovery.schemas import (
            CompanyObservation,
            StartupRunRequest,
        )
        from backend.app.services.startup_discovery.service import (
            StartupDiscoveryService,
        )

        engine = create_async_engine(settings.DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        original_factory = JobSourceFactory.get_adapter

        def response(request):
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 1,
                            "title": "Backend Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/fictional/jobs/1",
                            "location": {"name": "Bengaluru, Remote"},
                            "content": "Python FastAPI backend services",
                        }
                    ]
                },
            )

        class FictionalModel:
            async def generate_structured_answer(self, question, context, instructions):
                evidence = context["evidence"][0]
                reference = EvidenceReference.model_validate(evidence["reference"])
                quote = evidence["facts"]["contribution"]
                return ProviderAnswer(
                    content=ModelAnswer(
                        answer=quote,
                        evidence_references=[reference],
                        claims=[
                            SupportedClaim(text=quote, quote=quote, source=reference)
                        ],
                    )
                )

        try:
            with NetworkAudit() as network:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(response)
                ) as http:
                    JobSourceFactory.get_adapter = staticmethod(
                        lambda source, **kw: GreenhouseAdapter(http_client=http)
                    )
                    async with factory() as session:
                        profile = await CandidateProfileRepository(
                            session
                        ).create_primary_profile(
                            CandidateProfileCreate(
                                full_name="Alex Fictional",
                                email="alex@fictional.example",
                                github_url="https://github.com/fictional",
                                linkedin_url="https://linkedin.com/in/fictional",
                                portfolio_url="https://fictional.example",
                                verified_skills=["Python", "FastAPI"],
                                verified_experience_years=0,
                                projects=[
                                    dict(
                                        name="Fictional Relay",
                                        purpose="Task updates",
                                        contribution="I implemented backend authentication using Python and FastAPI.",
                                        engineering_challenges="Concurrent authentication",
                                        solutions="I checked signed tokens.",
                                        technologies=["Python", "FastAPI"],
                                    )
                                ],
                                preferences=dict(
                                    target_titles=["Backend Engineer"],
                                    preferred_locations=["Bengaluru"],
                                    remote_preference="remote",
                                ),
                            )
                        )
                        session.add(
                            CandidateResource(
                                candidate_profile_id=profile.id,
                                resource_type="resume",
                                label="Fictional confirmed resume",
                                url="https://fictional.example/resume.pdf",
                                is_primary=True,
                                user_confirmed=True,
                            )
                        )
                        await session.commit()
                        await StartupDiscoveryService(session, factory, settings).run(
                            StartupRunRequest(
                                idempotency_key="offline_company_6b",
                                permission_confirmed=True,
                                companies=[
                                    CompanyObservation(
                                        name="Fictional Robotics",
                                        source="manual",
                                        source_url="https://fictional.example/about",
                                        permission_evidence_url="https://fictional.example/license",
                                        observed_at=now(),
                                        employee_count=18,
                                        verification_status="human_confirmed",
                                    )
                                ],
                            )
                        )
                        request = PilotRequest(
                            source="greenhouse",
                            idempotency_key="offline_pilot_6b",
                            use_profile=True,
                            prepare_packet=True,
                        )
                        result = await run_pilot(session, factory, settings, request)
                        replay = await run_pilot(session, factory, settings, request)
                        if replay["run_id"] != result["run_id"]:
                            raise RuntimeError("offline_replay_failed")
                        if len(result["application_packets"]) != 1:
                            raise RuntimeError("offline_packet_missing")
                        packet_id = UUID(result["application_packets"][0]["packet_id"])
                        answers = ApplicationAnswerService(
                            session,
                            settings,
                            FictionalModel(),
                            LLMUsageManager(factory, settings),
                        )
                        packets = ApplicationPacketService(session, answers)
                        packet = await packets.read(packet_id)
                        packet = await packets.generate(
                            packet.id,
                            packet.fields[-1].id,
                            RevisionInput(expected_revision=packet.revision),
                        )
                        await session.commit()
                        if packet.fields[-1].validation_status != "draft_ready":
                            raise RuntimeError("offline_grounding_failed")
                        packet = await ApplicationReview(packets).review(
                            packet.id,
                            ReviewInput(
                                expected_revision=packet.revision,
                                action="approve",
                                confirm_resume=True,
                                confirm_destination=True,
                                reviewed_field_ids=[
                                    f.id for f in packet.fields if f.effective_answer
                                ],
                            ),
                        )
                        await session.commit()
                        handoff = await ApplicationReview(packets).handoff(packet.id)
                        if handoff.submitted:
                            raise RuntimeError("offline_handoff_submitted")
                        job = await session.get(Job, packet.job_id)
                        if job.status == "applied":
                            raise RuntimeError("offline_job_status_mutated")
                        result["fixture_company_details"] = result.pop("companies")
                        result["fixture_application_packets"] = result.pop("application_packets")
                        result["candidate_matched_jobs"] = 0
                        result["relevant_jobs"] = 0
                        result["company_size_evidence_coverage"] = 0
                        result["application_packets_prepared"] = 0
                        result.update(
                            fictional_data=True,
                            actual_jobs=0,
                            actual_companies=0,
                            fixture_jobs=1,
                            fixture_companies=1,
                            fixture_packet_prepared=True,
                            idempotent_replay_verified=True,
                            fake_grounded_answer_validated=True,
                            fictional_review_simulated=True,
                            manual_handoff_verified=True,
                            real_pilot_verified=False,
                            **network.output(),
                        )
                        return result
        finally:
            JobSourceFactory.get_adapter = original_factory
            await engine.dispose()
