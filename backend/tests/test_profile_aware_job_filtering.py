import uuid
import pytest
from backend.app.models.job import Job
from backend.app.models.company import Company
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher


def profile(**preferences):
    return CandidateProfileCreate(
        full_name="Example Person",
        email="example@example.com",
        verified_skills=["Python"],
        verified_experience_years=2,
        preferences={
            "target_titles": ["Engineer"],
            "preferred_locations": ["Bengaluru"],
            **preferences,
        },
    )


def listing(**kwargs):
    return Job(
        id=uuid.uuid4(),
        title="Python Engineer",
        job_url="https://example.com/job",
        source_platform="manual",
        is_remote=False,
        skills_required=["Python", "Go"],
        **kwargs,
    )


@pytest.mark.parametrize(
    "preferences",
    [
        {"excluded_companies": ["Acme"]},
        {"excluded_titles": ["Engineer"]},
        {"excluded_keywords": ["Python"]},
    ],
)
def test_hard_exclusions(preferences):
    result = JobDiscoveryMatcher(None).match(
        listing(), profile(**preferences), Company(name="Acme", metadata_={})
    )
    assert result.exclusion_reasons and result.match_score == 0


@pytest.mark.parametrize(
    "preference,policy,positive",
    [
        ("remote", "remote", True),
        ("remote", "onsite", False),
        ("hybrid", "hybrid", True),
        ("hybrid", "remote", False),
        ("onsite", "onsite", True),
    ],
)
def test_explicit_remote_policies(preference, policy, positive):
    result = JobDiscoveryMatcher(None).match(
        listing(remote_type=policy, location="Bengaluru"),
        profile(remote_preference=preference),
    )
    assert any("Location and remote" in x for x in result.positive_factors) is positive


def test_unknown_experience_salary_location_and_skills():
    result = JobDiscoveryMatcher(None).match(
        listing(remote_type="unknown"),
        profile(minimum_salary=100000, salary_currency="USD", salary_period="year"),
    )
    assert {
        "experience_suitability",
        "remote_policy",
        "location",
        "salary_comparison",
    }.issubset(result.unknown_fields)
    assert result.matched_skills == ["Python"] and result.missing_skills == ["Go"]
    assert not result.exclusion_reasons


@pytest.mark.parametrize(
    "currency,period", [("INR", "year"), ("USD", "month"), (None, None)]
)
def test_salary_units_must_match(currency, period):
    result = JobDiscoveryMatcher(None).match(
        listing(salary_min=100000, salary_currency=currency, salary_period=period),
        profile(minimum_salary=90000, salary_currency="USD", salary_period="year"),
    )
    assert "salary_comparison" in result.unknown_fields
    assert not any("salary meets" in x for x in result.positive_factors)


def test_startup_preference_needs_observed_source():
    matcher, candidate = JobDiscoveryMatcher(None), profile(prioritize_startups=True)
    regular = matcher.match(listing(), candidate, Company(name="Acme", metadata_={}))
    startup = matcher.match(
        listing(),
        candidate,
        Company(
            name="Acme",
            metadata_={
                "startup_discovery": {"source": "work_at_a_startup", "batch": "W25"}
            },
        ),
    )
    assert startup.match_score == regular.match_score + 10
    assert "startup_status" in regular.unknown_fields
