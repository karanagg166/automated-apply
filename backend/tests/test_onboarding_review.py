"""Fictional onboarding proposals, integrity, provenance, and owner review gates."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from backend.app.ai.schemas import GenerateRequest
from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    ProjectConfiguration,
)
from backend.app.candidate_context.persistence import MemoryRecordStore, SQLRecordStore
from backend.app.candidate_context.projects import EvidenceReference, make_fact
from backend.app.candidate_context.repository import RepositorySnapshot, extract_project
from backend.app.candidate_context.review import (
    confirmation_requests,
    write_private_review,
)
from backend.app.candidate_context.service import CandidateContextService
from backend.app.core.config import get_settings
from backend.app.dashboard.models import PrivateResume
from backend.app.dashboard.resumes import verified_pdf
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.test_phase7_dashboard import pdf_bytes


def fact(
    text="I developed inventory workflows using PostgreSQL and Redis.",
    topic="contribution",
):
    return make_fact(
        topic,
        text,
        "owner_supplied",
        (
            EvidenceReference(
                file="private-resume/fictional.pdf",
                content_sha256="b" * 64,
            ),
        ),
        personal_claim=True,
    )


async def document_service(records=None):
    service = CandidateContextService(records or MemoryRecordStore())
    await service.save_configuration(
        CandidateConfiguration(
            projects=(
                ProjectConfiguration(
                    id="project-employment",
                    name="Fictional employment project",
                    priority=1,
                ),
            )
        ),
        expected_revision=0,
        owner_ref="fictional-owner",
    )
    return service


@pytest.mark.parametrize("damage", ["valid", "ciphertext", "sha256"])
def test_encrypted_pdf_integrity(damage, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("RESUME_ENCRYPTION_KEY", key.decode())
    get_settings.cache_clear()
    raw = pdf_bytes("Alex Fictional")
    resume = SimpleNamespace(
        ciphertext=Fernet(key).encrypt(raw), sha256=hashlib.sha256(raw).hexdigest()
    )
    if damage == "ciphertext":
        resume.ciphertext = b"corrupt-private-fixture"
    if damage == "sha256":
        resume.sha256 = "0" * 64
    if damage == "valid":
        assert verified_pdf(resume) == raw
    else:
        with pytest.raises(HTTPException) as error:
            verified_pdf(resume)
        assert error.value.status_code == 409
        assert "Alex Fictional" not in str(error.value.detail)
    get_settings.cache_clear()


async def test_document_only_project_has_no_invented_commit_and_requires_owner():
    service = await document_service()
    _, knowledge = await service.build(
        "project-employment", expected_configuration_revision=1, owner_facts=(fact(),)
    )
    assert knowledge.candidate.commit_sha is None
    assert knowledge.candidate.last_verified_version is None
    assert knowledge.approved is None
    assert not await service.answer_evidence(
        "Describe your best project", "project_explanation"
    )
    for owner, confirmed in [("", True), ("owner", False)]:
        with pytest.raises(ContextError, match="explicit_owner_review_required"):
            await service.approve(
                "project-employment",
                expected_revision=knowledge.candidate.revision,
                fact_ids=(fact().id,),
                owner_ref=owner,
                owner_confirmed=confirmed,
            )
    await service.approve(
        "project-employment",
        expected_revision=knowledge.candidate.revision,
        fact_ids=(fact().id,),
        owner_ref="owner",
        owner_confirmed=True,
    )
    evidence = await service.answer_evidence(
        "Explain your experience with PostgreSQL and Redis", "technical_experience"
    )
    assert evidence[0]["reference"]["source_type"] == "project_context"
    assert evidence[0]["facts"]["revision"] == knowledge.candidate.revision
    assert evidence[0]["facts"]["fact_ids"] == [fact().id]
    assert evidence[0]["facts"]["evidence"][0]["content_sha256"] == "b" * 64
    assert not await service.answer_evidence(
        "What APIs have you integrated?", "technical_experience"
    )
    assert not await service.answer_evidence(
        "What was your most challenging technical bug?", "technical_experience"
    )
    assert not await service.answer_evidence(
        "Describe a difficult engineering decision", "technical_experience"
    )
    assert not await service.answer_evidence(
        "Explain your experience with MongoDB and Redis", "technical_experience"
    )
    _, changed = await service.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(fact("I implemented a reviewed order workflow."),),
    )
    assert changed.candidate.revision != knowledge.candidate.revision
    assert not await service.approved_projects()
    with pytest.raises(ContextError, match="project_changed"):
        await service.approve(
            "project-employment",
            expected_revision=knowledge.candidate.revision,
            fact_ids=(fact().id,),
            owner_ref="owner",
            owner_confirmed=True,
        )


def test_repository_ownership_and_forged_provenance_never_prove_contribution():
    cfg = ProjectConfiguration(
        id="project-source",
        name="Fictional",
        priority=1,
        repository_url="https://github.com/fictional-owner/source",
    )
    source = RepositorySnapshot(
        repository_url=str(cfg.repository_url),
        commit_sha="a" * 40,
        files={"requirements.txt": "redis==1"},
    )
    for verification in ["direct", "inferred"]:
        f = make_fact(
            "contribution",
            "I implemented all caching.",
            verification,
            (
                EvidenceReference(
                    file="requirements.txt",
                    commit_sha="a" * 40,
                    content_sha256="b" * 64,
                ),
            ),
            personal_claim=True,
        )
        assert not f.approvable
    forged = make_fact(
        "architecture",
        "A supported cache.",
        "owner_supplied",
        (
            EvidenceReference(
                file="requirements.txt", commit_sha="a" * 40, content_sha256="b" * 64
            ),
        ),
    )
    with pytest.raises(ContextError, match="project_evidence_changed_reload"):
        extract_project(cfg, source, owner_facts=(forged,))


async def test_approved_observation_does_not_become_personal_answer(
    db_session, phase2_profile, phase2_settings
):
    # Clear separately approved legacy project facts for this fictional fixture.
    phase2_profile.projects = []
    await db_session.flush()
    profile_version = phase2_profile.version
    svc = await document_service(SQLRecordStore(db_session))
    observation = make_fact(
        "architecture",
        "The repository uses PostgreSQL and Redis.",
        "owner_supplied",
        fact().evidence,
    )
    _, k = await svc.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(observation,),
    )
    await svc.approve(
        "project-employment",
        expected_revision=k.candidate.revision,
        fact_ids=(observation.id,),
        owner_ref="owner",
        owner_confirmed=True,
    )
    result = await ApplicationAnswerService(db_session, phase2_settings).generate(
        GenerateRequest(question="Describe your best project.")
    )
    assert (
        result.status == "needs_input" and result.answer is None and not result.used_llm
    )
    personal = fact()
    _, k = await svc.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(observation, personal),
    )
    await svc.approve(
        "project-employment",
        expected_revision=k.candidate.revision,
        fact_ids=(personal.id,),
        owner_ref="owner",
        owner_confirmed=True,
    )
    service = ApplicationAnswerService(db_session, phase2_settings)
    result = await service.generate(
        GenerateRequest(question="Describe your best project.")
    )
    assert result.status == "draft_ready" and result.answer == personal.text
    assert result.evidence_references[0].source_type == "project_context"
    assert not result.used_llm and phase2_profile.version == profile_version
    for question in [
        "What was your most challenging technical bug?",
        "What APIs have you integrated?",
        "Describe a difficult engineering decision.",
    ]:
        result = await service.generate(GenerateRequest(question=question))
        assert (
            result.status == "needs_input"
            and result.answer is None
            and not result.used_llm
        )


@pytest.mark.parametrize("change", ["digest", "profile"])
async def test_stale_resume_review_is_rejected(
    async_client, db_session, phase2_auth, phase2_profile, monkeypatch, change
):
    monkeypatch.setenv("RESUME_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    uploaded = await async_client.post(
        "/api/v1/dashboard/resumes",
        headers={**phase2_auth, "Content-Type": "application/pdf"},
        content=pdf_bytes(),
    )
    resume = await db_session.get(PrivateResume, uploaded.json()["id"])
    response = await async_client.post(
        f"/api/v1/dashboard/resumes/{resume.id}/confirm",
        headers=phase2_auth,
        json={
            "owner_confirmed": True,
            "primary": True,
            "expected_sha256": "0" * 64 if change == "digest" else resume.sha256,
            "expected_profile_version": 2 if change == "profile" else 1,
        },
    )
    assert response.status_code == 409 and not resume.confirmed
    assert phase2_profile.version == 1


async def test_resume_and_project_approval_require_authentication(
    async_client, phase2_auth, phase2_profile
):
    from uuid import uuid4

    for path, body in [
        (f"/api/v1/dashboard/resumes/{uuid4()}/confirm", {"owner_confirmed": True}),
        (
            "/api/v1/dashboard/candidate-context/projects/project-01/approve",
            {
                "owner_confirmed": True,
                "expected_revision": "a" * 64,
                "fact_ids": ["b" * 64],
            },
        ),
    ]:
        response = await async_client.post(path, json=body)
        assert response.status_code == 401
        assert "no-store" in response.headers["cache-control"]


async def test_private_report_escapes_sources_and_never_submits(tmp_path):
    service = await document_service()
    _, k = await service.build(
        "project-employment", expected_configuration_revision=1, owner_facts=(fact(),)
    )
    requests = confirmation_requests(
        SimpleNamespace(id="fictional-profile", version=1),
        SimpleNamespace(id="fictional-resume", sha256="b" * 64),
        None,
        [k.candidate],
    )
    payload = {
        "profile_version": 1,
        "profile": {"name": "<img src=x onerror=alert(1)>"},
        "resume_status": "pending",
        "resume_sha256": "b" * 64,
        "resume_text": "</script><script>BAD()</script>",
        "differences": ["unknown dates"],
        "missing_information": ["personal bug"],
        "projects": [
            {
                "id": "project-employment",
                "name": "Fictional",
                "revision": k.candidate.revision,
                "commit_sha": None,
                "facts": [
                    {**f.model_dump(mode="json"), "approvable": f.approvable}
                    for f in k.candidate.facts
                ],
            }
        ],
        "requests": requests,
        "answer_checks": [],
    }
    path = write_private_review(tmp_path / "private", payload, pdf_bytes=pdf_bytes())
    html = path.read_text()
    assert "<script>BAD()" not in html and "<img src=x" not in html
    assert "connect-src 'none'" in html and "fetch(" not in html
    assert " checked" not in html and "data:application/pdf;base64," in html
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    saved = json.loads((path.parent / "review-manifest.private.json").read_text())
    assert saved["requests"]["review_hash"] == saved["review_hash"]
    with pytest.raises(FileExistsError):
        write_private_review(path.parent, payload, pdf_bytes=pdf_bytes())
    repository = tmp_path / "tracked"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: somewhere")
    with pytest.raises(ValueError, match="outside_repository"):
        write_private_review(repository / "report", payload, pdf_bytes=pdf_bytes())


def test_owner_selections_are_exact_and_cannot_add_unreviewed_facts():
    from copy import deepcopy

    from backend.app.candidate_context.common import canonical_hash
    from backend.app.candidate_context.review import selected_requests

    request = {
        "method": "POST",
        "path": "/projects/project-01/approve",
        "body": {
            "expected_revision": "c" * 64,
            "fact_ids": ["a" * 64, "b" * 64],
            "owner_confirmed": True,
        },
    }
    manifest = {
        "profile_version": 1,
        "requests": {
            "profile_id": "fixture",
            "profile_version": 1,
            "resume": {
                "path": "/resumes/fixture/confirm",
                "method": "POST",
                "body": {"owner_confirmed": True},
            },
            "projects": [request],
        },
    }
    manifest["review_hash"] = canonical_hash(manifest)
    manifest["requests"]["review_hash"] = manifest["review_hash"]
    selection = {
        "profile_id": "fixture",
        "profile_version": 1,
        "review_hash": manifest["review_hash"],
        "requests": [deepcopy(request)],
    }
    selection["requests"][0]["body"]["fact_ids"] = ["a" * 64]
    assert selected_requests(manifest, selection) == selection["requests"]
    for change in ["fact", "revision", "owner", "hash", "duplicate"]:
        bad = deepcopy(selection)
        if change == "fact":
            bad["requests"][0]["body"]["fact_ids"] = ["d" * 64]
        if change == "revision":
            bad["requests"][0]["body"]["expected_revision"] = "d" * 64
        if change == "owner":
            bad["requests"][0]["body"]["owner_confirmed"] = "true"
        if change == "hash":
            bad["review_hash"] = "0" * 64
        if change == "duplicate":
            bad["requests"] *= 2
        with pytest.raises(ValueError):
            selected_requests(manifest, bad)
    bad = deepcopy(manifest)
    bad["profile_version"] = 2
    with pytest.raises(ValueError, match="review_changed"):
        selected_requests(bad, selection)


async def test_api_facts_need_personal_confirmation_and_are_used_without_models(
    db_session, phase2_profile, phase2_settings
):
    phase2_profile.projects = []
    await db_session.flush()
    service = await document_service(SQLRecordStore(db_session))
    contribution = fact()
    api = fact("I integrated payment APIs with signature verification.", "api")
    _, k = await service.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(contribution, api),
    )
    await service.approve(
        "project-employment",
        expected_revision=k.candidate.revision,
        fact_ids=(contribution.id, api.id),
        owner_ref="owner",
        owner_confirmed=True,
    )
    for question in [
        "What APIs have you integrated?",
        "Explain your experience with PostgreSQL and Redis.",
    ]:
        result = await ApplicationAnswerService(db_session, phase2_settings).generate(
            GenerateRequest(question=question)
        )
        assert result.status == "draft_ready" and not result.used_llm
        assert result.evidence_references[0].source_type == "project_context"
    assert await SQLRecordStore(db_session).read("candidate_project-employment") is None
    assert (
        await SQLRecordStore(db_session).read("document_project-employment") is not None
    )


def test_named_unattributed_project_cannot_use_another_projects_contribution():
    from backend.app.services.candidate_evidence_retrieval import retrieve

    profile = SimpleNamespace(
        id="fixture",
        verified_roles=[],
        verified_skills=[],
        projects=[
            {"name": "Fictional Search", "purpose": "Search", "contribution": None},
            {
                "name": "Fictional Inventory",
                "purpose": "Inventory",
                "contribution": "I developed inventory APIs.",
            },
        ],
    )
    assert (
        retrieve(
            profile,
            [],
            "Describe your contribution to Fictional Search",
            "project_explanation",
        )
        == []
    )


async def test_reviewed_record_revision_cannot_overwrite_newer_project_proposal():
    service = await document_service()
    _, first = await service.build(
        "project-employment", expected_configuration_revision=1, owner_facts=(fact(),)
    )
    _, second = await service.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(fact("I developed corrected inventory APIs."),),
    )
    with pytest.raises(ContextError, match="project_changed_rebuild_and_review"):
        await service.build(
            "project-employment",
            expected_configuration_revision=1,
            expected_project_revision=first.revision,
            owner_facts=(fact(),),
        )
    assert (
        await service.project("project-employment")
    ).candidate.revision == second.candidate.revision


async def test_selected_review_replays_services_atomically_without_retyping(
    tmp_path, monkeypatch, db_session, phase2_profile, capsys
):
    import copy
    import importlib.util
    from pathlib import Path

    import httpx
    from sqlalchemy import select

    from backend.app.candidate_context.common import canonical_hash
    from backend.app.core import config
    from backend.app.core.config import Settings
    from backend.app.db import session as session_module
    from backend.app.models.application_answer import CandidateResource
    from backend.app.services.candidate_profile_service import CandidateProfileService

    key = Fernet.generate_key()
    monkeypatch.setenv("RESUME_ENCRYPTION_KEY", key.decode())
    get_settings.cache_clear()
    settings = Settings(
        _env_file=None,
        DB_REMOTE_ONLY=True,
        DB_REQUIRE_TLS=True,
        JOB_AGENT_API_TOKEN="fictional-owner-token",
    )
    monkeypatch.setattr(config, "Settings", lambda **kwargs: settings)
    monkeypatch.setattr(config, "configure_operator", lambda settings: None)

    async def keep_fixture_engine():
        pass

    monkeypatch.setattr(session_module, "close_db_engine", keep_fixture_engine)
    original_client = httpx.AsyncClient
    authenticated_profile = {
        "id": str(phase2_profile.id),
        "version": phase2_profile.version,
    }

    def client(**kwargs):
        return original_client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        **authenticated_profile,
                    },
                )
            ),
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    raw = pdf_bytes("Alex Fictional")
    resume = PrivateResume(
        label="Fictional.pdf",
        ciphertext=Fernet(key).encrypt(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    db_session.add(resume)
    await db_session.commit()
    staged = await document_service()
    personal, unselected = (
        fact(),
        make_fact(
            "feature", "A fictional pending feature.", "owner_supplied", fact().evidence
        ),
    )
    _, knowledge = await staged.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(personal, unselected),
    )
    configuration = (await staged.configuration()).configuration
    profile = await CandidateProfileService(db_session).get_profile()
    plan = {
        "profile_version": 1,
        "resume_id": str(resume.id),
        "resume_sha256": resume.sha256,
        "configuration": configuration.model_dump(mode="json"),
        "checkouts": {},
        "source_paths": {},
        "facts": {
            "project-employment": [
                personal.model_dump(mode="json"),
                unselected.model_dump(mode="json"),
            ]
        },
    }
    manifest = {
        "profile_version": 1,
        "requests": confirmation_requests(profile, resume, None, [knowledge.candidate]),
        "staging": {
            "plan_hash": canonical_hash(plan),
            "profile_hash": canonical_hash(profile.model_dump(mode="json")),
            "configuration_revision": 0,
            "project_record_revisions": {"project-employment": 0},
        },
    }
    manifest["review_hash"] = canonical_hash(manifest)
    manifest["requests"]["review_hash"] = manifest["review_hash"]
    selection = {
        "profile_id": str(profile.id),
        "profile_version": 1,
        "review_hash": manifest["review_hash"],
        "requests": [
            copy.deepcopy(manifest["requests"]["resume"]),
            copy.deepcopy(manifest["requests"]["projects"][0]),
        ],
    }
    selection["requests"][1]["body"]["fact_ids"] = [personal.id]
    files = [
        tmp_path / name for name in ["plan.json", "manifest.json", "selection.json"]
    ]
    for path, value in zip(files, [plan, manifest, selection]):
        path.write_text(json.dumps(value))
    script = Path(__file__).resolve().parents[1] / "scripts/apply_onboarding_review.py"
    spec = importlib.util.spec_from_file_location("apply_review_fixture", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    await module.apply(tmp_path / "unused.env", *files)
    live = CandidateContextService(SQLRecordStore(db_session))
    result = await live.project("project-employment")
    assert result.approved.fact_ids == (personal.id,)
    assert not any(f.id == unselected.id for f in result.approved.facts)
    resources = list((await db_session.scalars(select(CandidateResource))).all())
    assert (
        len(resources) == 1 and resources[0].is_primary and resources[0].user_confirmed
    )
    assert (await CandidateProfileService(db_session).get_profile()).version == 1
    await db_session.rollback()
    await module.apply(tmp_path / "unused.env", *files)  # Exact retry is safe.
    await live.build(
        "project-employment",
        expected_configuration_revision=1,
        owner_facts=(fact("I implemented a corrected private workflow."),),
    )
    await db_session.commit()
    with pytest.raises(ValueError, match="project_changed_rebuild_and_review"):
        await module.apply(tmp_path / "unused.env", *files)
    assert (await live.project("project-employment")).candidate.facts[
        0
    ].text == "I implemented a corrected private workflow."
    assert "Alex Fictional" not in capsys.readouterr().out
    get_settings.cache_clear()
