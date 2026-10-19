"""Operational integration covers zero results, replay, interrupted runs and bounded network modes."""

import json
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.models.discovery import DiscoveryRun, now
from backend.app.operations.configuration import OperationRejected
from backend.app.operations.network import NetworkAudit
from backend.app.operations.pilot import PilotRequest, run_pilot
from backend.app.services.applications.platforms.public_listing import (
    PublicListingPlatform,
)
from backend.app.services.job_sources.direct_api import GreenhouseAdapter
from backend.app.services.job_sources.factory import JobSourceFactory


@pytest.mark.asyncio
async def test_zero_results_and_idempotent_replay_are_truthful(db_session, monkeypatch):
    from backend.app.db.session import get_session_factory

    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={"jobs": []})

    config = Settings(_env_file=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **kw: GreenhouseAdapter(
            board_token="fictional", company_name="Fictional", http_client=client))
        request = PilotRequest(source="greenhouse", idempotency_key="zero_result_pilot")
        first = await run_pilot(db_session, get_session_factory(), config, request)
        second = await run_pilot(db_session, get_session_factory(), config, request)
    assert first["actual_jobs"] == first["actual_companies"] == 0
    assert first["candidate_matched_jobs"] == 0
    assert first["run_id"] == second["run_id"]
    assert "zero_relevant_companies_no_records_invented" in first["blockers"]
    assert len(calls) == 1
    run = await db_session.get(DiscoveryRun, __import__("uuid").UUID(first["run_id"]))
    run.status, run.started_at = "running", now() - timedelta(hours=1)
    await db_session.commit()
    recovered = await run_pilot(db_session, get_session_factory(), config, request)
    assert recovered["discovery_status"] == "recovery_required"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_packet_requires_explicit_confirmed_profile(db_session):
    from backend.app.db.session import get_session_factory
    with pytest.raises(OperationRejected, match="profile_use"):
        await run_pilot(db_session, get_session_factory(), Settings(_env_file=None),
                        PilotRequest(idempotency_key="no_profile_use", prepare_packet=True))


@pytest.mark.parametrize("code,state", [(429, "rate_limited"), (503, "source_unavailable")])
@pytest.mark.asyncio
async def test_provider_failure_cannot_become_success(db_session, monkeypatch, code, state):
    from backend.app.db.session import get_session_factory
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(code))) as client:
        monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **kw: GreenhouseAdapter(
            board_token="fictional", company_name="Fictional", http_client=client))
        report = await run_pilot(db_session, get_session_factory(), Settings(_env_file=None),
                                 PilotRequest(source="greenhouse", idempotency_key="failed_pilot_" + str(code)))
    assert report["discovery_status"] == state
    assert report["actual_jobs"] == 0
    assert report["blockers"]


@pytest.mark.asyncio
async def test_network_mode_blocks_gmail_paid_and_arbitrary_urls():
    with NetworkAudit() as audit:
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="forbidden"):
                await client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    assert audit.attempted == 0


@pytest.mark.parametrize("source,url,application,verification,valid", [
    ("greenhouse", "https://job-boards.greenhouse.io/verified/jobs/1", "https://job-boards.greenhouse.io/verified/jobs/1", "source_reported", True),
    ("greenhouse", "https://attacker.invalid/1", "https://attacker.invalid/apply", "source_reported", False),
    ("hacker_news", "https://news.ycombinator.com/item?id=123", None, "requires_review", False),
    ("remotive", "https://remotive.com/remote-jobs/123", None, "source_reported", False),
    ("arbeitnow", "https://www.arbeitnow.com/jobs/123", "http://localhost/secret", "source_reported", False),
])
def test_public_packet_requires_attributed_explicit_safe_destination(source, url, application, verification, valid):
    job = SimpleNamespace(source_platform=source, job_url=url, application_url=application,
                          status="discovered", source_verification_status=verification)
    result = PublicListingPlatform(source).destination(job)
    assert result.valid == valid
    assert not PublicListingPlatform(source).capabilities().live_verified


def test_offline_end_to_end_never_claims_a_real_pilot(tmp_path):
    result = subprocess.run([sys.executable, "backend/scripts/smoke_test.py", "--output", str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["actual_companies"] == report["actual_jobs"] == 0
    assert not report["actual_external_calls"]
    assert not report["real_pilot_verified"]
    assert report["fake_grounded_answer_validated"]
    assert report["manual_handoff_verified"]
    assert report["emails_sent"] == report["applications_submitted"] == 0
    assert (tmp_path / "phase6b-pilot-summary.json").stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_fictional_gemini_evaluation_rejects_unsupported_claims():
    from backend.app.ai.schemas import (
        EvidenceReference,
        ModelAnswer,
        ProviderAnswer,
        SupportedClaim,
    )
    from backend.scripts.validate_gemini import evaluate

    class Usage:
        async def generate(self, provider, question, context, instructions):
            ref = EvidenceReference.model_validate(context["evidence"][0]["reference"])
            return ProviderAnswer(content=ModelAnswer(answer="I scaled to 100000 users.", evidence_references=[ref],
                claims=[SupportedClaim(text="I scaled to 100000 users.", quote="I implemented authentication using Python and FastAPI.", source=ref)]))

    result = await evaluate(Usage(), None)
    assert result["status"] == "grounding_checks_failed"
    assert not result["factual_accuracy_proven"]
    assert not result["personal_data_sent"]
    assert "100000" not in str(result)


@pytest.mark.asyncio
async def test_public_network_mode_forbids_external_mutations():
    from backend.app.operations.network import PUBLIC_HOSTS
    with NetworkAudit(PUBLIC_HOSTS) as audit:
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="forbidden"):
                await client.post("https://boards-api.greenhouse.io/v1/boards/example/jobs/1", json={})
    assert audit.attempted == 0
