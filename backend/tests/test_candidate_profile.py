"""Fictional fixtures only; these tests never seed a real user's profile."""

import uuid
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import IntegrityError
from backend.app.core.config import get_settings
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.repositories.candidate_profile import (
    CandidateProfileRepository, ProfileConflictError, ProfileNotFoundError,
)
from backend.app.schemas.candidate_profile import CandidateProfileCreate, CandidateProfileUpdate
from backend.app.services.application_assistant import ApplicationAssistant
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.db.session import get_session_factory

MINIMAL = {"full_name": "Alex Example", "email": "alex@example.com"}
COMPLETE = {
    **MINIMAL, "phone": "+1 555 0100", "linkedin_url": "https://linkedin.com/in/example",
    "github_url": "https://github.com/example", "portfolio_url": "https://example.com/portfolio",
    "personal_website": "https://example.com", "verified_experience_years": 2.5,
    "verified_skills": ["Python", "SQL"],
    "verified_roles": [{"company": "Example Company", "role": "Developer", "highlight": "Built an API", "start_date": "2022-01-01"}],
    "education": [{"institution": "Example College", "qualification": "BSc"}],
    "projects": [{"name": "Example Project", "technologies": ["Python"], "achievements": ["Created a CLI"]}],
    "certifications": [{"name": "Example Certification"}], "summary": "Developer working on APIs",
    "preferences": {"target_titles": ["Backend Engineer"], "technology_stacks": ["Python"],
                    "preferred_locations": ["London"], "remote_preference": "onsite",
                    "employment_types": ["full_time"], "minimum_salary": 50000,
                    "salary_currency": "GBP", "notice_period_days": 14,
                    "work_authorization": "User supplied authorization statement",
                    "prioritize_startups": True, "excluded_companies": ["Example Excluded"]},
}


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setattr(get_settings(), "JOB_AGENT_API_TOKEN", SecretStr("test-profile-token"))
    return {"Authorization": "Bearer test-profile-token"}


@pytest.mark.parametrize("payload", [MINIMAL, COMPLETE])
def test_valid_profiles(payload):
    profile = CandidateProfileCreate(**payload)
    assert profile.full_name == "Alex Example"


@pytest.mark.parametrize("patch", [
    {"email": "invalid"}, {"github_url": "https://user:password@example.com"}, {"github_url": "javascript:alert(1)"}, {"github_url": "not-url"},
    {"verified_experience_years": -1}, {"verified_experience_years": float("nan")},
    {"preferences": {"minimum_salary": -1}}, {"preferences": {"remote_preference": "sometimes"}},
    {"preferences": {"employment_types": ["permanent"]}}, {"full_name": "x" * 201},
    {"summary": "x" * 4001}, {"summary": "   "}, {"full_name": " "},
    {"verified_skills": ["x"] * 101}, {"verified_roles": [{"company": "a", "role": "b"}] * 51},
    {"verified_skills": [""]}, {"preferences": {"work_authorization": " "}},
    {"oauth_token": "forbidden"}, {"projects": [{"name": "a", "unknown": "b"}]},
    {"verified_roles": [{"company": "x", "role": "y", "start_date": "2024-01-01", "end_date": "2023-01-01"}]},
])
def test_invalid_profiles(patch):
    with pytest.raises(ValidationError):
        CandidateProfileCreate(**{**MINIMAL, **patch})


def test_normalization_and_unknowns():
    profile = CandidateProfileCreate(**{**MINIMAL, "full_name": " Alex   Example ", "verified_skills": [" Python ", "python", "SQL"]})
    assert profile.verified_skills == ["Python", "SQL"]
    assert profile.full_name == "Alex Example"
    assert profile.verified_experience_years is None
    assert profile.preferences.notice_period_days is None
    assert profile.preferences.work_authorization is None
    assert profile.preferences.prioritize_startups is None


@pytest.mark.parametrize("payload", [{}, {"full_name": None}, {"verified_skills": None}, {"preferences": None}, {"preferences": {"target_titles": None}}])
def test_invalid_partial_updates(payload):
    with pytest.raises(ValidationError):
        CandidateProfileUpdate(**payload)


def test_payload_size():
    with pytest.raises(ValidationError, match="64 KiB"):
        CandidateProfileCreate(**{**MINIMAL, "projects": [{"name": "x", "description": "x" * 4000}] * 20})


async def test_repository_create_retrieve_patch_idempotence(db_session):
    repo = CandidateProfileRepository(db_session)
    assert await repo.get_primary_profile() is None
    profile = await repo.create_primary_profile(CandidateProfileCreate(**COMPLETE))
    created_at, updated_at, profile_id = profile.created_at, profile.updated_at, profile.id
    same, created = await repo.upsert_primary_profile(CandidateProfileCreate(**COMPLETE))
    assert not created and same.id == profile_id and same.version == 1
    assert same.updated_at.replace(tzinfo=None) == updated_at.replace(tzinfo=None)
    updated = await repo.update_primary_profile(CandidateProfileUpdate(phone=None, preferences={"remote_preference": "remote"}), 1)
    assert updated.phone is None and updated.version == 2
    assert updated.verified_skills == ["Python", "SQL"]
    assert updated.preferences["minimum_salary"] == 50000
    assert updated.preferences["remote_preference"] == "remote"
    assert updated.created_at.replace(tzinfo=None) == created_at.replace(tzinfo=None)
    with pytest.raises(ProfileConflictError):
        await repo.update_primary_profile(CandidateProfileUpdate(summary="Stale"), 1)
    with pytest.raises(ProfileConflictError):
        await repo.create_primary_profile(CandidateProfileCreate(**MINIMAL))


