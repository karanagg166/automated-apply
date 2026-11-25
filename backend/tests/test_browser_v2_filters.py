"""Deterministic filter pipeline: portal hard filters, candidate preferences, cross-portal dedup."""

from datetime import UTC, datetime, time

import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    ApplicantPolicy,
    CandidatePreferences,
    Decision,
    PortalRules,
    dedup_key,
    evaluate_pipeline,
    evaluate_preferences,
    parse_applicants,
    parse_salary_lpa,
    within_active_hours,
)
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore

RULES = PortalRules(platform="naukri", enabled=True)
NO_PREFS = CandidatePreferences()


def pipeline(**overrides):
    values = {"age_days": 1, "applicants": parse_applicants("50 applicants"), "rules": RULES, "prefs": NO_PREFS,
                  "title": "Python Developer", "company": "Example Labs", "description": "python fastapi postgres"}
    values.update(overrides)
    return evaluate_pipeline(**values)


def test_age_over_max_job_age_days_is_rejected():
    result = pipeline(age_days=8)
    assert result.decision is Decision.FILTERED and result.reasons == ("posting_too_old",)
    assert pipeline(age_days=7).passed


def test_live_configurable_age_limit_is_honoured():
    assert pipeline(age_days=10, rules=PortalRules(platform="naukri", enabled=True, max_job_age_days=14)).passed


def test_applicants_over_300_rejected_and_100_plus_passes_lower_bound():
    assert pipeline(applicants=parse_applicants("301 applicants")).reasons == ("applicants_over_limit",)
    hundred_plus = pipeline(applicants=parse_applicants("100+ applicants"))
    assert hundred_plus.passed and "applicants_lower_bound_used" in hundred_plus.reasons
    assert pipeline(applicants=parse_applicants("500+ applicants")).decision is Decision.FILTERED


def test_unknown_applicants_policies():
    skip = PortalRules(platform="naukri", enabled=True, unknown_applicants_policy=ApplicantPolicy.SKIP)
    review = PortalRules(platform="naukri", enabled=True,
                         unknown_applicants_policy=ApplicantPolicy.NEEDS_REVIEW)
    assert pipeline(applicants=parse_applicants("100+"), rules=skip).decision is Decision.FILTERED
    assert pipeline(applicants=UNKNOWN_APPLICANTS, rules=review).decision is Decision.REVIEW


@pytest.mark.parametrize("company", ["Acme Corp", "ACME Technologies Pvt. Ltd.", "acme"])
def test_company_blacklist_is_case_insensitive_and_suffix_tolerant(company):
    result = pipeline(company=company, prefs=CandidatePreferences(company_blacklist=("Acme",)))
    assert result.decision is Decision.FILTERED and result.reasons == ("company_blacklisted: Acme",)


def test_blacklist_does_not_match_inside_other_words():
    assert pipeline(company="Acmeville Systems", prefs=CandidatePreferences(company_blacklist=("Acme",))).passed


def test_excluded_keywords_in_title_or_description():
    prefs = CandidatePreferences(keywords_excluded=("php", "sales"))
    assert pipeline(title="PHP Developer", prefs=prefs).reasons == ("excluded_keyword_in_title: php",)
    assert pipeline(description="Inside sales quota", prefs=prefs).reasons == (
        "excluded_keyword_in_description: sales",)
    # Whole-word: "go" must not match "google".
    assert pipeline(description="google cloud", prefs=CandidatePreferences(keywords_excluded=("go",))).passed


def test_required_keywords_any_vs_all_and_tech_stack():
    prefs = CandidatePreferences(keywords_required=("python", "django"))
    assert pipeline(prefs=prefs).passed  # "any" (default): python present
    strict = CandidatePreferences(keywords_required=("python", "django"), skill_match_mode="all")
    assert pipeline(prefs=strict).reasons == ("required_keywords_missing: django",)
    stack = CandidatePreferences(tech_stack=("golang", "rust"))
    assert pipeline(prefs=stack).reasons[0].startswith("no_tech_stack_overlap")


def test_target_roles_are_seniority_and_synonym_tolerant():
    prefs = CandidatePreferences(target_roles=("Python Developer", "Backend Engineer"))
    assert pipeline(title="Senior Python Engineer", prefs=prefs).passed
    assert pipeline(title="Backend Developer II", prefs=prefs).passed
    assert pipeline(title="Data Analyst", prefs=prefs).reasons == ("title_not_in_target_roles: Data Analyst",)


