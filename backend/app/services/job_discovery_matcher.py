"""Deterministic preference overlay on the existing factual ApplicationAssistant."""

from pydantic import BaseModel, Field
from backend.app.services.application_assistant import (
    ApplicationAssistant,
    CandidateProfile,
)


class DiscoveryMatch(BaseModel):
    match_score: float
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    explanation: str


class JobDiscoveryMatcher:
    def __init__(self, session):
        self.assistant = ApplicationAssistant(session)

    def match(self, job, profile, company=None):
        prefs = profile.preferences
        assistant_profile = CandidateProfile(
            full_name=profile.full_name,
            email=str(profile.email),
            verified_skills=profile.verified_skills,
            verified_experience_years=profile.verified_experience_years,
            target_titles=prefs.target_titles,
            preferred_locations=prefs.preferred_locations,
            remote_preference="remote_only"
            if prefs.remote_preference == "remote"
            else prefs.remote_preference,
        )
        base = self.assistant.calculate_match(job, assistant_profile)
        score, positive, negative, unknown, excluded = base.match_score, [], [], [], []
        title, description = job.title.casefold(), (job.description or "").casefold()
        company_name = (company.name if company else "").casefold()
        for value in prefs.excluded_companies:
            if company_name == value.casefold() or (
                company and company.domain == value.casefold()
            ):
                excluded.append("Excluded company: " + value)
        for value in prefs.excluded_titles:
            if value.casefold() in title:
                excluded.append("Excluded title: " + value)
        for value in prefs.excluded_keywords:
            if value.casefold() in title + " " + description + " " + company_name:
                excluded.append("Excluded keyword: " + value)
        if base.title_match:
            positive.append("Target role matches")
        elif prefs.target_titles:
            negative.append("Title differs from target roles")
        if base.matched_skills:
            positive.append("Verified skills align with listing evidence")
        if base.missing_skills:
            negative.append("Some required skills are not in the saved profile")
        if not job.skills_required:
            unknown.append("required_skills")
        if profile.verified_experience_years is None or not job.experience_level:
            unknown.append("experience_suitability")
            if (
                profile.verified_experience_years is not None
                and not job.experience_level
            ):
                score -= 10  # Baseline grants generic experience points; suitability needs both sides.
        elif (
            "senior" in job.experience_level.lower()
            and profile.verified_experience_years < 3
        ):
            negative.append("Seniority may exceed verified experience")
        remote = job.remote_type or "unknown"
        if remote == "unknown":
            unknown.append("remote_policy")
        if not job.location:
            unknown.append("location")
        # Replace baseline's binary remote/location component with explicit policy evidence.
        if base.location_match:
            score -= 20
        location_match = bool(
            job.location
            and any(
                x.casefold() in job.location.casefold()
                for x in prefs.preferred_locations
            )
        )
        policy = prefs.remote_preference
        compatible = (
            (policy == "remote" and remote == "remote")
            or (
                policy == "hybrid"
                and remote == "hybrid"
                and (location_match or not prefs.preferred_locations)
            )
            or (
                policy == "onsite"
                and remote == "onsite"
                and (location_match or not prefs.preferred_locations)
            )
            or (policy in (None, "any") and (location_match or remote == "remote"))
        )
        if compatible:
            score += 20
            positive.append("Location and remote policy fit preferences")
        elif policy and policy != "any" and remote != "unknown":
            negative.append("Remote policy differs from preference")
        if prefs.employment_types:
            if not job.employment_type:
                unknown.append("employment_type")
            elif job.employment_type in prefs.employment_types:
                score += 5
                positive.append("Employment type matches")
            else:
                score -= 5
                negative.append("Employment type differs")
        startup = (
            (company.metadata_ or {}).get("startup_discovery", {}) if company else {}
        )
        stage = startup.get("stage")
        if prefs.prioritize_startups:
            if startup.get("source") == "work_at_a_startup" or stage in {
                "pre_seed",
                "seed",
                "early",
                "startup",
            }:
                score += 10
                positive.append(
                    "Startup source or observed stage matches startup preference"
                )
            else:
                unknown.append("startup_status")
        if prefs.company_stages:
            if not stage:
                unknown.append("company_stage")
            elif stage.casefold() in {x.casefold() for x in prefs.company_stages}:
                score += 5
                positive.append("Observed company stage matches")
            else:
                negative.append("Observed company stage differs")
        if prefs.minimum_salary is not None:
            if (
                (job.salary_min is None and job.salary_max is None)
                or not prefs.salary_currency
                or not prefs.salary_period
                or job.salary_currency != prefs.salary_currency
                or job.salary_period != prefs.salary_period
            ):
                unknown.append("salary_comparison")
            elif (
                job.salary_max is not None
                and float(job.salary_max) < prefs.minimum_salary
            ):
                score -= 5
                negative.append("Published salary is below preference")
            elif (
                job.salary_min is not None
                and float(job.salary_min) >= prefs.minimum_salary
            ):
                score += 5
                positive.append("Published salary meets preference")
            else:
                unknown.append("salary_comparison")
        return DiscoveryMatch(
            match_score=0 if excluded else round(min(100, max(0, score)), 2),
            matched_skills=base.matched_skills,
            missing_skills=base.missing_skills,
            positive_factors=positive,
            negative_factors=negative,
            exclusion_reasons=excluded,
            unknown_fields=unknown,
            explanation=base.explanation,
        )