async def test_singleton_database_constraint(db_session):
    repo = CandidateProfileRepository(db_session)
    await repo.create_primary_profile(CandidateProfileCreate(**MINIMAL))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(CandidateProfile(**MINIMAL))
            await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(CandidateProfile(**MINIMAL, singleton_key="secondary"))
            await db_session.flush()


async def test_persistence_separate_sessions_and_unrelated_records():
    async with get_session_factory()() as first:
        company = Company(name="Existing Company", domain="existing.example")
        first.add(company)
        await first.flush()
        company_id = company.id
        await CandidateProfileRepository(first).create_primary_profile(CandidateProfileCreate(**COMPLETE))
        await first.commit()
    async with get_session_factory()() as second:
        repo = CandidateProfileRepository(second)
        profile = await repo.get_primary_profile()
        assert profile.email == MINIMAL["email"]
        await repo.update_primary_profile(CandidateProfileUpdate(summary="Updated"), profile.version)
        await second.commit()
    async with get_session_factory()() as third:
        assert (await CandidateProfileRepository(third).get_primary_profile()).summary == "Updated"
        assert (await third.get(Company, company_id)).name == "Existing Company"


async def test_stale_session_cannot_overwrite():
    async with get_session_factory()() as first, get_session_factory()() as second:
        await CandidateProfileRepository(first).create_primary_profile(CandidateProfileCreate(**MINIMAL))
        await first.commit()
        stale = await CandidateProfileRepository(second).get_primary_profile()
        version = stale.version
        await CandidateProfileRepository(first).update_primary_profile(CandidateProfileUpdate(summary="Winner"), 1)
        await first.commit()
        with pytest.raises(ProfileConflictError):
            await CandidateProfileRepository(second).update_primary_profile(CandidateProfileUpdate(summary="Loser"), version)


async def test_no_profile_service(db_session):
    with pytest.raises(ProfileNotFoundError):
        await CandidateProfileService(db_session).get_profile()


async def test_api_lifecycle(async_client, auth):
    assert (await async_client.get("/api/v1/profile", headers=auth)).status_code == 404
    created = await async_client.put("/api/v1/profile", json=COMPLETE, headers=auth)
    assert created.status_code == 201, created.text
    assert created.headers["etag"] == '"1"'
    assert created.headers["cache-control"] == "no-store"
    read = await async_client.get("/api/v1/profile", headers=auth)
    assert read.json() == created.json()
    same = await async_client.put("/api/v1/profile", json=COMPLETE, headers=auth)
    assert same.status_code == 200 and same.json() == created.json()
    missing_precondition = await async_client.put("/api/v1/profile", json=MINIMAL, headers=auth)
    assert missing_precondition.status_code == 428
    patched = await async_client.patch("/api/v1/profile", json={"phone": None, "preferences": {"remote_preference": "remote"}}, headers={**auth, "If-Match": '"1"'})
    assert patched.status_code == 200, patched.text
    assert patched.json()["verified_roles"] == created.json()["verified_roles"]
    assert patched.json()["preferences"]["minimum_salary"] == 50000
    assert patched.json()["version"] == 2
    stale = await async_client.patch("/api/v1/profile", json={"summary": "Stale"}, headers={**auth, "If-Match": '"1"'})
    assert stale.status_code == 409
    replaced = await async_client.put("/api/v1/profile", json=MINIMAL, headers={**auth, "If-Match": '"2"'})
    assert replaced.status_code == 200
    assert replaced.json()["verified_skills"] == []
    assert replaced.json()["verified_experience_years"] is None
    assert replaced.json()["created_at"] == created.json()["created_at"]


@pytest.mark.parametrize("method,path", [("get", "/api/v1/profile"), ("put", "/api/v1/profile"), ("patch", "/api/v1/profile"), ("post", f"/api/v1/jobs/{uuid.uuid4()}/match")])
@pytest.mark.parametrize("token", [None, "Bearer wrong", "Basic test-profile-token", "Bearer ☃"])
async def test_auth_rejections(async_client, auth, method, path, token):
    headers = {} if token is None else {b"Authorization": token.encode("utf-8")}
    response = await async_client.request(method, path, headers=headers)
    assert response.status_code == 401


@pytest.mark.parametrize("token", [None, SecretStr(""), SecretStr(" ")])
async def test_auth_unconfigured(async_client, monkeypatch, token):
    monkeypatch.setattr(get_settings(), "JOB_AGENT_API_TOKEN", token)
    assert (await async_client.get("/api/v1/profile")).status_code == 503