def test_min_ctc_filters_only_disclosed_salaries_below_minimum():
    prefs = CandidatePreferences(min_ctc=10)
    assert pipeline(salary_text="6-8 Lacs PA", prefs=prefs).reasons == (
        "salary_below_min_ctc: max 8 LPA < 10 LPA",)
    assert pipeline(salary_text="8-12 Lacs PA", prefs=prefs).passed
    assert pipeline(salary_text="Not disclosed", prefs=prefs).passed


def test_card_prefilter_defers_keyword_checks_until_description():
    prefs = CandidatePreferences(keywords_required=("django",))
    card = evaluate_preferences(title="Python Developer", company="X", description=None, salary_text=None,
                                work_mode=None, prefs=prefs)
    assert card.passed


@pytest.mark.parametrize("text,expected", [
    ("8-12 Lacs PA", (8.0, 12.0)), ("₹ 8,00,000 - 12,00,000 P.A.", (8.0, 12.0)),
    ("10 LPA", (10.0, 10.0)), ("1-1.5 Cr", (100.0, 150.0)), ("Not disclosed", None),
    ("50,000 per month", None),
])
def test_parse_salary_lpa(text, expected):
    parsed = parse_salary_lpa(text)
    assert (None if parsed is None else (parsed.minimum_lpa, parsed.maximum_lpa)) == expected


def test_dedup_key_normalizes_company_suffixes_and_seniority_abbreviations():
    assert dedup_key("Acme Technologies Pvt. Ltd.", "Sr. Python Developer (Remote)") == \
        dedup_key("ACME", "Senior Python Developer") == "acme::senior python developer"
    assert dedup_key(None, "Developer") is None


def test_active_hours_in_portal_timezone_including_overnight_windows():
    rules = PortalRules(platform="naukri", active_hours_start=time(8), active_hours_end=time(23, 30))
    ist_noon = datetime(2026, 11, 26, 6, 30, tzinfo=UTC)  # 12:00 IST
    ist_midnight = datetime(2026, 11, 26, 18, 45, tzinfo=UTC)  # 00:15 IST
    assert within_active_hours(rules, ist_noon) and not within_active_hours(rules, ist_midnight)
    overnight = PortalRules(platform="naukri", active_hours_start=time(22), active_hours_end=time(2))
    assert within_active_hours(overnight, ist_midnight) and not within_active_hours(overnight, ist_noon)


class NoBrowser:
    def job(self):
        raise AssertionError("prefilter must not open the browser")


async def test_cross_portal_dedup_key_prevents_duplicate_apply():
    store = MemoryStore()
    applied = await store.upsert_discovered(JobListing(
        platform="instahyre", external_job_id="ih-1", url="https://example.com/ih-1",
        title="Python Developer", company="Acme Pvt Ltd"))
    store.records[("instahyre", "ih-1")].state = S.APPLIED
    service = BrowserService(NoBrowser(), store)  # type: ignore[arg-type]
    listing = JobListing(platform="naukri", external_job_id="261126000001",
                         url="https://www.naukri.com/x-261126000001", title="Python Developer",
                         company="ACME", posted_age_days=1, applicants=parse_applicants("20 applicants"))
    record, verdict = await service.prefilter(listing, RULES, NO_PREFS, record_filters=True)
    assert verdict is not None and verdict.reasons[0] == "duplicate_of: instahyre:ih-1 (APPLIED)"
    assert record.state is S.FILTERED_OUT and applied.dedup_key == record.dedup_key


async def test_prefilter_records_human_readable_reason():
    store = MemoryStore()
    service = BrowserService(NoBrowser(), store)  # type: ignore[arg-type]
    listing = JobListing(platform="naukri", external_job_id="1", url="https://www.naukri.com/x-1",
                         title="PHP Developer", company="Example", posted_age_days=12)
    record, verdict = await service.prefilter(listing, RULES, CandidatePreferences(keywords_excluded=("php",)),
                                              record_filters=True)
    assert verdict is not None and record.reason == "posting_too_old"
    listing2 = JobListing(platform="naukri", external_job_id="2", url="https://www.naukri.com/x-2",
                          title="PHP Developer", company="Example", posted_age_days=1)
    record2, _ = await service.prefilter(listing2, RULES, CandidatePreferences(keywords_excluded=("php",)),
                                         record_filters=True)
    assert record2.state is S.FILTERED_OUT and record2.reason == "excluded_keyword_in_title: php"
