"""Fictional end-to-end demonstration; disposable SQLite and mock providers only."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "testing"


async def main():
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.models.base import Base
    from backend.app.models.company import Company
    from backend.app.models.contact import Contact
    from backend.app.models.contact_enrichment import ContactEvidence
    from backend.app.models.discovery import DiscoveredPerson
    from backend.app.models.outreach import OutreachLog
    from backend.app.services.contact_enrichment.ranking import rank_contact
    from backend.app.services.contact_enrichment.schemas import EnrichInput
    from backend.app.services.contact_enrichment.service import ContactEnrichmentService
    from backend.tests.contact_enrichment_fakes import (
        URL,
        FakeApollo,
        FakeSignal,
        settings,
    )

    with tempfile.TemporaryDirectory(prefix="contact-demo-") as directory:
        engine = create_async_engine("sqlite+aiosqlite:///" + directory + "/demo.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                company = Company(
                    name="Fictional Startup",
                    domain="fictional.example.com",
                    metadata_={"employee_count": 12},
                )
                session.add(company)
                await session.flush()
                session.add(
                    DiscoveredPerson(
                        company_id=company.id,
                        name="Alex Fictional",
                        role="CTO",
                        linkedin_url=URL,
                        evidence_url="https://fictional.example.com/team",
                        source="manual",
                        verification_status="public_evidence_unverified",
                    )
                )
                await session.commit()
                apollo, signal = FakeApollo(), FakeSignal()
                service = ContactEnrichmentService(
                    session,
                    factory,
                    settings(),
                    {"apollo": apollo, "signalhire": signal},
                )
                preview = await service.preview(company.id, EnrichInput())
                first = await service.enrich(
                    company.id,
                    EnrichInput(
                        allow_paid=True,
                        providers=["apollo", "signalhire"],
                        idempotency_key="fictional-demo-1",
                    ),
                )
                second = await service.enrich(
                    company.id,
                    EnrichInput(allow_paid=True, idempotency_key="fictional-demo-2"),
                )
                contact = await session.scalar(
                    select(Contact).where(Contact.company_id == company.id)
                )
                evidence = (
                    await session.scalars(
                        select(ContactEvidence).where(
                            ContactEvidence.contact_id == contact.id
                        )
                    )
                ).all()
                assert len(apollo.calls) == 1 and not signal.calls
                assert (
                    await session.scalar(select(func.count()).select_from(Contact)) == 1
                )
                assert contact.email_status == "provider_reported"
                outbound = await session.scalar(
                    select(func.count()).select_from(OutreachLog)
                )
                assert outbound == 0
                print(
                    json.dumps(
                        {
                            "mode": "fictional_mock_only",
                            "startup": company.name,
                            "initial_cached_contacts": len(preview["cached_contacts"]),
                            "discovered_people": preview["discovered_people"],
                            "first_run": str(first.id),
                            "second_run": str(second.id),
                            "mock_provider_calls": {
                                "apollo": len(apollo.calls),
                                "signalhire": len(signal.calls),
                            },
                            "canonical_contacts": 1,
                            "contact": {
                                "name": contact.full_name,
                                "role": contact.role_title,
                                "linkedin_url": contact.linkedin_url,
                                "email": contact.email,
                                "email_status": contact.email_status,
                                **rank_contact(contact, company),
                            },
                            "evidence": [
                                {
                                    "source": e.source,
                                    "url": e.evidence_url,
                                    "role": e.observed_role,
                                }
                                for e in evidence
                            ],
                            "outreach_rows": outbound,
                            "real_provider_credits_used": 0,
                        },
                        indent=2,
                    )
                )
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
