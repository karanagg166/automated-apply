"""Completeness checks reuse profile/resource contracts; never infer personal facts."""

import re

from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app.models.application_answer import CandidateResource
from backend.app.operations.configuration import OperationRejected
from backend.app.repositories.candidate_profile import CandidateProfileRepository
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.services.applications.resume_selector import select_resume


class ProfileReadiness(BaseModel):
    status: str
    profile_version: int | None = None
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resume_selected: bool = False
    identity_independently_verified: bool = False


def reject_placeholders(data):
    text = data.model_dump_json() if hasattr(data, "model_dump_json") else str(data)
    if re.search(
        r"fictional|placeholder|YOUR_|example\.(?:com|org|net)|\.example\b|Alex Example|test@|\bTODO\b",
        text,
        re.I,
    ):
        raise OperationRejected("fictional_or_placeholder_profile_rejected")


def assess_profile(profile, resources=(), *, live=True):
    if profile is None:
        return ProfileReadiness(status="blocked", missing=["candidate_profile"])
    facts = CandidateProfileCreate.model_validate(profile)
    if live:
        reject_placeholders(facts)
        for resource in resources:
            reject_placeholders({"label": resource.label, "url": resource.url})
    missing = []
    for name in ("verified_skills", "projects"):
        if not getattr(facts, name):
            missing.append(name)
    if not facts.verified_roles and facts.verified_experience_years != 0:
        missing.append("work_history_or_explicit_zero_experience")
    if any(not p.contribution or not p.technologies for p in facts.projects):
        missing.append("project_contribution_and_technologies")
    if not facts.preferences.target_titles:
        missing.append("target_roles")
    if (
        not facts.preferences.preferred_locations
        and facts.preferences.remote_preference is None
    ):
        missing.append("location_or_remote_preference")
    for name, host in (("github_url", "github.com"), ("linkedin_url", "linkedin.com")):
        url = getattr(facts, name)
        if (
            url is None
            or url.host not in {host, "www." + host}
            or url.scheme != "https"
        ):
            missing.append(name)
    if not facts.portfolio_url and not facts.personal_website:
        missing.append("portfolio_or_personal_website")
    resume = select_resume(resources)
    if resume.selected is None:
        missing.append("confirmed_unique_primary_resume")
    return ProfileReadiness(
        status="blocked" if missing else "owner_confirmation_required",
        profile_version=getattr(profile, "version", None),
        missing=missing,
        resume_selected=resume.selected is not None,
        warnings=[
            "Profile facts and links require owner confirmation; no sites or resume bytes were fetched",
            "Salary, education and work authorization remain unknown unless explicitly supplied",
        ],
    )


async def profile_readiness(session, *, live=True):
    profile = await CandidateProfileRepository(session).get_primary_profile()
    resources = (
        list(
            (
                await session.scalars(
                    select(CandidateResource).where(
                        CandidateResource.candidate_profile_id == profile.id
                    )
                )
            ).all()
        )
        if profile
        else []
    )
    return assess_profile(profile, resources, live=live)