async def test_api_bad_requests(async_client, auth):
    assert (await async_client.put("/api/v1/profile", content="{broken", headers=auth)).status_code == 422
    assert (await async_client.put("/api/v1/profile", json={**MINIMAL, "email": "bad"}, headers=auth)).status_code == 422
    assert (await async_client.patch("/api/v1/profile", json={"full_name": None}, headers=auth)).status_code == 422
    assert (await async_client.patch("/api/v1/profile", json={"summary": "New"}, headers=auth)).status_code == 428
    assert (await async_client.patch("/api/v1/profile", json={"summary": "New"}, headers={**auth, "If-Match": "1"})).status_code == 422
    assert (await async_client.put("/api/v1/profile", content=b" " * 65537, headers=auth)).status_code == 413
    assert (await async_client.post("/api/v1/jobs/invalid/match", headers=auth)).status_code == 422
    assert (await async_client.post(f"/api/v1/jobs/{uuid.uuid4()}/match", headers=auth)).status_code == 404


async def test_saved_profile_matching_and_privacy(async_client, auth):
    async with get_session_factory()() as session:
        job = Job(title="Backend Engineer", job_url="https://example.com/job", source_platform="manual", location="London", is_remote=False, skills_required=["Python", "Go"])
        session.add(job)
        await session.commit()
        job_id = job.id
    assert (await async_client.post(f"/api/v1/jobs/{job_id}/match", headers=auth)).status_code == 404
    await async_client.put("/api/v1/profile", json=COMPLETE, headers=auth)
    response = await async_client.post(f"/api/v1/jobs/{job_id}/match", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["matched_skills"] == ["Python"]
    assert response.json()["missing_skills"] == ["Go"]
    assert response.json()["location_match"] is True
    await async_client.patch("/api/v1/profile", json={"preferences": {"remote_preference": "remote"}}, headers={**auth, "If-Match": '"1"'})
    assert (await async_client.post(f"/api/v1/jobs/{job_id}/match", headers=auth)).json()["location_match"] is False
    assert (await async_client.get("/api/v1/jobs")).status_code == 401
    jobs = (await async_client.get("/api/v1/jobs", headers=auth)).json()
    assert jobs[0]["match_explanation"] is None and jobs[0]["match_score"] is None


async def test_unknown_facts_not_fabricated(db_session):
    service = CandidateProfileService(db_session)
    await service.create_profile(CandidateProfileCreate(**MINIMAL))
    profile = await service.to_application_profile()
    assert profile.verified_experience_years is None
    assert profile.notice_period_days is None and profile.work_authorization is None
    job = Job(id=uuid.uuid4(), title="Engineer", job_url="https://linkedin.com/jobs/1", source_platform="linkedin", experience_level="senior")
    assistant = ApplicationAssistant(db_session)
    result = assistant.calculate_match(job, profile)
    assert "Experience is unknown" in result.explanation
    draft = assistant.generate_draft_application(job, "Example", profile)
    assert not draft.submission_allowed
    assert "years" not in draft.tailored_cover_letter
    assert "software engineering" not in draft.tailored_cover_letter
    assert set(draft.prepared_answers) == {"Full Name", "Email Address"}
    assert (await service.get_verified_career_information())["verified_experience_years"] is None


async def test_repository_rollback_is_owned_by_caller():
    async with get_session_factory()() as session:
        await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(**MINIMAL))
        await session.rollback()
    async with get_session_factory()() as session:
        assert await CandidateProfileRepository(session).get_primary_profile() is None


async def test_combined_patch_payload_limit(async_client, auth):
    projects = [{"name": str(i), "description": "x" * 3900} for i in range(10)]
    response = await async_client.put("/api/v1/profile", headers=auth, json={**MINIMAL, "projects": projects})
    assert response.status_code == 201
    roles = [{"company": "Example", "role": "Engineer", "highlight": "x" * 3900} for _ in range(10)]
    response = await async_client.patch("/api/v1/profile", headers={**auth, "If-Match": '"1"'}, json={"verified_roles": roles})
    assert response.status_code == 422
    saved = (await async_client.get("/api/v1/profile", headers=auth)).json()
    assert saved["version"] == 1 and saved["verified_roles"] == []


async def test_openapi_declares_profile_routes(async_client):
    schema = (await async_client.get("/openapi.json")).json()
    assert set(schema["paths"]["/api/v1/profile"]) == {"get", "put", "patch"}
    assert "CandidateProfileRead" in schema["components"]["schemas"]
    assert schema["paths"]["/api/v1/profile"]["get"]["security"] == [{"ProfileBearer": []}]


async def test_no_secrets_or_profile_in_unauthorized_response(async_client, auth, caplog):
    await async_client.put("/api/v1/profile", headers=auth, json=MINIMAL)
    response = await async_client.get("/api/v1/profile", headers={"Authorization": "Bearer wrong-private-token"})
    assert response.status_code == 401
    assert "alex@example.com" not in response.text
    assert "wrong-private-token" not in caplog.text
    assert "test-profile-token" not in caplog.text
    assert "alex@example.com" not in caplog.text
