"""Offline fictional SQLite demo. Real discovery uses the approved PostgreSQL pilot."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def demo(args):
    if args.live:
        from backend.app.operations.configuration import OperationRejected

        raise OperationRejected("online_postgresql_required_use_run_startup_pilot")
    with tempfile.TemporaryDirectory(prefix="startup-demo-") as directory:
        # Set before importing ORM metadata; never load or write the operator's database.
        database_url = "sqlite+aiosqlite:///" + str(Path(directory) / "demo.db")
        os.environ.update(
            DATABASE_URL=database_url,
            DATABASE_SCHEMA="job_agent",
            ENVIRONMENT="testing",
            LOG_LEVEL="ERROR",
            APIFY_API_TOKEN="",
            SERPER_API_KEY="",
            APOLLO_API_KEY="",
            SIGNALHIRE_API_KEY="",
            HUNTER_API_KEY="",
            GMAIL_CLIENT_ID="",
            GMAIL_CLIENT_SECRET="",
            GMAIL_REFRESH_TOKEN="",
            GMAIL_SENDING_ENABLED="false",
            PEOPLE_SEARCH_ENABLED="false",
            GREENHOUSE_BOARDS=json.dumps(
                {args.greenhouse_board: args.greenhouse_company}
                if args.greenhouse_board
                else {}
            ),
        )
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.core.config import get_settings
        from backend.app.models import Base
        from backend.app.models.discovery import now
        from backend.app.services.startup_discovery.schemas import (
            CompanyObservation,
            ShortlistInput,
            StartupRunRequest,
        )
        from backend.app.services.startup_discovery.service import (
            StartupDiscoveryService,
        )

        get_settings.cache_clear()
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        try:
            async with factory() as session:
                # Fail any accidental external call, including optional AI/enrichment.
                import httpx

                from backend.app.repositories.candidate_profile import (
                    CandidateProfileRepository,
                )
                from backend.app.schemas.candidate_profile import (
                    CandidateProfileCreate,
                )
                from backend.app.schemas.normalized_job import NormalizedJob
                from backend.app.schemas.outreach import DraftInput
                from backend.app.services.applications.service import (
                    ApplicationPacketService,
                )
                from backend.app.services.discovery_budget import DiscoveryBudget
                from backend.app.services.job_ingestion import JobIngestionService
                from backend.app.services.outreach_drafting import (
                    OutreachDraftingService,
                )
                from backend.app.services.people_discovery.base import (
                    OfficialPersonEvidence,
                    PeopleQuery,
                )
                from backend.app.services.people_discovery.service import (
                    PeopleDiscoveryService,
                )
                from backend.app.services.saved_data import SavedDataService

                async def no_http(*a, **kw):
                    raise RuntimeError("External HTTP forbidden in offline demo")

                httpx.AsyncHTTPTransport.handle_async_request = no_http
                profile = await CandidateProfileRepository(
                    session
                ).create_primary_profile(
                    CandidateProfileCreate(
                        full_name="Alex Fictional",
                        email="alex@fictional.example",
                        verified_skills=["Python", "FastAPI"],
                        preferences={
                            "target_titles": ["Backend Engineer"],
                            "preferred_locations": ["Bengaluru"],
                            "remote_preference": "remote",
                            "prioritize_startups": True,
                        },
                    )
                )
                from backend.app.models.application_answer import CandidateResource

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
                service = StartupDiscoveryService(session, factory)
                company = CompanyObservation(
                    name="Fictional Robotics",
                    domain="fictional.example",
                    source="manual",
                    source_url="https://fictional.example/about",
                    permission_evidence_url="https://fictional.example/license",
                    observed_at=now(),
                    employee_count=18,
                    location="Bengaluru, India",
                    remote_policy="remote",
                    technology_stack=["Python", "FastAPI"],
                    verification_status="human_confirmed",
                )
                request = StartupRunRequest(
                    idempotency_key="offline-company-001",
                    permission_confirmed=True,
                    companies=[company],
                )
                run = await service.run(request)
                company_id = UUID(run["rankings"][0]["company_id"])
                job = NormalizedJob(
                    source_name="naukri",
                    source_job_id="offline-job-1",
                    original_url="https://www.naukri.com/job-listings-fictional-backend-example-123456",
                    application_url="https://fictional.example/jobs/backend",
                    company_name=company.name,
                    company_domain=company.domain,
                    title="Backend Engineer",
                    description="Build Python FastAPI backend services",
                    skills_required=["Python", "FastAPI"],
                    location="Bengaluru",
                    remote_type="remote",
                    source_verification_status="source_reported",
                    is_confirmed_current=True,
                    data_provenance={"fixture": True, "not_live": True},
                )
                ingested = await JobIngestionService(session).ingest_jobs([job])
                await PeopleDiscoveryService(
                    session, DiscoveryBudget(factory)
                ).search(
                    PeopleQuery(
                        company_name=company.name,
                        company_domain=company.domain,
                        source="manual",
                        permission_confirmed=True,
                        official_people=[
                            OfficialPersonEvidence(
                                full_name="Taylor Fictional",
                                role_title="Founder and CTO",
                                evidence_url="https://fictional.example/team",
                                professional_url="https://fictional.example/team/taylor",
                                permission_evidence_url="https://fictional.example/license",
                                observed_at=now(),
                                human_confirmed=True,
                            )
                        ],
                    )
                )
                await session.commit()
                shortlist = await service.shortlist(
                    company_id,
                    ShortlistInput(
                        note="Offline fictional demonstration",
                        run_id=UUID(run["id"]),
                    ),
                )
                contacts = await SavedDataService(session).contacts(company_id)
                preview = await ApplicationPacketService(session).preview(
                    UUID(ingested.job_ids[0])
                )
                draft = await OutreachDraftingService(session).create(
                    DraftInput(
                        contact_id=UUID(contacts[0]["id"]),
                        use_llm=False,
                        idempotency_key="offline-outreach-001",
                    )
                )
                output = {
                    "mode": "offline_fictional_fixtures",
                    "live_verified": False,
                    "query": "Python backend; Bengaluru/India or remote; 1–50 employees",
                    "company_first_run": run,
                    "shortlist": shortlist,
                    "contacts": contacts,
                    "application_preview": preview.model_dump(mode="json"),
                    "local_outreach_draft": draft,
                    "external_calls": 0,
                    "messages_sent": 0,
                    "applications_submitted": 0,
                }
                rendered = json.dumps(output, indent=2, default=str)
                if args.output:
                    Path(args.output).write_text(rendered + "\n")
                print(rendered)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Retired: use run_startup_pilot.py with approved online PostgreSQL",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        choices=["hacker_news", "arbeitnow", "remotive", "greenhouse"],
        default=["hacker_news"],
    )
    parser.add_argument("--greenhouse-board", default=None)
    parser.add_argument("--greenhouse-company", default=None)
    parser.add_argument("--output", default=None)
    asyncio.run(demo(parser.parse_args()))
