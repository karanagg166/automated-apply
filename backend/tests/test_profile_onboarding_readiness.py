"""No inferred personal facts, implicit profile imports or ambiguous resume selections."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from backend.app.operations.configuration import OperationRejected
from backend.app.operations.onboarding import assess_profile, reject_placeholders
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.scripts.onboard_profile import import_profile


def candidate():
    return CandidateProfileCreate(full_name="Morgan Patel", email="morgan@owner.dev",
        github_url="https://github.com/morgan-patel", linkedin_url="https://linkedin.com/in/morgan-patel",
        portfolio_url="https://owner.invalid", verified_experience_years=0,
        verified_skills=["Python"], projects=[{"name": "Relay", "contribution": "I built authentication",
            "technologies": ["Python"]}], preferences={"target_titles": ["Backend Engineer"], "remote_preference": "remote"})


def resume():
    return SimpleNamespace(id=uuid4(), resource_type="resume", label="Owner resume", url="https://owner.invalid/resume.pdf",
        is_primary=True, user_confirmed=True, updated_at="1")


def test_missing_profile_is_blocked():
    assert assess_profile(None).missing == ["candidate_profile"]


def test_complete_profile_still_needs_owner_confirmation():
    result = assess_profile(candidate(), [resume()])
    assert result.status == "owner_confirmation_required"
    assert not result.identity_independently_verified
    assert not result.missing


def test_conflicting_resume_resources_block_readiness():
    assert "confirmed_unique_primary_resume" in assess_profile(candidate(), [resume(), resume()]).missing


def test_missing_work_history_does_not_invent_experience():
    data = candidate().model_copy(update={"verified_experience_years": None})
    assert "work_history_or_explicit_zero_experience" in assess_profile(data).missing


@pytest.mark.parametrize("text", ["Alex Example", "alex@example.com", "https://fictional.example/resume", "TODO user", "YOUR_NAME"])
def test_placeholder_live_data_rejected(text):
    with pytest.raises(OperationRejected, match="placeholder"):
        reject_placeholders(text)


@pytest.mark.asyncio
async def test_profile_import_idempotency_and_version_checks():
    data, state = candidate(), {"value": None, "version": 0, "writes": 0}

    def request(req):
        if req.method == "GET":
            return httpx.Response(404 if state["value"] is None else 200, json=state["value"] or {})
        import json
        value = json.loads(req.content)
        if state["value"] is None:
            state["version"] = 1
        state["value"] = {**value, "version": state["version"]}
        state["writes"] += 1
        return httpx.Response(200, json=state["value"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(request), base_url="https://staging.invalid") as client:
        assert (await import_profile(client, data, 0))["profile_version"] == 1
        assert (await import_profile(client, data, 1))["profile_version"] == 1
        with pytest.raises(OperationRejected, match="version_conflict"):
            await import_profile(client, data, 0)
    assert state["writes"] == 2
