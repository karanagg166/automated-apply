import pytest
from sqlalchemy import select
from backend.app.models.company import Company
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
from backend.app.services.job_ingestion import JobIngestionService


@pytest.mark.asyncio
async def test_observed_startup_intelligence_is_linked_to_company(db_session):
    item = ApifyJobAdapter().normalize_portal_record(
        "work_at_a_startup",
        {
            "id": "42",
            "url": "https://www.workatastartup.com/jobs/42",
            "title": "Founding Engineer",
            "company": {
                "name": "Example Startup",
                "domain": "example.com",
                "batch": "W25",
                "stage": "seed",
                "technologies": ["Python"],
                "profile_url": "https://www.workatastartup.com/companies/example",
                "founder_urls": ["https://linkedin.com/in/example"],
            },
            "equity": "0.1%-0.5%",
        },
    )
    result = await JobIngestionService(db_session).ingest_jobs([item])
    company = await db_session.scalar(select(Company))
    intelligence = company.metadata_["startup_discovery"]
    assert (
        result.inserted_count == 1
        and intelligence["batch"] == "W25"
        and intelligence["source"] == "work_at_a_startup"
    )
    assert intelligence["observed_at"] and intelligence["source_url"]
    assert item.equity == "0.1%-0.5%" and not item.is_confirmed_current


def test_title_does_not_fabricate_yc_membership_or_founders():
    item = ApifyJobAdapter().normalize_portal_record(
        "wellfound",
        {
            "url": "https://wellfound.com/jobs/42",
            "title": "Engineer (YC W25)",
            "companyName": "Example",
        },
    )
    assert item.company_intelligence == {}


def test_invalid_stage_is_rejected_per_record():
    with pytest.raises(ValueError):
        ApifyJobAdapter().normalize_portal_record(
            "wellfound",
            {
                "url": "https://wellfound.com/jobs/42",
                "title": "Engineer",
                "company": {"name": "Example", "stage": {"unstructured": "invalid"}},
            },
        )
