from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.models.discovery import now
from backend.app.models.job import Job
from backend.app.services.startup_discovery.intelligence import (
    company_size,
    hiring_intelligence,
)
from backend.app.services.startup_discovery.normalizer import size_allowed, size_band
from backend.app.services.startup_discovery.schemas import StartupFilters
from backend.tests.startup_fakes import observed


@pytest.mark.parametrize(
    "count,band",
    [
        (1, "1-10"),
        (10, "1-10"),
        (11, "11-50"),
        (50, "11-50"),
        (51, "51-200"),
        (200, "51-200"),
        (201, "201-500"),
        (500, "201-500"),
        (501, "500+"),
        (None, "unknown"),
    ],
)
def test_size_bands(count, band):
    assert size_band(count) == band


@pytest.mark.parametrize(
    "changes",
    [
        {"employee_count": 0},
        {"employee_count": True},
        {"employee_count": 18, "team_size_band": "51-200"},
        {"observed_at": now() + timedelta(days=1)},
        {"observed_at": now().replace(tzinfo=None)},
        {"hiring_statement": "not_currently_hiring"},
        {"domain": "127.0.0.1"},
        {"source_url": "https://localhost/team"},
    ],
)
def test_invalid_evidence(changes):
    with pytest.raises(ValueError):
        observed(**changes)


@pytest.mark.parametrize(
    "band,maximum,allowed",
    [
        ("11-50", 50, True),
        ("51-200", 50, False),
        ("51-200", 200, True),
        ("51-200", 100, False),
        ("500+", 1000, False),
        ("500+", None, True),
    ],
)
def test_band_filters_never_invent_a_count(band, maximum, allowed):
    assert (
        size_allowed(
            {"team_size_band": band, "employee_count": None},
            StartupFilters(max_employees=maximum),
        )
        is allowed
    )


@pytest.mark.parametrize("historical,age", [(True, 1), (False, 365)])
def test_historical_and_old_counts_unknown(historical, age):
    o = SimpleNamespace(
        attributes={
            "historical": historical,
            "team_size_band": "11-50",
            "employee_count": 20,
        },
        observed_at=now() - timedelta(days=age),
        verification_status="source_reported",
        source="fixture",
        source_url="https://fictional.example",
        id=uuid4(),
        identity_key="key",
    )
    assert company_size([o])["team_size_band"] == "unknown"


@pytest.mark.parametrize(
    "age,confirmed,meta,expected",
    [
        (1, True, {}, "hiring_confirmed"),
        (1, False, {}, "hiring_possible"),
        (90, True, {}, "hiring_unknown"),
        (1, True, {"is_expired": True}, "hiring_unknown"),
        (
            1,
            True,
            {"expires_at": (now() - timedelta(days=1)).isoformat()},
            "hiring_unknown",
        ),
    ],
)
def test_hiring_freshness_and_expiry(age, confirmed, meta, expected):
    j = Job(
        id=uuid4(),
        title="Backend Engineer",
        job_url="https://fictional.example/jobs/1",
        source_platform="fixture",
        last_observed_at=now() - timedelta(days=age),
        source_verification_status="source_reported",
        discovery_metadata={"is_confirmed_current": confirmed, **meta},
    )
    info = hiring_intelligence([j], [])
    assert info["hiring_status"] == expected
    assert info["hiring_evidence"][0]["posted_at"] is None


def test_no_jobs_not_inferred_to_mean_not_hiring():
    assert hiring_intelligence([], [])["hiring_status"] == "hiring_unknown"
    item = observed(
        hiring_statement="not_currently_hiring", authoritative_statement=True
    )
    o = SimpleNamespace(
        attributes=item.model_dump(mode="json"),
        observed_at=item.observed_at,
        verification_status="source_reported",
        source=item.source,
        source_url=str(item.source_url),
    )
    assert hiring_intelligence([], [o])["hiring_status"] == "not_currently_hiring"
