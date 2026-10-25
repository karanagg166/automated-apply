"""Owner-authenticated candidate context API route tests."""

import pytest
from httpx import AsyncClient

from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    ProjectConfiguration,
)


@pytest.mark.asyncio
async def test_candidate_context_routes_require_auth(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "test-token")
    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    try:
        response = await async_client.get("/api/v1/dashboard/candidate-context/configuration")
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_candidate_context_configuration_lifecycle(
    async_client: AsyncClient, phase2_auth: dict[str, str]
):
    # Initial configuration is empty revision 0
    resp = await async_client.get(
        "/api/v1/dashboard/candidate-context/configuration",
        headers=phase2_auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["revision"] == 0
    assert len(data["configuration"]["projects"]) == 3
    assert data["configuration"]["projects"][0]["id"] == "project-01"

    # Update configuration
    new_cfg = CandidateConfiguration(
        projects=(
            ProjectConfiguration(
                id="project-01",
                name="Test Project",
                priority=1,
                repository_url="https://github.com/example/repo",
                tech_stack=("Python", "FastAPI"),
            ),
        )
    )
    update_resp = await async_client.put(
        "/api/v1/dashboard/candidate-context/configuration",
        headers=phase2_auth,
        json={
            "configuration": new_cfg.model_dump(mode="json"),
            "expected_revision": 0,
        },
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["revision"] == 1
    assert len(updated_data["configuration"]["projects"]) == 1

    # Conflict on bad revision
    conflict_resp = await async_client.put(
        "/api/v1/dashboard/candidate-context/configuration",
        headers=phase2_auth,
        json={
            "configuration": new_cfg.model_dump(mode="json"),
            "expected_revision": 0,
        },
    )
    assert conflict_resp.status_code == 409


@pytest.mark.asyncio
async def test_candidate_context_projects_and_answer(
    async_client: AsyncClient, phase2_auth: dict[str, str]
):
    # Setup configuration with a project
    new_cfg = CandidateConfiguration(
        projects=(
            ProjectConfiguration(
                id="project-alpha",
                name="Alpha Service",
                priority=1,
                repository_url="https://github.com/example/alpha",
                tech_stack=("Redis", "PostgreSQL"),
            ),
        )
    )
    await async_client.put(
        "/api/v1/dashboard/candidate-context/configuration",
        headers=phase2_auth,
        json={
            "configuration": new_cfg.model_dump(mode="json"),
            "expected_revision": 0,
        },
    )

    # List projects
    list_resp = await async_client.get(
        "/api/v1/dashboard/candidate-context/projects",
        headers=phase2_auth,
    )
    assert list_resp.status_code == 200
    projects = list_resp.json()
    assert len(projects) == 1
    assert projects[0]["project"]["id"] == "project-alpha"

    # Get single project
    proj_resp = await async_client.get(
        "/api/v1/dashboard/candidate-context/projects/project-alpha",
        headers=phase2_auth,
    )
    assert proj_resp.status_code == 200
    assert proj_resp.json()["revision"] == 0

    # Answer query when no facts approved yet
    answer_resp = await async_client.get(
        "/api/v1/dashboard/candidate-context/answer",
        headers=phase2_auth,
        params={"question": "What is your experience with Redis?"},
    )
    assert answer_resp.status_code == 200
    ans = answer_resp.json()
    assert ans["status"] == "missing_approved_context"
    assert ans["generator"] == "deterministic_extractive"


