import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.models.application_answer import CandidateResource
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.repositories.candidate_profile import ProfileConflictError, ProfilePreconditionError
from backend.app.schemas.candidate_resources import ResourceWrite
from backend.scripts.import_candidate_resources import import_defaults


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://localhost/a", "https://127.0.0.1/a", "https://169.254.169.254/a", "https://example.com:8443/a", "file:///tmp/resume", "https://example.com/%0afoo", "https://10.0.0.1/a"])
def test_invalid_resource_urls(url):
    with pytest.raises(ValidationError):
        ResourceWrite(resource_type="resume", label="Resume", url=url)


@pytest.mark.parametrize("values", [
    {"LLM_PROVIDER": "cohere"}, {"LLM_MODEL": "https://evil.example/model"}, {"LLM_MODEL": "model with spaces"},
    {"LLM_MAX_OUTPUT_TOKENS": 0}, {"LLM_MAX_INPUT_CHARS": 999999}, {"LLM_TIMEOUT_SECONDS": float("inf")},
    {"LLM_MONTHLY_MAX_REQUESTS": -1}, {"LLM_MAX_CONCURRENCY": 100}, {"CANDIDATE_GITHUB_URL": "https://user@example.com"},
])
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_empty_settings_and_secret_repr():
    settings = Settings(_env_file=None, LLM_MODEL="", GEMINI_API_KEY="fictional-secret-key")
    assert settings.LLM_MODEL is None
    assert "fictional-secret-key" not in repr(settings)


@pytest.mark.asyncio
async def test_resources_and_conflicts(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    data = ResourceWrite(resource_type="resume", label="General resume", url="https://drive.google.com/file/d/fictional/view", is_primary=True, user_confirmed=True)
    first = await repo.save_resource(data)
    assert first.candidate_profile_id == phase2_profile.id
    with pytest.raises(ProfileConflictError):
        await repo.save_resource(data)
    with pytest.raises(ProfileConflictError):
        await repo.save_resource(ResourceWrite.model_validate({**data.model_dump(mode="json"), "url": "https://example.com/second"}))
    assert len(await repo.resources(phase2_profile.id)) == 1
    await repo.save_resource(data.model_copy(update={"id": first.id, "is_primary": False}))
    await repo.save_resource(ResourceWrite.model_validate({**data.model_dump(mode="json"), "url": "https://example.com/second"}))
    assert len(await repo.resources(phase2_profile.id)) == 2


@pytest.mark.asyncio
async def test_standard_links_have_only_one_authority(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    data = ResourceWrite(resource_type="github", label="Original GitHub", url="https://github.com/another-example", user_confirmed=True)
    with pytest.raises(ProfilePreconditionError):
        await repo.save_resource(data)
    result = await repo.save_resource(data.model_copy(update={"expected_profile_version": 1}))
    assert result["source"] == "candidate_profile" and phase2_profile.version == 2
    assert not await repo.resources(phase2_profile.id)
    with pytest.raises(ProfileConflictError):
        await repo.save_resource(data.model_copy(update={"expected_profile_version": 1}))


@pytest.mark.asyncio
async def test_environment_import_dry_run_non_overwrite(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    settings = Settings(_env_file=None, CANDIDATE_GITHUB_URL="https://github.com/env-example", CANDIDATE_RESUME_DRIVE_URL="https://drive.google.com/file/d/example/view")
    actions = await import_defaults(repo, settings, apply=False)
    assert [a["resource_type"] for a in actions] == ["resume"]
    assert not await repo.resources(phase2_profile.id)
    await import_defaults(repo, settings, apply=True)
    assert phase2_profile.github_url == "https://github.com/example" and phase2_profile.version == 1
    item = (await repo.resources(phase2_profile.id))[0]
    assert not item.user_confirmed and item.source_type == "environment_import"
    assert not await import_defaults(repo, settings, apply=True)


@pytest.mark.asyncio
async def test_resource_rollback(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    await repo.save_resource(ResourceWrite(resource_type="resume", label="Resume", url="https://example.com/resume"))
    await db_session.rollback()
    assert not (await db_session.scalars(select(CandidateResource))).all()


@pytest.mark.asyncio
async def test_standard_default_import_is_explicit_and_idempotent(db_session, phase2_profile):
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    await db_session.delete(phase2_profile)
    await db_session.flush()
    profile = await CandidateProfileRepository(db_session).create_primary_profile(CandidateProfileCreate(full_name="New Example", email="new@example.com"))
    settings = Settings(_env_file=None, CANDIDATE_GITHUB_URL="https://github.com/env-example", CANDIDATE_ORIGINAL_LINKEDIN_URL="https://www.linkedin.com/in/env-example")
    repo = CandidateKnowledgeRepository(db_session)
    assert len(await import_defaults(repo, settings, apply=False)) == 2
    assert profile.github_url is None and profile.version == 1
    await import_defaults(repo, settings, apply=True)
    assert profile.github_url == "https://github.com/env-example" and profile.version == 3
    assert not await import_defaults(repo, settings, apply=True)


@pytest.mark.asyncio
async def test_resolver_finds_primary_beyond_first_list_page(db_session, phase2_profile):
    from backend.app.services.profile_link_resolver import ProfileLinkResolver
    db_session.add_all([CandidateResource(candidate_profile_id=phase2_profile.id, resource_type="resume", label=f"Variant {i}", url=f"https://example.com/resume/{i}", user_confirmed=True) for i in range(110)])
    await db_session.flush()
    repo = CandidateKnowledgeRepository(db_session)
    await repo.save_resource(ResourceWrite(resource_type="resume", label="Selected resume", url="https://example.com/primary", user_confirmed=True, is_primary=True))
    result = ProfileLinkResolver(phase2_profile, await repo.resolution_resources(phase2_profile.id), Settings(_env_file=None)).resolve("Resume URL")
    assert result.answer == "https://example.com/primary"
