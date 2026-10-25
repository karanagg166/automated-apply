"""Owner acceptance cannot be inferred from stored facts or a browser indicator."""
import hashlib

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference, PrivateResume
from backend.app.local_agent.platforms import (
    accept_manual_capability,
    platform_connections,
    save_observation,
)
from backend.app.local_agent.profile_confirmation import (
    confirm_profile,
    confirmation_matches,
)
from backend.app.local_agent.registry import connection_report
from backend.app.models.application_answer import CandidateResource
from backend.app.models.candidate_profile import CandidateProfile


async def profile(session):
    value = CandidateProfile(full_name="Alex Example", email="alex@example.org",
        verified_skills=["Python"], verified_experience_years=0,
        preferences={"target_titles": ["Engineer"], "preferred_locations": ["India"]})
    session.add(value)
    await session.flush()
    return value


@pytest.mark.asyncio
async def test_profile_confirmation_invalidates_after_fact_change(db_session):
    p = await profile(db_session)
    value = await confirm_profile(db_session, p, p.version)
    assert confirmation_matches(p, value)
    p.verified_experience_years = 1
    await db_session.flush()
    assert not confirmation_matches(p, value)
    with pytest.raises(ValueError, match="profile_changed"):
        await confirm_profile(db_session, p, value["profile_version"])
    saved = await db_session.get(OwnerPreference, "phase1_profile_confirmation")
    assert saved.value == value


@pytest.mark.asyncio
async def test_manual_acceptance_never_authenticates_or_invents_observation(db_session):
    await accept_manual_capability(db_session, "naukri")
    rows = await platform_connections(db_session)
    row = next(x for x in rows if x["platform"] == "naukri")
    assert row["state"] == "manual_only" and row["last_verification_time"] is None
    assert not row["api_connected"] and not row["identity_verified"]
    assert not row["owner_acceptance_required"]
    await save_observation(db_session, "naukri", "signed_in_indicator")
    observed = (await platform_connections(db_session))[0]
    assert observed["state"] == "browser_session_observed"
    assert not observed["owner_acceptance_required"]
    await save_observation(db_session, "naukri", "forgotten")
    forgotten = (await platform_connections(db_session))[0]
    assert forgotten["owner_acceptance_required"] and forgotten["last_verification_time"] is None


@pytest.mark.asyncio
async def test_connections_require_current_owner_review_and_actual_resume_integrity(db_session):
    key = Fernet.generate_key()
    settings = Settings(_env_file=None, ENVIRONMENT="testing", RESUME_ENCRYPTION_KEY=key.decode())
    p = await profile(db_session)
    # Authenticated request prevents a network health probe in this offline test.
    rows = {x["name"]: x for x in await connection_report(db_session, settings, api_request=True)}
    assert rows["Candidate profile"]["state"] == "owner_action_required"
    assert "Gmail identity" in rows and "Gmail compose" in rows and "Supabase CLI" in rows
    await confirm_profile(db_session, p, p.version)
    resource = CandidateResource(candidate_profile_id=p.id, resource_type="resume",
        label="Fictional", url="private-resume:fictional", source_type="private_upload",
        is_primary=True, user_confirmed=True)
    db_session.add(resource)
    await db_session.flush()
    raw = b"%PDF-1.4 fictional integrity fixture"
    file = PrivateResume(label="Fictional", ciphertext=Fernet(key).encrypt(raw),
        sha256=hashlib.sha256(raw).hexdigest(), confirmed=True, resource_id=resource.id)
    db_session.add(file)
    await db_session.flush()
    rows = {x["name"]: x for x in await connection_report(db_session, settings, api_request=True)}
    assert rows["Candidate profile"]["state"] == "capability_verified"
    assert rows["Resume"]["state"] == "capability_verified"
    file.sha256 = "0" * 64
    await db_session.flush()
    rows = {x["name"]: x for x in await connection_report(db_session, settings, api_request=True)}
    assert rows["Resume"]["state"] == "degraded"
    assert rows["Resume"]["blocker"] == "file_integrity_failed"
    db_session.add(OwnerPreference(key="phase1_agy_limitation", value={
        "owner_accepted": True, "cli_version": "1.4.7", "generation_disabled": True}))
    await db_session.flush()
    rows = {x["name"]: x for x in await connection_report(db_session, settings, api_request=True)}
    assert rows["AGY CLI"]["state"] == "unsupported"
    assert rows["AGY CLI"]["owner_authorization_required"] is False
    assert rows["AGY CLI"]["capability_verification"] != "structured_generation_verified"


@pytest.mark.asyncio
async def test_acceptance_routes_enforce_auth_version_and_extension_boundary(async_client, phase2_auth, db_session):
    path = "/api/v1/local-agent/profile-confirmation"
    data = {"expected_version": 1, "owner_confirmed": True}
    assert (await async_client.post(path, json=data)).status_code == 401
    assert (await async_client.post(path, json=data, headers=phase2_auth)).status_code == 409
    p = await profile(db_session)
    await db_session.commit()
    assert (await async_client.post(path, json=data, headers={**phase2_auth, "X-Agent-Client": "a" * 32})).status_code == 403
    assert (await async_client.post(path, json={**data, "owner_confirmed": False}, headers=phase2_auth)).status_code == 422
    assert (await async_client.post(path, json=data, headers=phase2_auth)).status_code == 200
    manual = "/api/v1/local-agent/platforms/naukri/accept-manual"
    assert (await async_client.post(manual)).status_code == 401
    assert (await async_client.post(manual, headers={**phase2_auth, "X-Agent-Client": "a" * 32})).status_code == 403
    assert (await async_client.post(manual, headers=phase2_auth)).status_code == 200
    saved = await db_session.scalar(select(OwnerPreference).where(OwnerPreference.key == "phase1_profile_confirmation"))
    assert saved.value["profile_id"] == str(p.id)
