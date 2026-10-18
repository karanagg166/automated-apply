"""Application Assistance Service providing matching, tailored materials, and human-in-the-loop tracking."""

import uuid
from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import logger
from backend.app.models.job import Job
from backend.app.repositories.job import JobRepository


class CandidateProfile(BaseModel):
    """Verified user credentials, experience, and job search preferences."""

    full_name: str
    email: str
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    verified_skills: list[str] = Field(default_factory=list)
    verified_experience_years: float | None = Field(default=None, ge=0)
    verified_roles: list[dict[str, str]] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: str | None = None
    target_titles: list[str] = Field(default_factory=list)
    notice_period_days: int | None = Field(default=None, ge=0)
    work_authorization: str | None = None


class JobMatchResult(BaseModel):
    """Explainable multi-factor match result between candidate and job vacancy."""

    job_id: str
    match_score: float = Field(ge=0.0, le=100.0)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    location_match: bool = False
    title_match: bool = False
    explanation: str


class ApplicationDraft(BaseModel):
    """Prepared application package for human review and manual approval."""

    job_id: str
    company_name: str
    job_title: str
    direct_application_url: str
    tailored_cover_letter: str
    highlighted_skills: list[str]
    prepared_answers: dict[str, str]
    submission_allowed: bool
    policy_disclaimer: str


