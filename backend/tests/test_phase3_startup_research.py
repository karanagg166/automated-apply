"""Fictional startup evidence: country/industry/band accuracy and strong identity."""

import pytest
from pydantic import ValidationError

from backend.app.models.discovery import now
from backend.app.services.startup_discovery.evidence import ingest_company
from backend.app.services.startup_discovery.schemas import (
    CompanyObservation,
    StartupFilters,
)
from backend.app.services.startup_discovery.service import StartupDiscoveryService


def company(**values):
    return CompanyObservation(
        name="Fictional Tools",
        domain="fictional-tools.example",
        source="fixture",
        source_url="https://fictional-tools.example/about",
        permission_evidence_url="https://fictional-tools.example/permission",
        observed_at=now(),
        verification_status="source_reported",
        **values,
    )


async def test_country_industry_and_reported_range_never_become_exact_headcount(
    db_session,
):
    saved = await ingest_company(
        db_session,
        company(
            country="India",
            industry="Software and developer tools",
            team_size_band="11-50",
            location="Bengaluru",
            remote_policy="remote",
            technology_stack=["Python"],
        ),
    )
    await db_session.commit()
    service = StartupDiscoveryService(db_session)
    response = await service.search(
        StartupFilters(
            country="IN",
            industries=["software"],
            min_employees=11,
            max_employees=50,
            size_bands=["11-50"],
            use_profile=False,
        )
    )
    assert response["total"] == 1
    item = response["startups"][0]
    assert item["employee_count"] is None and item["team_size_band"] == "11-50"
    assert (
        item["hiring_status"] == "hiring_unknown" and item["technical_staff_count"] == 0
    )
    assert not (await service.search(StartupFilters(country="USA", use_profile=False)))[
        "startups"
    ]
    assert not (
        await service.search(StartupFilters(industries=["fintech"], use_profile=False))
    )["startups"]
    assert not (
        await service.search(
            StartupFilters(country="India", has_technical_staff=True, use_profile=False)
        )
    )["startups"]
    assert (await service.detail(saved.id))["team_size_evidence"][0]["observed_at"]


async def test_same_display_name_with_distinct_source_identity_is_not_merged(
    db_session,
):
    first = await ingest_company(
        db_session,
        CompanyObservation(
            name="Namesake",
            source="fixture",
            source_company_id="one",
            source_url="https://first.example/about",
            permission_evidence_url="https://first.example/permission",
            observed_at=now(),
        ),
    )
    second = await ingest_company(
        db_session,
        CompanyObservation(
            name="Namesake",
            source="fixture",
            source_company_id="two",
            source_url="https://second.example/about",
            permission_evidence_url="https://second.example/permission",
            observed_at=now(),
        ),
    )
    assert first.id != second.id


async def test_optional_two_to_ten_band_and_exact_count_conflicts_remain_explicit(
    db_session,
):
    small = await ingest_company(
        db_session, company(country="India", team_size_band="2-10")
    )
    await db_session.commit()
    service = StartupDiscoveryService(db_session)
    response = await service.search(
        StartupFilters(
            size_bands=["2-10"], min_employees=2, max_employees=10, use_profile=False
        )
    )
    assert response["total"] == 1 and response["startups"][0]["employee_count"] is None
    # A fresh, distinct authoritative source contradicts the small-company claim.
    observation = company(country="India", employee_count=40)
    observation.source = "second_fixture"
    await ingest_company(db_session, observation)
    item = await service.detail(small.id)
    assert (
        item["employee_count"] is None
        and item["team_size_evidence_status"] == "conflicting"
    )
    with pytest.raises(ValidationError):
        StartupFilters(min_employees=50, max_employees=10)


async def test_generic_source_url_cannot_merge_different_employers(db_session):
    first = CompanyObservation(
        name="First Employer",
        source="fixture",
        source_url="https://directory.example/companies",
        permission_evidence_url="https://directory.example/permission",
        observed_at=now(),
    )
    await ingest_company(db_session, first)
    with pytest.raises(ValueError, match="does not establish"):
        await ingest_company(
            db_session, first.model_copy(update={"name": "Other Employer"})
        )
