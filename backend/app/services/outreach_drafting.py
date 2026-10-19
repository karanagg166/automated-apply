"""Grounded, application-local outreach. No Gmail write client or delivery code."""

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from backend.app.ai.schemas import GenerateRequest
from backend.app.core.config import get_settings
from backend.app.models.application_answer import CandidateEvidence, CandidateResource
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.models.job import Job
from backend.app.models.outreach import OutreachLog
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.candidate_evidence_retrieval import retrieve
from backend.app.services.contact_enrichment.ranking import rank_contact
from backend.app.services.contact_enrichment.verification import (
    business_email,
    email_kind,
    email_observed_at,
    fresh,
)


class DraftConflict(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def line(value):
    return " ".join(str(value).split())


def sentences(value):
    return {s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", value) if s.strip()}


class OutreachDraftingService:
    def __init__(self, session, settings=None, answer_service=None):
        self.session, self.settings = session, settings or get_settings()
        self.answer_service = answer_service or ApplicationAnswerService(
            session, self.settings
        )

    async def context(self, contact_id, job_id=None, lock=False):
        async def get(model, key):
            stmt = (
                select(model)
                .where(model.id == key)
                .execution_options(populate_existing=True)
            )
            return await self.session.scalar(stmt.with_for_update() if lock else stmt)

        contact = (
            await self.session.get(Contact, contact_id, populate_existing=True)
            if contact_id
            else None
        )
        if contact is None:
            raise LookupError("Contact not found")
        company = await get(Company, contact.company_id)
        if not company:
            raise ValueError("contact_employer_missing")
        if lock:
            contact = await get(Contact, contact_id)
            if not contact or contact.company_id != company.id:
                raise DraftConflict("contact_employer_changed")
        job = await get(Job, job_id) if job_id else None
        if job_id and (not job or job.company_id != contact.company_id):
            raise ValueError("job_employer_mismatch")
        profile_stmt = (
            select(CandidateProfile)
            .where(CandidateProfile.singleton_key == "primary")
            .execution_options(populate_existing=True)
        )
        profile = await self.session.scalar(
            profile_stmt.with_for_update() if lock else profile_stmt
        )
        if profile is None:
            return {
                "contact": contact,
                "company": company,
                "job": job,
                "profile": None,
                "facts": [],
                "blockers": ["candidate_profile_required"],
                "warnings": [],
                "snapshot": {},
            }
        # Lock material evidence when approving; subsequent sends must recheck again in 4B.
        if lock:
            for model in (CandidateEvidence, CandidateResource):
                await self.session.scalars(
                    select(model)
                    .where(model.candidate_profile_id == profile.id)
                    .with_for_update()
                )
        evidence = await CandidateKnowledgeRepository(self.session).relevant_evidence(
            profile.id, "project"
        )
        query = " ".join(
            [
                job.title if job else "",
                (job.description or "") if job else "",
                contact.role_title,
            ]
        )[:3000]
        facts = retrieve(profile, evidence, query, "project_explanation")
        ce_stmt = (
            select(ContactEvidence)
            .where(ContactEvidence.contact_id == contact.id)
            .order_by(ContactEvidence.id)
            .limit(100)
        )
        contact_evidence = list(
            (
                await self.session.scalars(
                    ce_stmt.with_for_update() if lock else ce_stmt
                )
            ).all()
        )
        current = [
            e
            for e in contact_evidence
            if fresh(e.expires_at, 0) and e.company_id == company.id
        ]
        blockers, warnings = [], []
        if contact.do_not_contact:
            blockers.append("contact_suppressed")
        if (contact.metadata_ or {}).get("identity_review_required"):
            blockers.append("identity_conflict")
        association = [
            e
            for e in current
            if e.observed_role
            and e.observed_company
            and line(e.observed_role).casefold() == line(contact.role_title).casefold()
            and e.observed_company.casefold()
            in {company.name.casefold(), (company.domain or "").casefold()}
        ]
        if not association:
            blockers.append("current_employer_evidence_required")
        if not fresh(contact.last_checked_at, self.settings.CONTACT_CACHE_TTL_DAYS):
            blockers.append("contact_evidence_expired")
        try:
            validated_email = str(TypeAdapter(EmailStr).validate_python(contact.email))
        except ValidationError:
            validated_email = None
        if not validated_email or not business_email(validated_email, company.domain):
            blockers.append("business_email_required")
        elif email_kind(contact.email) != "person_specific":
            blockers.append("person_specific_business_email_required")
        if contact.email_status not in {"verified", "provider_reported"}:
            blockers.append("unreliable_or_speculative_recipient")
        if not fresh(email_observed_at(contact), self.settings.CONTACT_CACHE_TTL_DAYS):
            blockers.append("email_evidence_expired")
        if contact.email_status == "provider_reported":
            warnings.append("provider_reported_email_is_not_verified")
        if not facts:
            blockers.append("verified_project_contribution_required")
        resources = await CandidateKnowledgeRepository(
            self.session
        ).resolution_resources(profile.id)
        links = {
            k: str(getattr(profile, k))
            for k in ("github_url", "linkedin_url", "portfolio_url")
            if getattr(profile, k)
        }
        for resource in resources:
            if (
                resource.resource_type == "resume"
                and resource.is_primary
                and resource.user_confirmed
            ):
                links["resume"] = resource.url
        snapshot = {
            "profile_id": str(profile.id),
            "profile_version": profile.version,
            "facts": facts,
            "candidate_evidence": [
                {
                    "id": str(e.id),
                    "updated_at": str(e.updated_at),
                    "source_url": e.source_url,
                    "user_confirmed": e.user_confirmed,
                    "content": e.content,
                    "project": e.project,
                }
                for e in evidence
                if any(
                    f["reference"]["source_type"] == "candidate_evidence"
                    and f["reference"]["source_id"] == str(e.id)
                    for f in facts
                )
            ],
            "links": links,
            "contact": {
                k: str(getattr(contact, k))
                for k in (
                    "id",
                    "company_id",
                    "full_name",
                    "role_title",
                    "email",
                    "email_status",
                    "do_not_contact",
                    "updated_at",
                    "last_checked_at",
                    "last_verified_at",
                    "last_reviewed_at",
                )
            },
            "contact_metadata": contact.metadata_,
            "contact_evidence": [
                {
                    k: getattr(e, k) if k == "provenance" else str(getattr(e, k))
                    for k in (
                        "id",
                        "source",
                        "observed_company",
                        "observed_role",
                        "evidence_type",
                        "expires_at",
                        "collected_at",
                        "user_confirmed",
                        "provenance",
                    )
                }
                for e in contact_evidence
            ],
            "company": {
                "id": str(company.id),
                "name": company.name,
                "domain": company.domain,
                "metadata": company.metadata_,
            },
            "job": {
                "id": str(job.id),
                "title": job.title,
                "description": job.description,
                "url": job.job_url,
                "updated_at": str(job.updated_at),
            }
            if job
            else None,
        }
        return dict(
            contact=contact,
            company=company,
            job=job,
            profile=profile,
            facts=facts,
            links=links,
            snapshot=snapshot,
            blockers=blockers,
            warnings=warnings,
        )

    async def preview(self, request, *, origin: Literal["rest", "mcp"] = "rest"):
        if origin not in {"rest", "mcp"}:
            raise ValueError("invalid_draft_origin")
        context = await self.context(request.contact_id, request.job_id)
        result = {
            "status": "needs_input",
            "subject": None,
            "body": None,
            "requires_review": True,
            "evidence_references": [],
            "missing_information": context["blockers"],
            "unsupported_claim_flags": [],
            "warnings": context["warnings"],
            "provider_metadata": {"used_llm": False},
            "gmail_draft_id": None,
            "outbound_messages_sent": 0,
        }
        if context["blockers"]:
            return result
        result["context_hash"] = fingerprint(context["snapshot"])
        profile, contact, company, job = (
            context[k] for k in ("profile", "contact", "company", "job")
        )
        fact = context["facts"][0]
        project = fact["facts"].get("project", fact["facts"])
        contribution = project["contribution"]
        references = [fact["reference"]]
        # MCP never executes a paid provider. Owner REST callers explicitly select use_llm.
        if request.use_llm and origin == "rest":
            style = {
                "friendly": "conversational",
                "founder-focused": "founder_focused",
            }.get(request.writing_style, request.writing_style)
            answer_request = GenerateRequest(
                question="Describe my relevant project contribution for an introduction to "
                + line(contact.role_title),
                writing_style=style,
                company_name=company.name,
                job_description=job.description if job else None,
                max_characters=max(100, request.max_length - 800),
            )
            composed = await self.answer_service._compose(
                answer_request,
                "project_explanation",
                context["facts"],
                answer_request.max_characters,
                None,
            )
            result["provider_metadata"] = {
                "provider": composed.provider,
                "model": composed.model,
                "used_llm": composed.used_llm,
                "usage": composed.usage.model_dump() if composed.usage else None,
            }
            if not composed.answer:
                result["status"] = (
                    "needs_input" if composed.missing_information else composed.status
                )
                result["missing_information"] = composed.missing_information
                result["unsupported_claim_flags"] = (
                    [composed.error_code]
                    if composed.status == "validation_failed"
                    else []
                )
                result["error_code"] = composed.error_code
                return result
            contribution, references = (
                composed.answer,
                [r.model_dump() for r in composed.evidence_references],
            )
        # No company accomplishment is inferred from a job description or a contact title.
        greeting = "Hi" if request.writing_style == "friendly" else "Hello"
        target = (
            f"I'm reaching out about the saved {line(job.title)} listing at {line(company.name)}."
            if job
            else f"I'm exploring potential engineering opportunities at {line(company.name)}."
        )
        requests = {
            "professional": "Would you be open to a brief discussion about a potential fit?",
            "concise": "Would a brief conversation about fit be useful?",
            "friendly": "Would you be open to a short chat about a possible fit?",
            "technical": "Would you be open to discussing where this engineering experience could be useful?",
            "founder-focused": "Would a brief discussion about contributing to your engineering team be useful?",
        }
        project_line = (
            f"In {line(project.get('name', 'my saved project'))}: {contribution}"
        )
        if job:
            matched = [
                skill
                for skill in profile.verified_skills
                if skill.casefold() in (job.description or "").casefold()
                and skill.casefold() in json.dumps(project).casefold()
            ]
            if matched:
                project_line += (
                    " The saved listing mentions " + ", ".join(matched[:4]) + "."
                )
        parts = [
            f"{greeting} {line(contact.full_name)},",
            f"I'm {line(profile.full_name)}. {target}",
            project_line,
            requests[request.writing_style],
            line(profile.full_name),
        ]
        startup = (company.metadata_ or {}).get("startup_discovery", {})
        if (
            isinstance(startup, dict)
            and startup.get("source_url")
            and startup.get("source")
        ):
            technologies = startup.get("technologies", [])
            relevant = [
                skill
                for skill in profile.verified_skills
                if isinstance(technologies, list)
                and skill in technologies
                and skill.casefold() in json.dumps(project).casefold()
            ]
            if relevant:
                parts.insert(
                    3,
                    "The saved company source reports work with "
                    + ", ".join(relevant[:4])
                    + "; that may be relevant to my project experience.",
                )
        parts.extend(context["links"].values())
        body = "\n\n".join(parts)
        subject = line(
            f"{job.title if job else 'Engineering opportunities'} — {profile.full_name}"
        )[:255]
        if len(body) > request.max_length:
            result["missing_information"] = [
                "Increase max_length or shorten the verified contribution"
            ]
            return result
        references = references + [
            {"source_type": "candidate_profile", "source_id": str(profile.id)},
            {"source_type": "company", "source_id": str(company.id)},
            {"source_type": "contact", "source_id": str(contact.id)},
        ]
        references.extend(
            {"source_type": "contact_evidence", "source_id": e["id"]}
            for e in context["snapshot"]["contact_evidence"]
        )
        if job:
            references.append({"source_type": "job", "source_id": str(job.id)})
        result.update(
            status="draft_ready",
            subject=subject,
            body=body,
            evidence_references=references,
        )
        if request.personal_instructions:
            result["warnings"].append(
                "Personal instructions are untrusted guidance; apply any additional factual changes through review"
            )
        return result

    async def create(self, request, *, origin="rest"):
        request_hash = fingerprint(
            {
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
                "origin": origin,
            }
        )
        # Claim persistence under a stable PostgreSQL advisory lock before any billed generation.
        if (
            request.idempotency_key
            and self.session.get_bind().dialect.name == "postgresql"
        ):
            from sqlalchemy import text

            key = int(fingerprint(request.idempotency_key)[:15], 16)
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
        if request.idempotency_key:
            existing = await self.session.scalar(
                select(OutreachLog).where(
                    OutreachLog.idempotency_key == request.idempotency_key
                )
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise DraftConflict("idempotency_key_conflict")
                return await self.read(existing.id)
        preview = await self.preview(request, origin=origin)
        if preview["status"] != "draft_ready":
            return preview
        context = await self.context(request.contact_id, request.job_id, lock=True)
        if (
            context["blockers"]
            or fingerprint(context["snapshot"]) != preview["context_hash"]
        ):
            raise DraftConflict("evidence_changed_during_generation")
        draft = OutreachLog(
            contact_id=request.contact_id,
            job_id=request.job_id,
            subject=preview["subject"],
            body=preview["body"],
            recipient_email=context["contact"].email,
            candidate_profile_version=context["profile"].version,
            evidence_snapshot=context["snapshot"],
            evidence_hash=fingerprint(context["snapshot"]),
            approval_status="pending_approval",
            validation_status="requires_review",
            created_via=origin,
            generation_metadata={**preview, "max_length": request.max_length},
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )
        self.session.add(draft)
        await self.session.flush()
        return await self.read(draft.id)

    async def get(self, draft_id, lock=False):
        stmt = (
            select(OutreachLog)
            .where(OutreachLog.id == draft_id)
            .execution_options(populate_existing=True)
        )
        draft = await self.session.scalar(stmt.with_for_update() if lock else stmt)
        if draft is None:
            raise LookupError("Draft not found")
        return draft

    def approval_digest(self, draft):
        return fingerprint(
            [
                draft.subject,
                draft.body,
                draft.recipient_email,
                draft.evidence_hash,
                draft.draft_revision,
            ]
        )

    async def eligibility(self, draft, lock=False):
        try:
            context = await self.context(draft.contact_id, draft.job_id, lock=lock)
        except (LookupError, ValueError):
            return {
                "eligible_for_approval": False,
                "email_send_ready": False,
                "approval_current": False,
                "blockers": ["contact_or_job_context_missing"],
                "warnings": [],
                "requires_review": True,
            }
        blockers = list(context["blockers"])
        if fingerprint(context["snapshot"]) != draft.evidence_hash:
            blockers.append("material_evidence_changed_regenerate_draft")
        if draft.recipient_email != context["contact"].email:
            blockers.append("recipient_changed_or_unverified")
        original = draft.generation_metadata or {}
        if not original.get("body") or not original.get("subject"):
            blockers.append("legacy_draft_requires_regeneration")
        else:
            supported = sentences(original["body"])
            for fact in context["facts"]:
                project = fact["facts"].get("project", fact["facts"])
                for key in (
                    "contribution",
                    "implementation_details",
                    "engineering_challenges",
                    "solutions",
                ):
                    supported |= sentences(project.get(key) or "")
            if (
                sentences(draft.body) - supported
                or draft.subject != original["subject"]
            ):
                blockers.append("unsupported_edited_claim_requires_grounding")
        if draft.approval_status == "rejected":
            blockers.append("draft_rejected")
        ranking = rank_contact(
            context["contact"],
            context["company"],
            context["job"],
            self.settings.CONTACT_CACHE_TTL_DAYS,
        )
        verified_mailbox = any(
            e.get("evidence_type") == "mailbox_verification"
            and e.get("user_confirmed") == "True"
            and e.get("provenance", {}).get("email") == draft.recipient_email
            and e.get("provenance", {}).get("result") == "deliverable"
            and e.get("provenance", {}).get("method")
            in {"authorized_mailbox_verifier", "owner_confirmation"}
            and fresh(datetime.fromisoformat(e["expires_at"]), 0)
            for e in context["snapshot"].get("contact_evidence", [])
        )
        return {
            "eligible_for_approval": not blockers,
            "email_send_ready": bool(
                not blockers and ranking["email_send_ready"] and verified_mailbox
            ),
            "blockers": sorted(set(blockers)),
            "warnings": context["warnings"],
            "requires_review": True,
            "recipient_email": draft.recipient_email,
            "evidence_references": original.get("evidence_references", []),
            "approval_status": draft.approval_status,
            "approval_current": bool(
                not blockers
                and draft.approval_status == "approved"
                and draft.approved_revision == draft.draft_revision
                and draft.approval_hash == self.approval_digest(draft)
            ),
        }

    async def read(self, draft_id):
        draft = await self.get(draft_id)
        return {
            k: getattr(draft, k)
            for k in (
                "id",
                "job_id",
                "contact_id",
                "subject",
                "body",
                "recipient_email",
                "draft_revision",
                "approval_status",
                "approved_revision",
                "approved_at",
                "candidate_profile_version",
                "validation_status",
                "created_via",
                "last_edited_at",
                "created_at",
                "updated_at",
                "gmail_draft_id",
                "gmail_message_id",
                "sent_at",
            )
        } | {
            "eligibility": await self.eligibility(draft),
            "requires_review": True,
            "provider_metadata": draft.generation_metadata.get("provider_metadata", {}),
            "outbound_messages_sent": 0,
        }

    async def edit(self, draft_id, changes):
        draft = await self.get(draft_id, lock=True)
        if draft.draft_revision != changes.expected_revision:
            raise DraftConflict("draft_revision_conflict")
        for key, value in changes.model_dump(
            exclude={"expected_revision"}, exclude_unset=True
        ).items():
            setattr(draft, key, str(value))
        (
            draft.approval_status,
            draft.approved_at,
            draft.approval_hash,
            draft.approved_revision,
        ) = "pending_approval", None, None, None
        draft.last_edited_at, draft.validation_status = now(), "requires_review"
        await self.session.flush()
        return await self.read(draft.id)

    async def decide(self, draft_id, expected_revision, approve):
        draft = await self.get(draft_id, lock=True)
        if draft.draft_revision != expected_revision:
            raise DraftConflict("draft_revision_conflict")
        if approve:
            eligibility = await self.eligibility(draft, lock=True)
            if not eligibility["eligible_for_approval"]:
                raise DraftConflict(
                    "draft_not_eligible:" + ",".join(eligibility["blockers"])
                )
            draft.approval_status, draft.approved_at = "approved", now()
            draft.validation_status = "reviewed"
            # SQLAlchemy increments the revision for this state transition too.
            draft.approved_revision = draft.draft_revision + 1
            draft.approval_hash = fingerprint(
                [
                    draft.subject,
                    draft.body,
                    draft.recipient_email,
                    draft.evidence_hash,
                    draft.approved_revision,
                ]
            )
        else:
            (
                draft.approval_status,
                draft.approved_at,
                draft.approved_revision,
                draft.approval_hash,
            ) = "rejected", None, None, None
        await self.session.flush()
        return await self.read(draft.id)
