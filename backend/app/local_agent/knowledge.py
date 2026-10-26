"""Read-only approved evidence boundary for future profile-context integration.

The independent profile-context module must be reviewed before its store adapter
is wired here. Current profile answers require the existing version confirmation.
"""
from typing import Protocol

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.profile_confirmation import confirmation_matches
from backend.app.models.candidate_profile import CandidateProfile


class ApprovedKnowledge(Protocol):
    async def answer(self, *, question: str, project_rank: int | None,
                     max_words: int, max_characters: int) -> dict: ...


async def reviewed_profile(session):
    profile = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    confirmation = await session.get(OwnerPreference, "phase1_profile_confirmation")
    return profile if confirmation_matches(profile, confirmation.value if confirmation else {}) else None


async def profile_reply(session):
    profile = await reviewed_profile(session)
    if not profile:
        return {"reply": "Your current profile still needs owner review in the dashboard. Imported facts are not approved experience.", "status": "profile_review_required"}
    # No identity, salary, phone, email or private resume text in Telegram output.
    skills = ", ".join(profile.verified_skills[:20]) or "Not specified"
    roles = ", ".join(profile.preferences.get("target_titles", [])[:10]) or "Not specified"
    return {"reply": f"Reviewed profile version {profile.version}. Skills: {skills}. Preferred roles: {roles}. Open Profile to review all personal facts.", "status": "profile_query", "profile_version": profile.version}


async def project_reply(intent, provider=None):
    if provider is None:
        return {"reply": "Approved project context is unavailable in this runtime. The independent project-context module awaits review and integration. No project details were invented. AI chat unavailable.", "status": "project_context_unavailable"}
    result = await provider.answer(question=intent.subject or "Describe my best project",
        project_rank=intent.project_rank, max_words=intent.max_words, max_characters=intent.max_characters)
    if not isinstance(result, dict) or not isinstance(result.get("text"), str) or not result.get("sources"):
        return {"reply": "No approved supporting project evidence is available. Review Profile first.", "status": "missing_approved_context"}
    text = " ".join(result["text"].split()[:intent.max_words])[:intent.max_characters]
    return {"reply": text, "status": "approved_context_draft", "sources": result["sources"]}
