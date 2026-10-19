"""Local live-mode tooling reuses durable discovery gates without accessing owner data."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.operations.configuration import OperationRejected
from backend.app.services.job_sources.direct_api import ArbeitnowAdapter
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.scripts import local_public_pilot as script


async def test_unauthorized_pilot_stops_before_creating_state(tmp_path):
    args = SimpleNamespace(authorize_public_read=False, state_dir=str(tmp_path / "state"))
    with pytest.raises(OperationRejected, match="authorization_required"):
        await script.execute(args)
    assert not (tmp_path / "state").exists()


async def test_durable_state_prevents_replay_and_preserves_source_windows(tmp_path, monkeypatch, capsys):
    # Preserve the enclosing test process's operator; the child CLI configures its own.
    monkeypatch.setattr(script, "configure_operator", lambda settings: None)
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [], "links": {}})

    state = tmp_path / "private-state"
    args = SimpleNamespace(authorize_public_read=True, state_dir=str(state),
                           source="arbeitnow", idempotency_key="first-local-pilot")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        # Keep _client=None so the production pacing path runs; replace only I/O.
        monkeypatch.setattr(ArbeitnowAdapter, "client", lambda self: client)
        monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **kw: ArbeitnowAdapter())
        await script.execute(args)
        first = json.loads(capsys.readouterr().out)
        await script.execute(args)
        replay = json.loads(capsys.readouterr().out)
        assert first["run_id"] == replay["run_id"]
        args.idempotency_key = "second-local-pilot"
        await script.execute(args)
        paced = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    assert paced["discovery_status"] == "rate_limited"
    assert first["actual_jobs"] == first["candidate_matched_jobs"] == 0
    assert not first["staging_deployed"] and not first["real_pilot_verified"]
    assert not first["owner_profile_used"] and first["paid_requests"] == 0
    assert first["emails_sent"] == first["applications_submitted"] == 0
    assert (state / "public.sqlite").stat().st_mode & 0o077 == 0


def test_local_mode_does_not_inherit_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-owner-key")
    monkeypatch.setenv("GMAIL_SENDING_ENABLED", "true")
    monkeypatch.setenv("APOLLO_ENRICHMENT_ENABLED", "true")
    settings = script.public_settings(tmp_path / "public.sqlite")
    assert settings.GEMINI_API_KEY is None
    assert not settings.GMAIL_SENDING_ENABLED and not settings.APOLLO_ENRICHMENT_ENABLED
    assert settings.DATABASE_URL.startswith("sqlite+aiosqlite:///")
