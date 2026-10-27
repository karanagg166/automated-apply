"""Bounded timing metadata contains no provider bodies or candidate values."""

import httpx
import pytest

from backend.app.db.session import get_session_factory
from backend.app.schemas.discovery import DiscoveryQuery, RunRequest
from backend.app.services.job_discovery_service import JobDiscoveryService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.tests.test_public_ats import configuration, feed, posting


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [LeverAdapter, AshbyAdapter])
async def test_http_decoding_normalization_and_retry_diagnostics(adapter):
    calls = []

    def respond(request):
        calls.append(request)
        return (
            httpx.Response(503)
            if len(calls) == 1
            else httpx.Response(200, json=feed(adapter, [posting(adapter)]))
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await adapter(http_client=client, settings=configuration()).discover(
            DiscoveryQuery(limit=1)
        )
    metrics = result.usage["public_feed"]
    assert metrics["http_attempts"] == 2
    assert metrics["retry_wait_seconds"] >= 0.09
    assert all(
        0 <= metrics[name] < 5
        for name in [
            "request_seconds",
            "json_seconds",
            "normalization_seconds",
            "adapter_seconds",
        ]
    )
    assert "Python Engineer" not in str(metrics) and "Fictional Employer" not in str(
        metrics
    )


@pytest.mark.asyncio
async def test_pacing_and_commit_are_measured_without_logging_job_data(
    db_session, monkeypatch, caplog
):
    class Feed(LeverAdapter):
        def client(self):
            return httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json=feed(LeverAdapter, [posting(LeverAdapter)])
                    )
                )
            )

    monkeypatch.setattr(
        JobSourceFactory,
        "get_adapter",
        lambda source, **kwargs: Feed(settings=kwargs["settings"]),
    )
    caplog.set_level("INFO", logger="job_pulse_agent")
    result = await JobDiscoveryService(
        db_session, get_session_factory(), configuration()
    ).run(
        RunRequest(source="lever", use_profile=False, idempotency_key="timing-fixture")
    )
    assert result["status"] == "success", result
    phases = result["usage"]["diagnostics"]["phase_seconds"]
    assert (
        "provider_pacing" in phases
        and "ingestion" in phases
        and "finalization" in phases
    )
    messages = " ".join(
        r.getMessage()
        for r in caplog.records
        if "discovery_commit_ack" in r.getMessage()
    )
    assert str(result["id"]) in messages
    assert "Python Engineer" not in messages and "jobs.lever.co" not in messages
