"""Authorized committed-source refresh, approval invalidation and Telegram retrieval."""
import subprocess

import pytest
from pydantic import ValidationError

from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    ProjectConfiguration,
)
from backend.app.candidate_context.persistence import MemoryRecordStore
from backend.app.candidate_context.repository import AuthorizedCheckoutReader
from backend.app.candidate_context.runtime import refresh_projects
from backend.app.candidate_context.service import (
    CandidateContextService,
    TelegramKnowledgeAdapter,
)
from backend.app.core.config import Settings

REPOSITORY = "https://github.com/fictional-owner/fictional-context"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.mark.asyncio
async def test_authorized_source_commit_automatically_recomputes_pending_context(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    git(checkout, "init")
    git(checkout, "config", "user.email", "fictional@example.org")
    git(checkout, "config", "user.name", "Fictional Owner")
    git(checkout, "remote", "add", "origin", REPOSITORY)
    requirements = checkout / "requirements.txt"
    requirements.write_text("fastapi==1.0\n")
    git(checkout, "add", ".")
    git(checkout, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional source")
    svc = CandidateContextService(MemoryRecordStore(), reader=AuthorizedCheckoutReader({REPOSITORY: checkout}))
    await svc.save_configuration(CandidateConfiguration(projects=(ProjectConfiguration(
        id="project-01", name="Fictional service", priority=1, repository_url=REPOSITORY,
    ),)), expected_revision=0, owner_ref="fixture")
    assert await refresh_projects(svc, {}) == {}
    assert (await svc.project("project-01")).candidate is None
    assert await refresh_projects(svc, {REPOSITORY}) == {"project-01": "pending_review"}
    candidate = (await svc.project("project-01")).candidate
    await svc.approve("project-01", expected_revision=candidate.revision,
                      fact_ids=tuple(f.id for f in candidate.facts if f.approvable),
                      owner_ref="fixture", owner_confirmed=True)
    answer = await TelegramKnowledgeAdapter(svc).answer("FastAPI", max_characters=80)
    assert "FastAPI" in answer["text"] and answer["sources"]
    assert answer["generator"] == "deterministic_extractive" and len(answer["text"]) <= 80
    assert await refresh_projects(svc, {REPOSITORY}) == {"project-01": "unchanged"}
    requirements.write_text("fastapi==1.0\nredis==1.0\n")
    git(checkout, "add", ".")
    git(checkout, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional Redis change")
    assert await refresh_projects(svc, {REPOSITORY}) == {"project-01": "pending_review"}
    updated = await svc.project("project-01")
    assert updated.candidate.revision != candidate.revision
    assert updated.approved.revision == candidate.revision
    assert any(f.technology == "Redis" for f in updated.candidate.facts)
    assert await svc.approved_projects() == ()
    assert (await TelegramKnowledgeAdapter(svc).answer("Redis"))["status"] == "missing_approved_context"


@pytest.mark.parametrize("mapping", [
    {REPOSITORY: "relative/path"},
    {"https://example.org/repo": "/tmp/repo"},
    {REPOSITORY + "/tree/main": "/tmp/repo"},
])
def test_checkout_allowlist_rejects_ambiguous_targets(mapping):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CANDIDATE_PROJECT_CHECKOUTS=mapping)
