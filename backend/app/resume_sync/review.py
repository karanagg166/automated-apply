"""Owner-reviewed profile/resource activation in one transaction."""

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update

from backend.app.dashboard.models import PrivateResume
from backend.app.models.application_answer import (
    ApplicationAnswerDraft,
    CandidateEvidence,
    CandidateResource,
)
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.repositories.candidate_profile import CandidateProfileRepository
from backend.app.resume_sync.facts import differences
from backend.app.resume_sync.models import DriveResumeVersion, ResumeProfileReview
from backend.app.resume_sync.schemas import ResumeReviewRead
from backend.app.resume_sync.service import read_review
from backend.app.resume_sync.store import (
    check_generation,
    lock_source,
    require_cipher,
    status,
    version_read,
)
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.services.discovery_budget import insert_for


async def get_review(session, version_id):
    version = await session.get(DriveResumeVersion, version_id)
    review = await session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == version_id))
    if not version or not review:
        raise HTTPException(404, "Resume version or review not found")
    return version, review


async def review_changes(session, settings, version_id):
    from backend.app.resume_sync.models import ResumeDriveSource

    source = await session.get(ResumeDriveSource, "primary")
    version, review = await get_review(session, version_id)
    payload = read_review(review, require_cipher())
    profile = await CandidateProfileRepository(session).get_primary_profile()
    current = CandidateProfileCreate.model_validate(profile) if profile else None
    proposed = current.model_dump(mode="json") if current else dict(payload["facts"]["suggestions"])
    # Keep every human-confirmed skill, even when omitted from the latest PDF.
    proposed["verified_skills"] = list(dict.fromkeys(proposed.get("verified_skills", []) + payload["facts"]["suggestions"]["verified_skills"]))
    try:
        proposed = CandidateProfileCreate.model_validate(proposed)
    except ValidationError:
        proposed = None
    packets = answers = 0
    fact_differences = differences(payload["previous_facts"], payload["facts"], current.verified_skills if current else [], current.model_dump(mode="json") if current else None)
    if profile:
        packets = await session.scalar(select(func.count()).select_from(ApplicationPacket).where(ApplicationPacket.candidate_profile_id == profile.id))
        answers = await session.scalar(select(func.count()).select_from(ApplicationAnswerDraft).where(ApplicationAnswerDraft.candidate_profile_id == profile.id))
        known_evidence = (await session.scalars(select(CandidateEvidence).where(
            CandidateEvidence.candidate_profile_id == profile.id, CandidateEvidence.user_confirmed.is_(True),
        ).order_by(CandidateEvidence.updated_at.desc()).limit(100))).all()
        categories = {"project": "projects", "experience": "work_experience", "achievement": "achievements"}
        for item in known_evidence:
            category = categories.get(item.evidence_type, "other_claims")
            next(diff for diff in fact_differences if diff["category"] == category)["current_verified"].append(f"{item.title}: {item.content[:1000]}")
    return ResumeReviewRead(
        version=await version_read(session, version), expected_generation=source.generation,
        expected_profile_version=profile.version if profile else None,
        current_profile=current, proposed_profile=proposed,
        suggested_identity=payload["facts"]["suggestions"],
        differences=fact_differences,
        text=payload["facts"]["text"], stale_packet_count=packets, stale_answer_count=answers,
        warnings=[
            "Section differences are verbatim unverified evidence, not inferred structured facts. Review the source PDF and every date, employer, institution, project, link and claim.",
            "Omitted skills do not remove human-confirmed skills. Explicit removal requires a separate confirmation.",
            "Existing facts and evidence remain unchanged until approval. The editable profile is the exact set of facts you approve.",
            "No PDF or source text was sent to an AI service. Scanned PDFs require manual fact entry.",
            "Approval flags prior answers and packets as stale; approved packet contents and outreach history remain intact.",
        ],
    )


async def approve_version(session, settings, version_id, data):
    source = await lock_source(session, settings)
    check_generation(source, data.expected_generation)
    if source.latest_version_id != version_id:
        raise HTTPException(409, "Only the latest version of the current source can be activated; reload the review")
    version, review = await get_review(session, version_id)
    profile = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary").with_for_update().execution_options(populate_existing=True))
    if source.active_version_id == version_id and review.status == "approved":
        return await status(session, settings)  # Lost-response retries are harmless.
    if (profile.version if profile else None) != data.expected_profile_version:
        raise HTTPException(409, "Candidate profile changed; reload and review the latest facts before approval")
    if profile and not data.allow_skill_removals:
        approved = {skill.casefold() for skill in data.profile.verified_skills}
        if any(skill.casefold() not in approved for skill in profile.verified_skills):
            raise HTTPException(422, "Explicitly confirm removal of human-confirmed skills, or preserve them")
    CandidateProfileService.validate_live_input(data.profile)
    encryption = require_cipher()
    payload = read_review(review, encryption)
    values = {**data.profile.model_dump(mode="json"), "active_resume_version_id": version.id}
    if profile:
        expected = profile.version
        result = await session.execute(update(CandidateProfile).where(
            CandidateProfile.id == profile.id, CandidateProfile.version == expected,
        ).values(**values, version=expected + 1, updated_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise HTTPException(409, "Candidate profile changed; reload the review")
        await session.refresh(profile)
    else:
        profile = (await session.execute(insert_for(session)(CandidateProfile).values(**values).on_conflict_do_nothing(index_elements=["singleton_key"]).returning(CandidateProfile))).scalar_one_or_none()
        if profile is None:
            raise HTTPException(409, "A candidate profile was created concurrently; reload the review")
    # The relationship changes even when facts do not, so PostgreSQL's existing version
    # trigger advances the profile exactly once. No packet snapshots are edited.
    await session.execute(update(CandidateResource).where(
        CandidateResource.candidate_profile_id == profile.id,
        CandidateResource.resource_type == "resume", CandidateResource.is_primary.is_(True),
    ).values(is_primary=False))
    private = await session.get(PrivateResume, version.private_resume_id)
    resource = await session.get(CandidateResource, private.resource_id) if private.resource_id else None
    if resource is None:
        resource = CandidateResource(
            candidate_profile_id=profile.id, resource_type="resume", label=version.file_name,
            url="private-resume:" + str(private.id), source_type="private_upload",
            user_confirmed=True, is_primary=True,
        )
        session.add(resource)
        await session.flush()
    else:
        resource.is_primary, resource.user_confirmed = True, True
    private.confirmed, private.resource_id = True, resource.id
    for evidence in data.evidence:
        values = evidence.model_dump(mode="json")
        values.update(source_url=version.canonical_url, source_description=f"Owner-reviewed Drive resume {version.sha256[:12]}")
        session.add(CandidateEvidence(candidate_profile_id=profile.id, **values))
    payload["approved_profile"] = data.profile.model_dump(mode="json")
    payload["approved_evidence"] = [item.model_dump(mode="json") for item in data.evidence]
    review.review_ciphertext = encryption.encrypt(json.dumps(payload).encode())
    review.status, review.approved_at, review.approved_profile_version = "approved", datetime.now(timezone.utc), profile.version
    source.active_version_id, source.status = version.id, "approved"
    await session.flush()
    return await status(session, settings)
