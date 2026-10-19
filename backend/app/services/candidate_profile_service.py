"""Deterministic access to user-verified facts. No inference or provider access."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.operations.onboarding import reject_placeholders
from backend.app.repositories.candidate_profile import (
    CandidateProfileRepository,
    ProfileNotFoundError,
)
from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileRead,
    CandidateProfileUpdate,
)
from backend.app.services.application_assistant import (
    CandidateProfile as AssistantProfile,
)


class CandidateProfileService:
    def __init__(self, session: AsyncSession):
        self.repository = CandidateProfileRepository(session)

    @staticmethod
    def validate_live_input(data):
        if get_settings().ENVIRONMENT in {"staging", "production"}:
            reject_placeholders(data)

    async def get_profile(self) -> CandidateProfileRead:
        profile = await self.repository.get_primary_profile()
        if profile is None:
            raise ProfileNotFoundError("No candidate profile saved")
        return CandidateProfileRead.model_validate(profile)

    async def create_profile(self, data: CandidateProfileCreate) -> CandidateProfileRead:
        self.validate_live_input(data)
        return CandidateProfileRead.model_validate(await self.repository.create_primary_profile(data))

    async def update_profile(self, data: CandidateProfileUpdate, expected_version: int) -> CandidateProfileRead:
        self.validate_live_input(data)
        return CandidateProfileRead.model_validate(await self.repository.update_primary_profile(data, expected_version))

    async def upsert_profile(self, data: CandidateProfileCreate, expected_version: int | None = None):
        self.validate_live_input(data)
        profile, created = await self.repository.upsert_primary_profile(data, expected_version)
        return CandidateProfileRead.model_validate(profile), created

    async def get_verified_career_information(self) -> dict:
        profile = await self.get_profile()
        return profile.model_dump(mode="json", include={
            "verified_skills", "verified_experience_years", "verified_roles",
            "education", "projects", "certifications", "summary",
        })

    async def to_application_profile(self) -> AssistantProfile:
        profile = await self.get_profile()
        preferences = profile.preferences
        # The legacy assistant uses remote_only for the remote preference.
        remote = "remote_only" if preferences.remote_preference == "remote" else preferences.remote_preference
        return AssistantProfile(
            full_name=profile.full_name, email=str(profile.email), phone=profile.phone,
            linkedin_url=str(profile.linkedin_url) if profile.linkedin_url else None,
            github_url=str(profile.github_url) if profile.github_url else None,
            portfolio_url=str(profile.portfolio_url) if profile.portfolio_url else None,
            verified_skills=profile.verified_skills,
            verified_experience_years=profile.verified_experience_years,
            verified_roles=[role.model_dump(mode="json", exclude_none=True) for role in profile.verified_roles],
            preferred_locations=preferences.preferred_locations,
            remote_preference=remote, target_titles=preferences.target_titles,
            notice_period_days=preferences.notice_period_days,
            work_authorization=preferences.work_authorization,
        )
