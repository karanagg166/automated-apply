import pytest
from backend.app.core.job_urls import canonical_job_url
from backend.app.services.job_sources.normalization import salary_fields
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
from backend.tests.discovery_fakes import job


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/jobs/1",
        "https://127.0.0.1/jobs",
        "https://169.254.169.254/meta",
        "https://localhost/jobs",
        "https://a.internal/jobs",
        "https://user:secret@example.com/job",
        "javascript:alert(1)",
        "https://example.com:8080/job",
        "https://example.com/%00",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        job(original_url=url)


def test_canonical_links_keep_meaningful_ids():
    assert (
        canonical_job_url(
            "https://boards.greenhouse.io/acme/jobs/123/?utm_source=email&gh_src=x#section"
        )
        == "https://job-boards.greenhouse.io/acme/jobs/123"
    )
    assert (
        canonical_job_url("https://example.com/careers?gh_jid=123&ref=email")
        == "https://example.com/careers?gh_jid=123"
    )
    assert canonical_job_url(
        "https://news.ycombinator.com/item?id=12"
    ) != canonical_job_url("https://news.ycombinator.com/item?id=13")


def test_unknown_fields_are_not_facts():
    item = job(
        company_name=None, remote_type="unknown", is_remote=None, employment_type=None
    )
    assert (
        item.company_name is None
        and item.is_remote is None
        and item.remote_type == "unknown"
    )
    assert "company_unknown" in item.quality_flags
    assert item.employment_type is None


def test_ats_identity_requires_observed_per_job_url():
    item = job(
        application_url="https://boards.greenhouse.io/acme/jobs/123?utm_source=naukri"
    )
    assert item.canonical_url == "https://job-boards.greenhouse.io/acme/jobs/123"
    with pytest.raises(ValueError):
        job(canonical_url="https://different.com/job/123")
    assert (
        job(application_url="https://example.com/careers").canonical_url
        == "https://www.naukri.com/jobs/1"
    )


@pytest.mark.parametrize(
    "value", ["yesterday", "2099-01-01T00:00:00Z", "1980-01-01T00:00:00Z"]
)
def test_invalid_posted_dates(value):
    with pytest.raises(ValueError):
        job(date_posted=value)


def test_salary_units_and_ambiguous_currency():
    assert salary_fields("USD 120k - 150k per year") == {
        "salary_min": 120000,
        "salary_max": 150000,
        "salary_currency": "USD",
        "salary_period": "year",
    }
    assert salary_fields("$120k-$150k")["salary_currency"] is None
    assert salary_fields("EUR 50 per hour")["salary_period"] == "hour"
    assert salary_fields("0.5%-1% equity") == {}
    with pytest.raises(ValueError):
        job(salary_min=200, salary_max=100)


def test_no_fabricated_apify_records():
    with pytest.raises(ValueError):
        ApifyJobAdapter().normalize_portal_record(
            "naukri", {"title": "Python Engineer"}
        )
    with pytest.raises(ValueError):
        ApifyJobAdapter().normalize_portal_record(
            "naukri", {"url": "https://example.com/jobs/1"}
        )
