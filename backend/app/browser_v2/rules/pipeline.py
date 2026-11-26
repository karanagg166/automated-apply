"""Deterministic job filter pipeline: portal hard filters, experience, then preferences."""

from __future__ import annotations

from backend.app.browser_v2.rules.decision import Decision, FilterResult
from backend.app.browser_v2.rules.parsing import ApplicantCount
from backend.app.browser_v2.rules.portal import ApplicantPolicy, PortalRules
from backend.app.browser_v2.rules.preferences import (
    CandidatePreferences,
    evaluate_experience,
    evaluate_preferences,
)


def evaluate_applicants(count: ApplicantCount, rules: PortalRules) -> FilterResult:
    if count.known and not count.is_lower_bound:
        if count.maximum is not None and count.maximum <= rules.max_applicants:
            return FilterResult(Decision.PASS)
        return FilterResult(Decision.FILTERED, ("applicants_over_limit",))
    policy = rules.unknown_applicants_policy
    if policy is ApplicantPolicy.ALLOW:
        return FilterResult(Decision.PASS, ("applicants_upper_bound_unknown_allowed",))
    if policy is ApplicantPolicy.SKIP:
        return FilterResult(Decision.FILTERED, ("applicants_upper_bound_unknown_skipped",))
    if policy is ApplicantPolicy.NEEDS_REVIEW:
        return FilterResult(Decision.REVIEW, ("applicants_upper_bound_unknown_review",))
    lower = count.minimum or 0
    if lower <= rules.max_applicants:
        return FilterResult(Decision.PASS, ("applicants_lower_bound_used",))
    return FilterResult(Decision.FILTERED, ("applicants_over_limit",))


def evaluate_job(*, age_days: int | None, applicants: ApplicantCount, rules: PortalRules,
                 age_is_lower_bound: bool = False) -> FilterResult:
    """Deterministic pre-apply filter. Unknown age is held for review unless the portal's
    live-editable `allow_unknown_posting_age` rule allows it (then it is noted in reasons)."""
    if not rules.enabled:
        return FilterResult(Decision.FILTERED, ("portal_disabled",))
    if age_days is None:
        if not rules.unknown_age_allowed:
            return FilterResult(Decision.REVIEW, ("posting_age_unknown",))
        applicant = evaluate_applicants(applicants, rules)
        return FilterResult(applicant.decision, ("posting_age_unknown_allowed",) + applicant.reasons)
    if age_days > rules.max_job_age_days or (age_is_lower_bound and age_days >= rules.max_job_age_days):
        return FilterResult(Decision.FILTERED, ("posting_too_old",))
    return evaluate_applicants(applicants, rules)


def evaluate_pipeline(*, age_days: int | None, applicants: ApplicantCount, rules: PortalRules,
                      prefs: CandidatePreferences, title: str | None, company: str | None,
                      description: str | None = None, salary_text: str | None = None,
                      work_mode: str | None = None, age_is_lower_bound: bool = False,
                      require_description: bool = True, experience_text: str | None = None) -> FilterResult:
    """Portal hard filters (age, applicants), required experience, then candidate preferences."""
    portal = evaluate_job(age_days=age_days, applicants=applicants, rules=rules,
                          age_is_lower_bound=age_is_lower_bound)
    if portal.decision is Decision.FILTERED:
        return portal
    experience = evaluate_experience(experience_text, prefs)
    if experience.decision is Decision.FILTERED:
        return experience
    preference = evaluate_preferences(title=title, company=company, description=description,
                                      salary_text=salary_text, work_mode=work_mode, prefs=prefs,
                                      require_description=require_description)
    if preference.decision is not Decision.PASS:
        return preference
    return FilterResult(portal.decision, portal.reasons + preference.reasons)
