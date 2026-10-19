"""Bearer-protected review APIs. No message creation or delivery operations."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.usage import concurrency_limiter
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session, get_session_factory
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import (
    ContactEnrichmentRun,
    ContactEvidence,
    ContactIdentity,
)
from backend.app.models.discovery import now
from backend.app.models.job import Job
from backend.app.schemas.contact import EmailVerificationStatus
from backend.app.services.contact_enrichment.contact_identity import IdentityConflict
from backend.app.services.contact_enrichment.ranking import rank_contact
from backend.app.services.contact_enrichment.schemas import (
    ContactCorrection,
    EnrichInput,
)
from backend.app.services.contact_enrichment.service import ContactEnrichmentService
from backend.app.services.contact_enrichment.verification import (
    email_observed_at,
    fresh,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Contact enrichment"],
    dependencies=[Depends(require_api_token)],
)


def enrichment_service(session: AsyncSession = Depends(get_db_session)):
    return ContactEnrichmentService(session, get_session_factory())


def run_output(run):
    return {
        "id": str(run.id),
        "company_id": str(run.company_id),
        "state": run.state,
        "target_roles": run.target_roles,
        "provider_plan": run.provider_plan,
        "contact_ids": run.contact_ids,
        "counts": run.counts,
        "usage": run.usage,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "errors": run.errors,
    }


def contact_output(contact, company, job=None):
    settings = get_settings()
    ranking = rank_contact(contact, company, job, settings.CONTACT_CACHE_TTL_DAYS)
    expired = contact.enrichment_source in {"apollo", "signalhire"} and not fresh(
        email_observed_at(contact), settings.CONTACT_RETENTION_DAYS
    )
    if expired:
        ranking.update(
            email_send_ready=False,
            manual_outreach_review_available=False,
            manual_linkedin_available=False,
        )
    return {
        "id": str(contact.id),
        "company_id": str(contact.company_id),
        "company": company.name,
        "full_name": contact.full_name,
        "role_title": contact.role_title,
        "linkedin_url": None if expired else contact.linkedin_url,
        "email": None if expired else contact.email,
        "email_status": "unknown" if expired else contact.email_status,
        "source": contact.enrichment_source,
        "legacy_confidence_score": float(contact.confidence_score or 0),
        "last_checked_at": contact.last_checked_at,
        "last_reviewed_at": contact.last_reviewed_at,
        "do_not_contact": contact.do_not_contact,
        "suppression_reason": contact.suppression_reason,
        "human_review_notes": contact.human_review_notes,
        "associated_job_ids": (contact.metadata_ or {}).get("job_ids", [])[:100],
        "retention_expired": expired,
        **ranking,
    }


async def get_contact(session, contact_id, lock=False):
    statement = select(Contact).where(Contact.id == contact_id)
    if lock:
        statement = statement.with_for_update()
    contact = await session.scalar(statement)
    if contact is None:
        raise HTTPException(404, "Contact not found")
    return contact


@router.get("/contact-enrichment/providers")
async def providers(service=Depends(enrichment_service)):
    return {"providers": await service.provider_status()}


@router.post("/companies/{company_id}/contacts/preview")
async def preview(
    company_id: UUID, data: EnrichInput, service=Depends(enrichment_service)
):
    try:
        return await service.preview(company_id, data)
    except LookupError:
        raise HTTPException(404, "Company not found") from None


@router.post("/companies/{company_id}/contacts/enrich")
async def enrich(
    company_id: UUID, data: EnrichInput, service=Depends(enrichment_service)
):
    try:
        async with concurrency_limiter(
            service.settings.CONTACT_ENRICHMENT_MAX_CONCURRENCY
        ):
            # Every provider request has its own finite deadline; run size is bounded.
            return run_output(await service.enrich(company_id, data))
    except LookupError:
        raise HTTPException(404, "Company not found") from None
    except IdentityConflict:
        raise HTTPException(
            409, "Idempotency key belongs to a different request"
        ) from None


@router.get("/contact-enrichment/runs/{run_id}")
async def get_run(run_id: UUID, session: AsyncSession = Depends(get_db_session)):
    run = await session.get(ContactEnrichmentRun, run_id)
    if run is None:
        raise HTTPException(404, "Enrichment run not found")
    return run_output(run)


@router.get("/companies/{company_id}/contacts")
async def list_contacts(
    company_id: UUID,
    role: str | None = Query(None, max_length=255),
    email_status: EmailVerificationStatus | None = None,
    provider: Literal["apollo", "signalhire", "manual", "public_search"] | None = None,
    min_evidence_strength: Literal["weak", "moderate", "strong"] | None = None,
    last_observed_after: datetime | None = None,
    suppressed: bool | None = None,
    has_linkedin: bool | None = None,
    has_business_email: bool | None = None,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "Company not found")
    stmt = select(Contact).where(Contact.company_id == company_id)
    if role:
        stmt = stmt.where(
            Contact.role_title.ilike(
                "%" + role.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"
            )
        )
    if email_status:
        stmt = stmt.where(Contact.email_status == email_status.value)
    if suppressed is not None:
        stmt = stmt.where(Contact.do_not_contact == suppressed)
    if has_linkedin is not None:
        stmt = stmt.where(
            Contact.linkedin_url.is_not(None)
            if has_linkedin
            else Contact.linkedin_url.is_(None)
        )
    if has_business_email is not None:
        present = Contact.email.is_not(None) & Contact.email_status.in_(
            ["provider_reported", "verified"]
        )
        stmt = stmt.where(present if has_business_email else ~present)
    if last_observed_after:
        stmt = stmt.where(Contact.last_checked_at >= last_observed_after)
    if provider or min_evidence_strength:
        evidence = select(ContactEvidence.contact_id).where(
            ContactEvidence.contact_id == Contact.id
        )
        if provider:
            evidence = evidence.where(ContactEvidence.source == provider)
        if min_evidence_strength:
            choices = {
                "weak": ["weak", "moderate", "strong"],
                "moderate": ["moderate", "strong"],
                "strong": ["strong"],
            }[min_evidence_strength]
            evidence = evidence.where(
                ContactEvidence.strength.in_(choices),
                ContactEvidence.expires_at > now(),
            )
        stmt = stmt.where(evidence.exists())
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    contacts = (
        await session.scalars(stmt.order_by(Contact.id).offset(offset).limit(limit))
    ).all()
    return {
        "contacts": [contact_output(c, company) for c in contacts],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/contacts/{contact_id}")
async def detail(contact_id: UUID, session: AsyncSession = Depends(get_db_session)):
    contact = await get_contact(session, contact_id)
    company = await session.get(Company, contact.company_id)
    evidence = (
        await session.scalars(
            select(ContactEvidence)
            .where(ContactEvidence.contact_id == contact_id)
            .order_by(ContactEvidence.collected_at.desc())
            .limit(100)
        )
    ).all()
    return {
        **contact_output(contact, company),
        "evidence": [
            {
                "id": str(e.id),
                "source": e.source,
                "type": e.evidence_type,
                "url": e.evidence_url,
                "observed_role": e.observed_role,
                "observed_company": e.observed_company,
                "provider_verification_claim": e.provider_verification_claim,
                "strength": e.strength,
                "collected_at": e.collected_at,
                "expires_at": e.expires_at,
                "user_confirmed": e.user_confirmed,
                "provenance": e.provenance
                if fresh(e.expires_at, 0)
                else {"expired": True},
            }
            for e in evidence
        ],
    }


@router.patch("/contacts/{contact_id}")
async def correct(
    contact_id: UUID,
    data: ContactCorrection,
    session: AsyncSession = Depends(get_db_session),
):
    # Same company lock order as ingestion avoids correction/enrichment races.
    initial = await get_contact(session, contact_id)
    await session.scalar(
        select(Company.id).where(Company.id == initial.company_id).with_for_update()
    )
    contact = await get_contact(session, contact_id, lock=True)
    await session.refresh(contact)
    if data.email_status == "verified":
        evidence = (
            await session.get(ContactEvidence, data.verification_evidence_id)
            if data.verification_evidence_id
            else None
        )
        if not (
            contact.email
            and evidence
            and evidence.contact_id == contact.id
            and evidence.evidence_type == "mailbox_verification"
            and evidence.user_confirmed
            and evidence.provenance.get("email") == contact.email
            and evidence.provenance.get("result") == "deliverable"
            and evidence.provenance.get("method")
            in {"authorized_mailbox_verifier", "owner_confirmation"}
            and fresh(evidence.expires_at, 0)
        ):
            raise HTTPException(
                422,
                "A current supported verification record for this mailbox is required",
            )
        contact.last_verified_at = now()
    elif data.email_status == "provider_reported" and not contact.email:
        raise HTTPException(422, "No business email is recorded")
    values = data.model_dump(exclude_unset=True, exclude={"verification_evidence_id"})
    if any(
        values.get(k) is None
        for k in (
            "full_name",
            "role_title",
            "company_id",
            "email_status",
            "do_not_contact",
        )
        if k in values
    ):
        raise HTTPException(422, "Required contact fields cannot be null")
    if data.company_id and data.company_id != contact.company_id:
        if await session.get(Company, data.company_id) is None:
            raise HTTPException(404, "Company not found")
        if contact.email:
            raise HTTPException(
                409,
                "Review or remove existing company email before changing affiliation",
            )
        await session.execute(
            delete(ContactIdentity).where(ContactIdentity.contact_id == contact_id)
        )
    before = {
        k: str(getattr(contact, k)) if getattr(contact, k) is not None else None
        for k in values
    }
    for key, value in values.items():
        setattr(contact, key, value)
    contact.human_corrected, contact.last_reviewed_at = True, now()
    session.add(
        ContactEvidence(
            contact_id=contact.id,
            company_id=contact.company_id,
            source="manual",
            evidence_type="human_correction",
            strength="strong",
            user_confirmed=True,
            expires_at=now() + timedelta(days=get_settings().CONTACT_RETENTION_DAYS),
            provenance={"previous_values": before, "changed_fields": list(values)},
        )
    )
    await session.flush()
    company = await session.get(Company, contact.company_id)
    return contact_output(contact, company)


@router.get("/jobs/{job_id}/recommended-contacts")
async def recommended(
    job_id: UUID,
    limit: int = Query(10, ge=1, le=25),
    session: AsyncSession = Depends(get_db_session),
):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    company = await session.get(Company, job.company_id) if job.company_id else None
    if company is None:
        return {"contacts": []}
    contacts = (
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company.id, Contact.do_not_contact.is_(False))
            .order_by(Contact.id)
            .limit(1000)
        )
    ).all()
    ranked = [contact_output(c, company, job) for c in contacts]
    ranked.sort(key=lambda c: c["ordering_score"], reverse=True)
    return {
        "job_id": str(job.id),
        "contacts": ranked[:limit],
        "outreach_mode": "manual_review",
        "outbound_messages_sent": 0,
    }
