"""Milestone 2 rules sandbox: run a pasted listing through the deterministic filter pipeline and explain
every stage. Pure (no network: a URL is only used to infer the portal and job id, never fetched)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from backend.app.browser_v2.adapters.shared.external_handoff import ats_handoff_target
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    ApplicantCount,
    CandidatePreferences,
    Decision,
    FilterResult,
    PortalRules,
    evaluate_experience,
    evaluate_job,
    evaluate_pipeline,
    evaluate_preferences,
    paused,
    within_active_hours,
)
from backend.app.browser_v2.schemas.ops import (
    RuleCheckRead,
    RuleScoreRead,
    RulesExplainInput,
    RulesExplainRead,
)
from backend.app.browser_v2.service.scoring import score_listing, title_matches_target

PORTAL_HOSTS = (("naukri.com", "naukri"), ("instahyre.com", "instahyre"), ("internshala.com", "internshala"),
                ("wellfound.com", "wellfound"), ("workatastartup.com", "work_at_a_startup"),
                ("ashbyhq.com", "ashby"), ("smartrecruiters.com", "smartrecruiters"))


def infer_platform(data: RulesExplainInput) -> str:
    if data.platform:
        return data.platform
    url = (data.url or "").strip()
    if url:
        handoff = ats_handoff_target(url)
        if handoff is not None:
            return handoff.platform
        lowered = url.lower()
        for host, platform in PORTAL_HOSTS:
            if host in lowered:
                return platform
    return "greenhouse"


def applicant_count(value: int | None) -> ApplicantCount:
    return UNKNOWN_APPLICANTS if value is None else ApplicantCount(value, value, False, str(value))


def _check(name: str, result: FilterResult, *, ok_detail: str | None = None) -> RuleCheckRead:
    detail = "; ".join(result.reasons) or ok_detail
    return RuleCheckRead(name=name, passed=result.decision is Decision.PASS, detail=detail)


def explain_listing(data: RulesExplainInput, rules: PortalRules, prefs: CandidatePreferences,
                    now: datetime | None = None) -> RulesExplainRead:
    now = now or datetime.now(UTC)
    applicants = applicant_count(data.applicants)
    portal = evaluate_job(age_days=data.posted_age_days, applicants=applicants, rules=rules)
    experience = evaluate_experience(data.experience_text, prefs)
    preference = evaluate_preferences(title=data.title, company=data.company, description=data.description,
                                      salary_text=data.salary_text, work_mode=data.work_mode, prefs=prefs,
                                      require_description=False)
    verdict = evaluate_pipeline(
        age_days=data.posted_age_days, applicants=applicants, rules=rules, prefs=prefs, title=data.title,
        company=data.company, description=data.description, salary_text=data.salary_text,
        work_mode=data.work_mode, require_description=False, experience_text=data.experience_text)
    title_ok = title_matches_target(data.title, prefs)
    checks = [
        RuleCheckRead(name="portal_enabled", passed=rules.enabled,
                      detail=None if rules.enabled else "portal_disabled"),
        RuleCheckRead(name="not_paused", passed=not paused(rules, now),
                      detail=f"paused_until {rules.paused_until}" if paused(rules, now) else None),
        RuleCheckRead(name="active_hours", passed=within_active_hours(rules, now),
                      detail=None if within_active_hours(rules, now) else "outside_active_hours (apply waits)"),
        _check("posting_age_and_applicants", portal),
        _check("experience", experience),
        _check("preferences", preference),
        RuleCheckRead(name="title_matches_target_role", passed=title_ok,
                      detail=None if title_ok else "no strong target-role title match (LLM gray zone may apply)"),
    ]
    listing = JobListing(platform=rules.platform, external_job_id="explain", url=data.url or "",
                         title=data.title, company=data.company, posted_age_days=data.posted_age_days)
    meta = score_listing(listing, prefs, now=now, passed=verdict.decision is Decision.PASS)
    stages = {"posting_age_and_applicants": portal, "experience": experience, "preferences": preference}
    breakdown: dict[str, float] = {name: 1.0 if result.decision is Decision.PASS else
                                   (0.5 if result.decision is Decision.REVIEW else 0.0)
                                   for name, result in stages.items()}
    breakdown["title_match"] = 1.0 if title_ok else 0.0
    total = round(sum(breakdown.values()) / len(breakdown), 3)
    return RulesExplainRead(
        platform=rules.platform, decision=verdict.decision.value, passed=verdict.decision is Decision.PASS,
        reasons=list(verdict.reasons), checks=checks, rules_revision=rules.revision,
        score=RuleScoreRead(total=total, breakdown=breakdown, priority=meta.priority,
                            priority_reason=meta.priority_reason))


def explain_payload(data: RulesExplainInput, rules: PortalRules, profile: dict[str, Any],
                    now: datetime | None = None) -> RulesExplainRead:
    prefs = CandidatePreferences.from_profile(profile)
    return explain_listing(data, replace(rules), prefs, now)
