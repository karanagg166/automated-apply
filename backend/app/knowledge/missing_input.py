"""Durable, context-bound questions using existing private owner records.

Drafts are never evidence. Exact-context answer approval is separate from the
existing opt-in reusable-answer bank and never changes candidate profile facts.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, StrictBool, model_validator
from sqlalchemy import String, cast, select, update

from backend.app.ai.schemas import Contract, GenerateRequest
from backend.app.dashboard.models import OwnerPreference
from backend.app.models.application_answer import ApplicationAnswerDraft
from backend.app.models.application_packet import ApplicationPacket
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.repositories.candidate_profile import ProfileConflictError
from backend.app.services.discovery_budget import insert_for

PREFIX = "needs_input:"
SENSITIVE = re.compile(
    r"password|passcode|verification code|one.time (?:code|password)|"
    r"social security|government (?:id|identifier)|aadhaar|aadhar|pan (?:card|number)|"
    r"passport|bank account|credit card|\bcvv\b|\botp\b|"
    r"sexual orientation|gender identity|ethnicity|disabilit|veteran|religio|consent|legal declaration|terms and conditions",
    re.I,
)


def permitted(question, answer=""):
    if SENSITIVE.search(question) or re.search(
        r"-----BEGIN .*PRIVATE KEY-----|\b(?:password|verification code|one.time code|otp|api[_ -]?key|access[_ -]?token)\s*(?:[:=]|is\b)",
        answer,
        re.I,
    ):
        raise ProfileConflictError("sensitive_answer_not_retained")


def key_for(
    profile_id,
    question,
    job_id=None,
    packet_id=None,
    company_name=None,
    job_description=None,
):
    identity = f"{profile_id}|{job_id}|{packet_id}|{company_name}|{job_description}|{question.strip().casefold()}"
    return PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]


class MissingInputCreate(GenerateRequest):
    packet_id: UUID | None = None
    missing_fact: str = Field(min_length=1, max_length=2000)
    reason: str = Field(
        default="No approved evidence supports an answer", min_length=1, max_length=2000
    )
    required_input_type: Literal[
        "text", "number", "choice", "evidence", "profile_edit"
    ] = "evidence"


class MissingInputEdit(Contract):
    expected_version: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=10000)
    evidence_note: str = Field(default="", max_length=2000)


class MissingInputApprove(Contract):
    expected_version: int = Field(ge=1)
    expected_profile_version: int = Field(ge=1)
    factual_confirmation: StrictBool

    @model_validator(mode="after")
    def confirmed(self):
        if not self.factual_confirmation:
            raise ValueError("Explicit factual confirmation required")
        return self


class MissingInputService:
    def __init__(self, session):
        self.session = session
        self.repo = CandidateKnowledgeRepository(session)

    async def stamp(self, request):
        from backend.app.services.application_answer_service import (
            ApplicationAnswerService,
        )
        from backend.app.services.applications.resume_selector import digest

        return digest(
            {
                "sources": await ApplicationAnswerService(
                    self.session
                )._generation_stamp(request),
                "company_name": request.company_name,
                "job_description": request.job_description,
            }
        )

    async def ensure(
        self, request, result, *, packet_id=None, reason=None, input_type="evidence"
    ):
        if SENSITIVE.search(request.question):
            return None
        profile = await self.repo.profile()
        if packet_id:
            packet = await self.session.get(ApplicationPacket, packet_id)
            if (
                not packet
                or packet.candidate_profile_id != profile.id
                or packet.job_id != request.job_id
            ):
                raise ProfileConflictError("missing_input_packet_context_mismatch")
        # Validate job ownership/context and collect a private digest, never raw source material.
        stamp = await self.stamp(request)
        key = key_for(
            profile.id,
            request.question,
            request.job_id,
            packet_id,
            request.company_name,
            request.job_description,
        )
        value = {
            "id": key.removeprefix(PREFIX),
            "candidate_profile_id": str(profile.id),
            "question": request.question,
            "question_category": result.question_type,
            "job_id": str(request.job_id) if request.job_id else None,
            "company_name": request.company_name,
            "job_description": request.job_description,
            "packet_id": str(packet_id) if packet_id else None,
            "missing_information": result.missing_information,
            "reason": reason
            or "Answer generation stopped because approved evidence is missing",
            "required_input_type": input_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "needs_input",
            "version": 1,
            "profile_version": profile.version,
            "context_digest": stamp,
            "answer": None,
            "evidence_note": "",
            "draft_id": None,
        }
        await self.session.execute(
            insert_for(self.session)(OwnerPreference)
            .values(key=key, value=value)
            .on_conflict_do_nothing()
        )
        await self.session.flush()
        return value["id"]

    async def row(self, request_id, lock=False):
        if not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise LookupError("Missing-answer request not found")
        profile = await self.repo.profile()
        row = await self.session.get(
            OwnerPreference,
            PREFIX + request_id,
            with_for_update=lock,
            populate_existing=True,
        )
        if not row or row.value.get("candidate_profile_id") != str(profile.id):
            raise LookupError("Missing-answer request not found")
        return row, profile

    def request(self, value):
        return GenerateRequest(
            question=value["question"],
            job_id=value["job_id"],
            company_name=value.get("company_name"),
            job_description=value.get("job_description"),
        )

    async def read(self, request_id):
        row, _ = await self.row(request_id)
        value = dict(row.value)
        value["stale"] = value["context_digest"] != await self.stamp(
            self.request(value)
        )
        value["effective_status"] = (
            "review_required"
            if value["stale"] and value["status"] == "approved"
            else value["status"]
        )
        value["href"] = f"/api/v1/application-answers/missing/{request_id}"
        return value

    async def list(self, offset=0, limit=25):
        profile = await self.repo.profile()
        rows = (
            await self.session.scalars(
                select(OwnerPreference)
                .where(
                    OwnerPreference.key.startswith(PREFIX),
                    cast(
                        OwnerPreference.value["candidate_profile_id"].as_string(),
                        String,
                    )
                    == str(profile.id),
                )
                .order_by(OwnerPreference.created_at.desc(), OwnerPreference.key)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [await self.read(row.value["id"]) for row in rows]

    async def replace(self, row, old, new, operation):
        # JSON compare-and-swap protects SQLite fixtures as well as PostgreSQL row locks.
        changed = await self.session.execute(
            update(OwnerPreference)
            .where(
                OwnerPreference.key == row.key,
                OwnerPreference.value["version"].as_integer() == old["version"],
            )
            .values(value=new)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise ProfileConflictError("missing_input_version_conflict")
        self.session.add(
            OwnerPreference(
                key="input_rev:" + uuid4().hex,
                value={
                    "request_id": old["id"],
                    "candidate_profile_id": old["candidate_profile_id"],
                    "operation": operation,
                    "version": new["version"],
                    "previous": old,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        await self.session.commit()
        return await self.read(old["id"])

    async def edit(self, request_id, data):
        row, profile = await self.row(request_id, lock=True)
        old = dict(row.value)
        if old["version"] != data.expected_version:
            raise ProfileConflictError("missing_input_version_conflict")
        permitted(old["question"], data.answer + " " + data.evidence_note)
        new = {
            **old,
            "answer": data.answer,
            "evidence_note": data.evidence_note,
            "status": "draft",
            "version": old["version"] + 1,
            "profile_version": profile.version,
            "context_digest": await self.stamp(self.request(old)),
        }
        # Editing an approved answer invalidates its prior reusable draft as well.
        if old.get("draft_id"):
            draft = await self.session.get(
                ApplicationAnswerDraft, UUID(old["draft_id"])
            )
            if draft:
                draft.review_status = "discarded"
        new["draft_id"] = None
        return await self.replace(row, old, new, "edited")

    async def approve(self, request_id, data):
        row, profile = await self.row(request_id, lock=True)
        old = dict(row.value)
        if (
            old["version"] != data.expected_version
            or profile.version != data.expected_profile_version
        ):
            raise ProfileConflictError("missing_input_version_conflict")
        if (
            old["status"] != "draft"
            or not old.get("answer")
            or not old.get("evidence_note")
        ):
            raise ProfileConflictError("factual_answer_and_evidence_note_required")
        if old["context_digest"] != await self.stamp(self.request(old)):
            raise ProfileConflictError(
                "missing_input_context_changed_edit_before_approval"
            )
        permitted(old["question"], old["answer"])
        draft = ApplicationAnswerDraft(
            candidate_profile_id=profile.id,
            job_id=UUID(old["job_id"]) if old["job_id"] else None,
            question=old["question"],
            answer=old["answer"],
            question_category=old["question_category"],
            writing_style="professional",
            evidence_references=[],
            candidate_profile_version=profile.version,
            review_status="reviewed",
            provider=None,
            model=None,
        )
        self.session.add(draft)
        await self.session.flush()
        new = {
            **old,
            "ever_approved": True,
            "status": "approved",
            "version": old["version"] + 1,
            "draft_id": str(draft.id),
        }
        return await self.replace(row, old, new, "approved_exact_context")

    async def history(self, request_id, offset=0, limit=25):
        await self.row(request_id)
        rows = (
            await self.session.scalars(
                select(OwnerPreference)
                .where(
                    OwnerPreference.key.startswith("input_rev:"),
                    OwnerPreference.value["request_id"].as_string() == request_id,
                )
                .order_by(OwnerPreference.created_at.desc(), OwnerPreference.key)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [row.value for row in rows]

    async def approved(self, request):
        profile = await self.repo.profile()
        key = key_for(
            profile.id,
            request.question,
            request.job_id,
            company_name=request.company_name,
            job_description=request.job_description,
        )
        row = await self.session.get(OwnerPreference, key, populate_existing=True)
        if not row or row.value.get("status") != "approved":
            return None
        value = await self.read(row.value["id"])
        if value["stale"]:
            return None
        return value


async def approved_input_revisions(session, profile_id, job_id):
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(
                OwnerPreference.key.startswith(PREFIX),
                OwnerPreference.value["candidate_profile_id"].as_string()
                == str(profile_id),
                OwnerPreference.value["ever_approved"].as_boolean().is_(True),
            )
            .order_by(OwnerPreference.key)
        )
    ).all()
    return [
        [r.key, r.value["version"], r.value["status"], r.value["context_digest"]]
        for r in rows
        if r.value.get("job_id") in {None, str(job_id)}
    ]
