"""Actual FastAPI + isolated fictional SQLite fixtures for browser verification only.

Never reads a local .env, touches a configured database or calls a live provider.
"""

import asyncio
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def setup_environment(directory):
    # Only allow a fixture launcher to choose the isolated database.
    for key in list(os.environ):
        if any(
            word in key
            for word in (
                "API_KEY",
                "TOKEN",
                "DATABASE",
                "GMAIL",
                "SUPABASE",
                "CANDIDATE_",
                "OAUTH",
                "APIFY",
                "SECRET_KEY",
            )
        ):
            os.environ.pop(key, None)
    os.environ.update(
        ENVIRONMENT="testing",
        DATABASE_URL=f"sqlite+aiosqlite:///{directory}/fixture.sqlite",
        DATABASE_SCHEMA="job_agent",
        JOB_AGENT_API_TOKEN="fictional-phase7-backend-token-never-client",
        SECRET_KEY="fictional-test-secret-for-isolated-ui-only",  # pragma: allowlist secret — isolated fixture only
        UI_FIXTURE_MODE="true",
        AUTOMATION_EXECUTION_ENABLED="false",
        GMAIL_SENDING_ENABLED="false",
        MCP_REMOTE_ENABLED="false",
        LOG_LEVEL="WARNING",
        CANDIDATE_RESUME_DRIVE_URL="https://drive.google.com/file/d/fictional_drive_resume_001/view?usp=drivesdk",
    )
    from cryptography.fernet import Fernet

    os.environ["RESUME_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    from backend.app.core.config import Settings, configure_operator

    configure_operator(Settings(_env_file=None))
    import httpx

    async def deny_network(*args, **kwargs):
        raise RuntimeError(
            "Live provider HTTP is disabled in the isolated browser fixture"
        )

    httpx.AsyncHTTPTransport.handle_async_request = deny_network
    httpx.HTTPTransport.handle_request = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Live HTTP disabled")
    )
    from backend.app.resume_sync import service as resume_service
    from backend.app.resume_sync.download import DownloadedPDF
    from backend.tests.test_phase7_dashboard import pdf_bytes

    resume_checks = 0

    async def fictional_drive(file_id):
        nonlocal resume_checks
        if file_id != "fictional_drive_resume_001":
            raise RuntimeError("Only the exact fictional Drive fixture is allowed")
        resume_checks += 1
        skill = "Docker" if resume_checks <= 2 else "Redis"
        return DownloadedPDF(pdf_bytes(f"Alex Sample | alex@sample.org | Python {skill}"), "fictional_drive_resume.pdf")

    resume_service.fetch_pdf = fictional_drive


async def seed():
    import backend.app.automation.models  # noqa: F401 — register isolated fixture tables
    import backend.app.local_agent.models  # noqa: F401 — register isolated connection fixture tables
    from backend.app.db.session import get_engine, get_session_factory
    from backend.app.models.base import Base
    from backend.app.models.contact import Contact
    from backend.app.models.contact_enrichment import ContactEvidence
    from backend.app.models.discovery import now
    from backend.app.models.job import Job
    from backend.app.services.startup_discovery.evidence import ingest_company
    from backend.tests.startup_fakes import observed
    from backend.tests.test_phase7_dashboard import pdf_bytes

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        for i, (name, count, band) in enumerate(
            [
                ("Fictional Northstar Labs", 8, "unknown"),
                ("Fictional Pixel Current", None, "1-10"),
                ("Fictional Solo Systems", 1, "unknown"),
                ("Fictional Large Team", 75, "unknown"),
            ]
        ):
            company = await ingest_company(
                session,
                observed(
                    name=name,
                    domain=f"phase7-{i}.example.org",
                    source_company_id=f"phase7-{i}",
                    employee_count=count,
                    team_size_band=band,
                    location="Bengaluru, India",
                    country="India",
                    technology_stack=["Python", "FastAPI", "PostgreSQL"],
                    description="Fictional isolated UI fixture. Building reliable developer infrastructure with Python and FastAPI.",
                ),
                None,
            )
            job = Job(
                company_id=company.id,
                title="Backend Engineer",
                job_url=f"https://job-boards.greenhouse.io/fictional/jobs/{i + 1}",
                application_url=f"https://phase7-{i}.example.org/careers/backend",
                source_platform="greenhouse",
                location="Bengaluru, India",
                skills_required=["Python", "FastAPI"],
                description="Fictional backend role for isolated browser tests.",
                status="discovered",
                remote_type="remote",
                last_observed_at=now(),
                source_verification_status="source_reported",
                match_score=88 if i == 0 else 60,
                discovery_metadata={"is_confirmed_current": True},
            )
            session.add(job)
            if i == 0:
                contact = Contact(
                    company_id=company.id,
                    full_name="Jordan Fictional",
                    role_title="CTO",
                    enrichment_source="manual",
                    email="jordan@phase7-0.example.org",
                    email_status="provider_reported",
                    last_checked_at=now(),
                    metadata_={
                        "identity_human_confirmed": True,
                        "evidence_strength": "strong",
                        "email_observed_at": now().isoformat(),
                        "email_kind": "person_specific",
                    },
                )
                session.add(contact)
                await session.flush()
                session.add(
                    ContactEvidence(
                        contact_id=contact.id,
                        company_id=company.id,
                        source="manual",
                        evidence_type="official_company_team",
                        strength="strong",
                        observed_role="CTO",
                        observed_company=company.name,
                        evidence_url="https://phase7-0.example.org/team",
                        user_confirmed=True,
                        expires_at=now() + timedelta(days=30),
                        provenance={
                            "full_name": "Jordan Fictional",
                            "role_title": "CTO",
                            "company_domain": company.domain,
                            "permission_evidence_url": "https://phase7-0.example.org/permission",
                        },
                    )
                )
        await session.commit()
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/phase7-fictional-resume.pdf").write_bytes(
        pdf_bytes("Alex Sample | alex@sample.org | Python FastAPI PostgreSQL")
    )


if __name__ == "__main__":
    if os.environ.get("PHASE7_ISOLATED_UI") != "true":
        raise SystemExit(
            "Set PHASE7_ISOLATED_UI=true; this launcher is only for fictional isolated testing"
        )
    with tempfile.TemporaryDirectory(prefix="automated-apply-phase7-ui-") as directory:
        setup_environment(directory)
        asyncio.run(seed())
        import uvicorn

        from backend.app.main import app

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8765,
            log_level="warning",
            access_log=False,
        )
