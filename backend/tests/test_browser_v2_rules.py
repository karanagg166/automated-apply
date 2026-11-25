from datetime import date, time

import pytest

from backend.app.browser_v2.rules import (
    ApplicantPolicy,
    Decision,
    PortalRules,
    evaluate_applicants,
    evaluate_job,
    parse_applicants,
    parse_posted_age_days,
)

NAUKRI = PortalRules(platform="naukri", enabled=True)


@pytest.mark.parametrize("label,minimum,maximum,lower", [
    ("100+ applicants", 100, None, True),
    ("Applicants: 100+", 100, None, True),
    ("Applicants: 37", 37, 37, False),
    ("1,000+ Applicants", 1000, None, True),
    ("Less than 10 applicants", 0, 9, False),
    ("50 - 100 applicants", 50, 100, False),
])
def test_parse_applicants(label, minimum, maximum, lower):
    count = parse_applicants(label)
    assert (count.minimum, count.maximum, count.is_lower_bound) == (minimum, maximum, lower)


def test_unknown_applicants_have_no_bounds():
    for label in (None, "", "Be an early applicant"):
        count = parse_applicants(label)
        assert count.minimum is None and count.is_lower_bound


def test_hundred_plus_passes_with_allow_lower_bound_default():
    assert NAUKRI.unknown_applicants_policy is ApplicantPolicy.ALLOW_LOWER_BOUND
    assert NAUKRI.max_applicants == 300
    assert evaluate_applicants(parse_applicants("100+ applicants"), NAUKRI).passed


def test_lower_bound_over_limit_is_filtered():
    result = evaluate_applicants(parse_applicants("1000+ applicants"), NAUKRI)
    assert result.decision is Decision.FILTERED


def test_hundred_plus_is_skipped_under_skip_policy():
    rules = PortalRules(platform="naukri", enabled=True, unknown_applicants_policy=ApplicantPolicy.SKIP)
    result = evaluate_applicants(parse_applicants("100+ applicants"), rules)
    assert result.decision is Decision.FILTERED
    assert result.reasons == ("applicants_upper_bound_unknown_skipped",)


def test_needs_review_and_allow_policies():
    review = PortalRules(platform="naukri", enabled=True,
                         unknown_applicants_policy=ApplicantPolicy.NEEDS_REVIEW)
    allow = PortalRules(platform="naukri", enabled=True, unknown_applicants_policy=ApplicantPolicy.ALLOW)
    assert evaluate_applicants(parse_applicants("5000+"), review).decision is Decision.REVIEW
    assert evaluate_applicants(parse_applicants("5000+"), allow).passed


def test_exact_counts_ignore_unknown_policy():
    rules = PortalRules(platform="naukri", enabled=True, unknown_applicants_policy=ApplicantPolicy.SKIP)
    assert evaluate_applicants(parse_applicants("Applicants: 120"), rules).passed
    assert not evaluate_applicants(parse_applicants("Applicants: 301"), rules).passed


@pytest.mark.parametrize("text,days", [
    ("Just now", 0), ("Today", 0), ("Posted: 3 days ago", 3), ("1 day ago", 1),
    ("30+ days ago", 30), ("2 weeks ago", 14), ("Few hours ago", 0), ("2026-11-20", 6),
])
def test_parse_posted_age(text, days):
    assert parse_posted_age_days(text, today=date(2026, 11, 26)) == days


def test_evaluate_job_age_and_portal_rules():
    hundred_plus = parse_applicants("100+")
    assert evaluate_job(age_days=3, applicants=hundred_plus, rules=NAUKRI).passed
    assert evaluate_job(age_days=8, applicants=hundred_plus, rules=NAUKRI).reasons == ("posting_too_old",)
    assert evaluate_job(age_days=None, applicants=hundred_plus, rules=NAUKRI).decision is Decision.REVIEW
    disabled = PortalRules(platform="instahyre")
    assert evaluate_job(age_days=1, applicants=hundred_plus, rules=disabled).reasons == ("portal_disabled",)


def test_rules_from_database_row():
    rules = PortalRules.from_row({
        "platform": "naukri", "enabled": True, "max_applies_per_day": 50, "max_applies_per_hour": 10,
        "max_job_age_days": 7, "max_applicants": 300, "unknown_applicants_policy": "skip",
        "active_hours_start": time(8), "updated_at": "ignored", "portal_limit_hit_at": None,
    })
    assert rules.unknown_applicants_policy is ApplicantPolicy.SKIP and rules.max_applies_per_hour == 10
