"""Candidate-scoped persistence. Callers own transactions, except AI usage reservations."""
from datetime import datetime, timezone

from sqlalchemy import select, case, cast, String, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.models.application_answer import CandidateResource, CandidateEvidence, ApplicationAnswerDraft
from backend.app.repositories.candidate_profile import (
    CandidateProfileRepository, ProfileConflictError, ProfileNotFoundError, ProfilePreconditionError,
)
from backend.app.schemas.candidate_profile import CandidateProfileUpdate
from backend.app.schemas.candidate_resources import EvidenceWrite, EvidencePatch, ResourceWrite

STANDARD_FIELDS = {"github": "github_url", "linkedin": "linkedin_url", "portfolio": "portfolio_url"}


class CandidateKnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def profile(self):
        profile = await CandidateProfileRepository(self.session).get_primary_profile()
        if profile is None:
            raise ProfileNotFoundError("Save a candidate profile first")
        return profile

    async def resources(self, profile_id, offset=0, limit=100):
        return list((await self.session.scalars(select(CandidateResource).where(
            CandidateResource.candidate_profile_id == profile_id
        ).order_by(CandidateResource.created_at, CandidateResource.id).offset(offset).limit(limit))).all())

    async def save_resource(self, data: ResourceWrite):
        profile = await self.profile()
        if data.resource_type in STANDARD_FIELDS:
            if data.id or not data.user_confirmed:
                raise ProfileConflictError("Standard links require explicit user confirmation and are stored only on the profile")
            if data.expected_profile_version is None:
                raise ProfilePreconditionError("Supply expected_profile_version to change a standard profile link")
            field = STANDARD_FIELDS[data.resource_type]
            profile = await CandidateProfileRepository(self.session).update_primary_profile(
                CandidateProfileUpdate.model_validate({field: str(data.url)}), data.expected_profile_version)
            return {"resource_type": data.resource_type, "url": getattr(profile, field),
                    "source": "candidate_profile", "user_confirmed": True}
        values = data.model_dump(mode="json", exclude={"id", "expected_profile_version"})
        if data.id:
            item = await self.session.scalar(select(CandidateResource).where(
                CandidateResource.id == data.id, CandidateResource.candidate_profile_id == profile.id
            ).with_for_update())
            if item is None:
                raise ProfileNotFoundError("Resource not found")
            for key, value in values.items():
                setattr(item, key, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise ProfileConflictError("Duplicate URL or conflicting primary resource") from exc
        else:
            insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
            statement = insert(CandidateResource).values(candidate_profile_id=profile.id, **values).on_conflict_do_nothing().returning(CandidateResource)
            item = (await self.session.execute(statement)).scalar_one_or_none()
            if item is None:
                raise ProfileConflictError("Duplicate URL or conflicting primary resource; update the existing resource or demote its primary first")
        return item

    async def evidence(self, profile_id, offset=0, limit=100, confirmed_only=False):
        query = select(CandidateEvidence).where(CandidateEvidence.candidate_profile_id == profile_id)
        if confirmed_only:
            query = query.where(CandidateEvidence.user_confirmed.is_(True))
        return list((await self.session.scalars(query.order_by(
            CandidateEvidence.created_at, CandidateEvidence.id).offset(offset).limit(limit))).all())

    async def relevant_evidence(self, profile_id, question):
        # Rank across all confirmed rows in SQL before bounding the prompt candidates.
        from backend.app.services.candidate_evidence_retrieval import tokens
        words = sorted(tokens(question))[:25]
        searchable = func.lower(CandidateEvidence.title + " " + CandidateEvidence.content + " " +
                                func.coalesce(cast(CandidateEvidence.project, String), ""))
        score = sum((case((searchable.contains(word, autoescape=True), 1), else_=0) for word in words), 0)
        query = select(CandidateEvidence).where(
            CandidateEvidence.candidate_profile_id == profile_id, CandidateEvidence.user_confirmed.is_(True)
        )
        if words:
            query = query.order_by(score.desc())
        query = query.order_by(CandidateEvidence.updated_at.desc(), CandidateEvidence.id).limit(100)
        return list((await self.session.scalars(query)).all())

    async def add_evidence(self, data: EvidenceWrite):
        profile = await self.profile()
        item = CandidateEvidence(candidate_profile_id=profile.id, **data.model_dump(mode="json"))
        self.session.add(item)
        await self.session.flush()
        return item

    async def patch_evidence(self, evidence_id, data: EvidencePatch):
        profile = await self.profile()
        item = await self.session.scalar(select(CandidateEvidence).where(
            CandidateEvidence.id == evidence_id, CandidateEvidence.candidate_profile_id == profile.id
        ).with_for_update())
        if item is None:
            raise ProfileNotFoundError("Evidence not found")
        values = data.model_dump(mode="json", exclude_unset=True)
        if "user_confirmed" not in values and values.keys() - {"user_confirmed"}:
            values["user_confirmed"] = False  # Corrections require fresh approval.
        complete = EvidenceWrite.model_validate({**EvidenceWrite.model_validate(item).model_dump(mode="json"), **values})
        for key, value in complete.model_dump(mode="json").items():
            setattr(item, key, value)
        await self.session.flush()
        return item

    async def save_draft(self, profile, request, result):
        item = ApplicationAnswerDraft(
            candidate_profile_id=profile.id, job_id=request.job_id, question=request.question,
            answer=result.answer, question_category=result.question_type, writing_style=request.writing_style,
            provider=result.provider, model=result.model,
            evidence_references=[r.model_dump() for r in result.evidence_references],
            candidate_profile_version=profile.version, review_status="draft",
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def drafts(self, profile_id, offset=0, limit=25):
        return list((await self.session.scalars(select(ApplicationAnswerDraft).where(
            ApplicationAnswerDraft.candidate_profile_id == profile_id
        ).order_by(ApplicationAnswerDraft.created_at.desc(), ApplicationAnswerDraft.id).offset(offset).limit(limit))).all())

    async def review_draft(self, draft_id, status):
        profile = await self.profile()
        item = await self.session.scalar(select(ApplicationAnswerDraft).where(
            ApplicationAnswerDraft.id == draft_id, ApplicationAnswerDraft.candidate_profile_id == profile.id
        ).with_for_update())
        if item is None:
            raise ProfileNotFoundError("Draft not found")
        if status == "reviewed" and item.candidate_profile_version != profile.version:
            raise ProfileConflictError("Draft is stale; regenerate or correct the profile before reviewing")
        item.review_status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return item