class ApplicationAssistant:
    """Service to score relevance, prepare factual application materials, and track application lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.job_repo = JobRepository(session)

    def calculate_match(self, job: Job, profile: CandidateProfile) -> JobMatchResult:
        """Calculate an explainable, multi-factor match score (0-100) based strictly on verified candidate data."""
        job_title_lower = job.title.lower()
        job_desc_lower = (job.description or "").lower()

        # 1. Title match (up to 30 points)
        title_points = 0.0
        title_match = False
        for target in profile.target_titles:
            t_low = target.lower()
            if t_low in job_title_lower:
                title_points = 30.0
                title_match = True
                break
            elif any(w in job_title_lower for w in t_low.split() if len(w) > 3):
                title_points = max(title_points, 15.0)

        # 2. Skill match (up to 40 points)
        matched_skills: list[str] = []
        missing_skills: list[str] = []

        # Compare against required skills or detect from description
        skills_to_check = job.skills_required or []
        profile_skills_lower = {s.lower(): s for s in profile.verified_skills}

        if skills_to_check:
            for skill in skills_to_check:
                if skill.lower() in profile_skills_lower:
                    matched_skills.append(profile_skills_lower[skill.lower()])
                else:
                    missing_skills.append(skill)
            skill_ratio = len(matched_skills) / max(len(skills_to_check), 1)
            skill_points = skill_ratio * 40.0
        else:
            # Detect from description
            for s_low, s_orig in profile_skills_lower.items():
                if s_low in job_desc_lower or s_low in job_title_lower:
                    matched_skills.append(s_orig)
            skill_points = min(len(matched_skills) * 8.0, 40.0)

        # 3. Location & Remote match (up to 20 points)
        location_points = 0.0
        location_match = False

        if profile.remote_preference == "remote_only":
            if job.is_remote:
                location_points = 20.0
                location_match = True
        elif profile.remote_preference in ("hybrid", "any", "onsite"):
            if job.is_remote and profile.remote_preference != "onsite":
                location_points = 20.0
                location_match = True
            elif not job.is_remote and job.location:
                for pref in profile.preferred_locations:
                    if pref.lower() in job.location.lower():
                        location_points = 20.0
                        location_match = True
                        break

        # 4. Seniority / Experience baseline (up to 10 points)
        exp_points = 0.0 if profile.verified_experience_years is None else 10.0
        if job.experience_level and profile.verified_experience_years is not None:
            exp_low = job.experience_level.lower()
            if "senior" in exp_low and profile.verified_experience_years < 3.0:
                exp_points = 2.0
            elif "junior" in exp_low and profile.verified_experience_years > 6.0:
                exp_points = 5.0

        total_score = min(max(title_points + skill_points + location_points + exp_points, 0.0), 100.0)

        explanation = (
            f"Title relevance: {title_points:.1f}/30. "
            f"Skills matched ({len(matched_skills)}): {', '.join(matched_skills[:5]) if matched_skills else 'None'}. "
            f"Location/Remote match: {'Yes' if location_match else 'No'} ({location_points:.1f}/20). "
            f"Seniority alignment: {exp_points:.1f}/10."
        )

        if profile.verified_experience_years is None:
            explanation += " Experience is unknown; no seniority points awarded."

        return JobMatchResult(
            job_id=str(job.id),
            match_score=round(total_score, 2),
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            location_match=location_match,
            title_match=title_match,
            explanation=explanation,
        )

    def generate_draft_application(
        self,
        job: Job,
        company_name: str,
        profile: CandidateProfile,
    ) -> ApplicationDraft:
        """Prepare human-in-the-loop application draft with zero fact fabrication."""
        # STRICT POLICY: LinkedIn cannot be automatically submitted
        is_linkedin = "linkedin" in (job.source_platform or "").lower() or "linkedin.com" in job.job_url.lower()

        submission_allowed = not is_linkedin
        policy_disclaimer = (
            "⚠️ STRICT POLICY NOTICE: LinkedIn automated application submission is strictly prohibited. "
            "You must review and submit this application directly in your web browser."
            if is_linkedin
            else "HUMAN APPROVAL REQUIRED: Review materials before final submission."
        )

        if not profile.full_name.strip() or not profile.email.strip():
            raise ValueError("Name and email are required to prepare an application")
        facts = []
        if profile.verified_experience_years is not None:
            facts.append(f"I have {profile.verified_experience_years:g} years of experience.")
        if profile.verified_skills:
            facts.append(f"My technical skills include {', '.join(profile.verified_skills[:5])}.")
        for role in profile.verified_roles[:2]:
            if role.get("company") and role.get("role"):
                sentence = f"At {role['company']}, I worked as {role['role']}."
                if role.get("highlight"):
                    sentence += f" {role['highlight']}"
                facts.append(sentence)
        cover_letter = (
            f"Dear Hiring Team at {company_name},\n\n"
            f"I am interested in the {job.title} role. "
            + " ".join(facts)
            + f"\n\nI would welcome the opportunity to discuss this position.\n\n"
              f"Sincerely,\n{profile.full_name}\n{profile.email}"
        )
        prepared_answers = {
            "Full Name": profile.full_name,
            "Email Address": profile.email,
        }
        optional_answers = {
            "Phone Number": profile.phone,
            "LinkedIn Profile": profile.linkedin_url,
            "GitHub / Code Portfolio": profile.github_url or profile.portfolio_url,
            "Total Years of Experience": f"{profile.verified_experience_years:g} years" if profile.verified_experience_years is not None else None,
            "Notice Period": f"{profile.notice_period_days} days" if profile.notice_period_days is not None else None,
            "Work Authorization": profile.work_authorization,
            "Remote Work Preference": profile.remote_preference,
        }
        prepared_answers.update({key: value for key, value in optional_answers.items() if value is not None})

        return ApplicationDraft(
            job_id=str(job.id),
            company_name=company_name,
            job_title=job.title,
            direct_application_url=job.job_url,
            tailored_cover_letter=cover_letter,
            highlighted_skills=[s for s in profile.verified_skills if s.lower() in (job.description or "").lower() or s in (job.skills_required or [])],
            prepared_answers=prepared_answers,
            submission_allowed=submission_allowed,
            policy_disclaimer=policy_disclaimer,
        )

    async def update_application_status(
        self,
        job_id: str,
        new_status: str,
        notes: str | None = None,
    ) -> Job:
        """Update job application status with human confirmation."""
        allowed_statuses = {"discovered", "reviewed", "shortlisted", "applied", "rejected", "archived"}
        if new_status not in allowed_statuses:
            raise ValueError(f"Invalid status '{new_status}'. Allowed: {allowed_statuses}")

        jid = uuid.UUID(job_id)
        job = await self.job_repo.get_by_id(jid)
        if not job:
            raise ValueError(f"Job with ID '{job_id}' not found")

        job.status = new_status
        if notes:
            existing_exp = job.match_explanation or ""
            job.match_explanation = f"{existing_exp} | Status update ({new_status}): {notes}".strip(" | ")

        await self.session.flush()
        logger.info(f"Updated job {job_id} status to '{new_status}'")
        return job
