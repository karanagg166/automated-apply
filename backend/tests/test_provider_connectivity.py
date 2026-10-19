from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from backend.app.db.session import get_session_factory
from backend.app.models.discovery import now
from backend.app.models.startup import ProviderConnectionCheck
from backend.app.schemas.discovery import DiscoveryError
from backend.app.services.job_sources.direct_api import (
    ArbeitnowAdapter,
    RemotiveAdapter,
)
from backend.app.services.startup_discovery.connectivity import (
    ProviderConnectivity,
    claim_access,
    configuration_fingerprint,
)
from backend.tests.discovery_fakes import settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,payload,state,valid",
    [
        (200, {"data": []}, "configured_not_tested", True),
        (200, {"data": [{"invalid": True}]}, "failed", False),
        (200, {"data": "invalid"}, "failed", False),
        (429, {}, "rate_limited", False),
        (403, {}, "authorization_required", False),
        (503, {}, "failed", False),
        (200, [], "failed", False),
    ],
)
async def test_connectivity_schema_and_mock_labels(
    db_session, code, payload, state, valid
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(code, json=payload))
    ) as client:
        check = await ProviderConnectivity(
            db_session, get_session_factory(), settings()
        ).check("arbeitnow", ArbeitnowAdapter(client))
    assert check["state"] == state, check
    assert check["is_live"] is False
    assert check["schema_valid"] is valid
    assert check["http_status"] == code
    assert "secret" not in str(check)
    assert (
        await db_session.scalars(select(ProviderConnectionCheck))
    ).first() is not None


@pytest.mark.asyncio
async def test_timeout_never_live_verified(db_session):
    def handler(request):
        raise httpx.ReadTimeout("fixture secret")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProviderConnectivity(
            db_session, get_session_factory(), settings()
        ).check("remotive", RemotiveAdapter(client))
    assert result["state"] == "failed" and "secret" not in str(result)


@pytest.mark.asyncio
async def test_durable_rate_gate_and_no_paid_check(db_session):
    service = ProviderConnectivity(db_session, get_session_factory(), settings())
    assert (await service.check("wellfound"))["state"] == "authorization_required"
    assert (await service.check("greenhouse"))["state"] == "not_configured"
    assert (await service.check("yc_directory"))["state"] == "unsupported"
    with pytest.raises(ValueError, match="Unknown"):
        await service.check("https://localhost")
    await claim_access(get_session_factory(), "remotive")
    with pytest.raises(DiscoveryError) as exc:
        await claim_access(get_session_factory(), "remotive")
    assert exc.value.status == "rate_limited"


@pytest.mark.asyncio
async def test_historical_mock_and_stale_live_verification(db_session):
    service = ProviderConnectivity(db_session, get_session_factory(), settings())
    row = ProviderConnectionCheck(
        provider="arbeitnow",
        state="live_verified",
        configuration_fingerprint=configuration_fingerprint("arbeitnow", settings()),
        is_live=True,
        schema_valid=True,
        checked_at=now() - timedelta(hours=25),
        finished_at=now() - timedelta(hours=25),
        result_count=0,
        http_status=200,
    )
    db_session.add(row)
    await db_session.flush()
    first = next(
        s for s in (await service.status())["providers"] if s["provider"] == "arbeitnow"
    )
    assert first["state"] == "configured_not_tested" and not first["live_verified"]
    row.finished_at = now()
    live = next(
        s for s in (await service.status())["providers"] if s["provider"] == "arbeitnow"
    )
    assert live["live_verified"]
    row.is_live = False
    mocked = next(
        s for s in (await service.status())["providers"] if s["provider"] == "arbeitnow"
    )
    assert not mocked["live_verified"]


@pytest.mark.asyncio
async def test_crashed_check_lease_expires(db_session):
    db_session.add(
        ProviderConnectionCheck(
            provider="arbeitnow",
            state="testing",
            is_live=True,
            checked_at=now() - timedelta(hours=1),
        )
    )
    await db_session.flush()
    source = next(
        s
        for s in (await ProviderConnectivity(db_session, None, settings()).status())[
            "providers"
        ]
        if s["provider"] == "arbeitnow"
    )
    assert source["state"] == "failed" and not source["live_verified"]


def test_paid_actor_requires_inclusive_cost_and_account_cap_review():
    from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
    from backend.tests.discovery_fakes import actor_config

    for changes in (
        {"platform_usage_included": False},
        {"account_spending_limit_verified": False},
    ):
        assert ApifyJobAdapter(
            source_name="wellfound",
            configuration=actor_config(**changes),
            settings=settings(),
        ).validate_configuration()
