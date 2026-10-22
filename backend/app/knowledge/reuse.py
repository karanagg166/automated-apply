"""High-precision semantic intent reuse of explicitly approved narrative drafts.

No remote embeddings, models or fuzzy company matching. Unknown paraphrases fall
through to normal grounded generation. Factual answers and consent never use this bank.
"""

import re

from fastapi import HTTPException
from pydantic import Field, StrictBool
from sqlalchemy import String, cast, select

from backend.app.ai.schemas import AnswerGenerationResult, Contract, EvidenceReference
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.models.application_answer import (
    ApplicationAnswerDraft,
    CandidateEvidence,
)
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.services.applications.resume_selector import digest
from backend.app.services.profile_link_resolver import normalize

NARRATIVES = {
    "project_explanation",
    "technical_experience",
    "short_text",
    "motivation",
    "startup_interest",
}
WORDS = set(
    "describe explain tell us me about your you my i a an the of and or to in with using used use built build developed develop implemented implement created create made make have has how what why most best biggest technically technical engineering challenging challenge challenges difficult difficulty problem problems solved solve solution solutions project projects application applications tool tools work worked experience contribution contributions purpose does it do impressive thing proud proudest are is which interests interest interested join joining want would like company role startup yourself professional summary short bio introduce for this our".split()
)


class ApproveReuse(Contract):
    expected_profile_version: int = Field(ge=1)
    scope: str = Field(pattern=r"^(same_job|general_profile)$")
    confirm_reviewed_answer: StrictBool


def semantic_intent(question, category, profile):
    if category not in NARRATIVES:
        return None
    q = normalize(question)
    skills = sorted(
        s.casefold()
        for s in profile.verified_skills
        if re.search(r"(?<!\w)" + re.escape(s.casefold()) + r"(?!\w)", q)
    )
    projects = sorted(
        p["name"].casefold() for p in profile.projects if p["name"].casefold() in q
    )
    words = set(re.findall(r"[a-z]+", q))
    entity_words = set(re.findall(r"[a-z]+", " ".join(skills + projects)))
    if words - WORDS - entity_words:
        return None
    if category in {"motivation", "startup_interest"}:
        intent = "company_motivation"
    elif category == "short_text":
        intent = "professional_summary"
    elif re.search(r"\b(challeng\w*|difficult\w*|problem|solv\w*)\b", q):
        intent = "engineering_challenge"
    elif category == "technical_experience":
        intent = "technical_usage"
    else:
        intent = "project_overview"
    return {"intent": intent, "skills": skills, "projects": projects}


async def evidence_digest(session, profile):
    rows = list(
        (
            await session.scalars(
                select(CandidateEvidence)
                .where(CandidateEvidence.candidate_profile_id == profile.id)
                .order_by(CandidateEvidence.id)
            )
        ).all()
    )
    return digest(
        {
            "profile_id": str(profile.id),
            "version": profile.version,
            "evidence": [
                (str(r.id), r.title, r.content, r.project, r.user_confirmed)
                for r in rows
            ],
        }
    )


async def job_digest(session, job_id):
    if not job_id:
        return None
    job = await session.get(Job, job_id)
    if not job:
        return None
    company = await session.get(Company, job.company_id) if job.company_id else None
    return digest(
        {
            "id": str(job.id),
            "title": job.title,
            "url": job.application_url or job.job_url,
            "description": job.description,
            "reviewed_opportunity": (job.discovery_metadata or {}).get(
                "application_opportunity"
            ),
            "company_id": str(job.company_id),
            "company": company.name if company else None,
            "domain": company.domain if company else None,
            "metadata": company.metadata_ if company else None,
        }
    )


def draft_digest(draft):
    return digest(
        {
            "question": draft.question,
            "answer": draft.answer,
            "category": draft.question_category,
            "style": draft.writing_style,
            "references": draft.evidence_references,
            "job_id": str(draft.job_id),
        }
    )


async def approve(session, draft_id, data):
    if not get_settings().APPROVED_ANSWER_REUSE_ENABLED:
        raise HTTPException(503, "Approved answer reuse is disabled")
    repo = CandidateKnowledgeRepository(session)
    profile = await repo.profile()
    draft = await session.scalar(
        select(ApplicationAnswerDraft)
        .where(
            ApplicationAnswerDraft.id == draft_id,
            ApplicationAnswerDraft.candidate_profile_id == profile.id,
        )
        .with_for_update()
    )
    if not draft:
        raise HTTPException(404, "Saved answer draft not found")
    if (
        not data.confirm_reviewed_answer
        or draft.review_status != "reviewed"
        or profile.version != data.expected_profile_version
        or draft.candidate_profile_version != profile.version
    ):
        raise HTTPException(
            409, "Review the current answer and candidate facts before approving reuse"
        )
    intent = semantic_intent(draft.question, draft.question_category, profile)
    if not intent:
        raise HTTPException(
            422,
            "This question requires individual review; no supported reuse intent is established",
        )
    if data.scope == "same_job" and not draft.job_id:
        raise HTTPException(422, "Same-job reuse requires a saved job context")
    if data.scope == "general_profile" and intent["intent"] == "company_motivation":
        raise HTTPException(
            422, "Company motivation can only be reused for the exact saved job"
        )
    if data.scope == "general_profile" and any(
        r.get("source_type", "").startswith("opportunity_")
        for r in draft.evidence_references
    ):
        raise HTTPException(
            422, "Employer evidence can only be reused for the exact saved job"
        )
    refs = {
        (r["source_type"], r["source_id"])
        for r in draft.evidence_references
        if r.get("source_type", "").startswith("opportunity_")
    }
    if refs:
        if not get_settings().OPPORTUNITY_CONTEXT_ENABLED:
            raise HTTPException(503, "Reviewed opportunity context is disabled")
        from backend.app.knowledge.opportunity import reviewed_context

        job = await session.get(Job, draft.job_id) if draft.job_id else None
        company = (
            await session.get(Company, job.company_id)
            if job and job.company_id
            else None
        )
        current = reviewed_context(job, company) if job else []
        if not refs <= {
            (f["reference"]["source_type"], f["reference"]["source_id"])
            for f in current
        }:
            raise HTTPException(
                409,
                "Employer evidence changed or expired; generate and review a fresh answer",
            )
    key = "answer:" + str(draft.id)
    saved = await session.get(OwnerPreference, key)
    if not saved:
        saved = OwnerPreference(key=key, value={})
        session.add(saved)
    saved.value = {
        "approved": True,
        "profile_id": str(profile.id),
        "profile_version": profile.version,
        "draft_hash": draft_digest(draft),
        "evidence_hash": await evidence_digest(session, profile),
        "job_hash": await job_digest(session, draft.job_id),
        "scope": data.scope,
        "intent": intent,
    }
    await session.flush()
    return {
        "draft_id": str(draft.id),
        "scope": data.scope,
        "approved": True,
        "intent": intent,
        "profile_version": profile.version,
    }


async def revoke(session, draft_id):
    profile = await CandidateKnowledgeRepository(session).profile()
    draft = await session.get(ApplicationAnswerDraft, draft_id)
    if not draft or draft.candidate_profile_id != profile.id:
        raise HTTPException(404, "Saved answer draft not found")
    saved = await session.get(OwnerPreference, "answer:" + str(draft_id))
    if saved:
        saved.value = {**saved.value, "approved": False}
    return {"draft_id": str(draft_id), "approved": False}


async def reuse(
    session,
    profile,
    request,
    category,
    max_chars,
    max_words,
    *,
    allow_opportunity=False,
):
    intent = semantic_intent(request.question, category, profile)
    if not intent:
        return None
    rows = (
        await session.execute(
            select(ApplicationAnswerDraft, OwnerPreference)
            .join(
                OwnerPreference,
                OwnerPreference.key
                == "answer:" + cast(ApplicationAnswerDraft.id, String),
            )
            .where(
                ApplicationAnswerDraft.candidate_profile_id == profile.id,
                ApplicationAnswerDraft.candidate_profile_version == profile.version,
                ApplicationAnswerDraft.review_status == "reviewed",
                ApplicationAnswerDraft.writing_style == request.writing_style,
            )
            .order_by(
                ApplicationAnswerDraft.updated_at.desc(), ApplicationAnswerDraft.id
            )
            .limit(100)
        )
    ).all()
    evidence_hash = await evidence_digest(session, profile)
    context_hash = await job_digest(session, request.job_id)
    for draft, stored in rows:
        opportunity_refs = {
            (r["source_type"], r["source_id"])
            for r in draft.evidence_references
            if r.get("source_type", "").startswith("opportunity_")
        }
        if opportunity_refs:
            if not allow_opportunity:
                continue
            from backend.app.knowledge.opportunity import reviewed_context

            job = await session.get(Job, request.job_id) if request.job_id else None
            company = (
                await session.get(Company, job.company_id)
                if job and job.company_id
                else None
            )
            current = reviewed_context(job, company) if job else []
            if not opportunity_refs <= {
                (f["reference"]["source_type"], f["reference"]["source_id"])
                for f in current
            }:
                continue
        binding = stored.value
        if (
            not binding.get("approved")
            or binding.get("intent") != intent
            or binding.get("profile_id") != str(profile.id)
            or binding.get("profile_version") != profile.version
            or binding.get("draft_hash") != draft_digest(draft)
            or binding.get("evidence_hash") != evidence_hash
        ):
            continue
        if binding["scope"] == "same_job" and (
            draft.job_id != request.job_id or binding.get("job_hash") != context_hash
        ):
            continue
        if len(draft.answer) > max_chars or (
            max_words is not None and len(draft.answer.split()) > max_words
        ):
            continue
        return AnswerGenerationResult(
            question_type=category,
            status="draft_ready",
            answer=draft.answer,
            writing_style=request.writing_style,
            source="approved_answer",
            confidence=0.95,
            requires_review=True,
            used_llm=False,
            evidence_references=[
                EvidenceReference.model_validate(r) for r in draft.evidence_references
            ],
            draft_id=draft.id,
            reused_draft_id=draft.id,
            warnings=[
                "Reused an explicitly approved answer with the same supported intent and current evidence; review for this form"
            ],
        )
    return None


async def approvals(session, profile_id):
    rows = (
        await session.execute(
            select(ApplicationAnswerDraft, OwnerPreference)
            .join(
                OwnerPreference,
                OwnerPreference.key
                == "answer:" + cast(ApplicationAnswerDraft.id, String),
            )
            .where(ApplicationAnswerDraft.candidate_profile_id == profile_id)
            .order_by(ApplicationAnswerDraft.updated_at.desc())
            .limit(100)
        )
    ).all()
    return {
        str(d.id): {
            "approved": v.value.get("approved", False),
            "scope": v.value.get("scope"),
        }
        for d, v in rows
    }
