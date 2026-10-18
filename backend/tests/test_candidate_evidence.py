import pytest
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.schemas.candidate_resources import EvidenceWrite, EvidencePatch
from backend.app.services.candidate_evidence_retrieval import retrieve
from backend.tests.phase2a_fakes import PROJECT


@pytest.mark.asyncio
async def test_evidence_confirmation_and_correction(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    item = await repo.add_evidence(EvidenceWrite(evidence_type="resume_note", title="Reviewed notes", content="I implemented backend authentication."))
    assert not item.user_confirmed
    assert not await repo.evidence(phase2_profile.id, confirmed_only=True)
    await repo.patch_evidence(item.id, EvidencePatch(user_confirmed=True))
    assert len(await repo.evidence(phase2_profile.id, confirmed_only=True)) == 1
    await repo.patch_evidence(item.id, EvidencePatch(content="I implemented a task API."))
    assert not item.user_confirmed
    await db_session.commit()
    assert (await repo.evidence(phase2_profile.id))[0].content == "I implemented a task API."


@pytest.mark.asyncio
async def test_project_evidence_retrieval(db_session, phase2_profile):
    repo = CandidateKnowledgeRepository(db_session)
    item = await repo.add_evidence(EvidenceWrite(evidence_type="project", title="Relay", content="User supplied project notes", project=PROJECT, user_confirmed=True))
    selected = retrieve(phase2_profile, [item], "Describe your challenging project", "project_explanation")
    assert {f["reference"]["source_type"] for f in selected} == {"candidate_evidence", "verified_project"}
    phase2_profile.projects = [{"name": "Unattributed", "technologies": ["Python"]}]
    item.user_confirmed = False
    assert retrieve(phase2_profile, [item], "Best project", "project_explanation") == []


@pytest.mark.asyncio
async def test_unknown_evidence_id_and_rollback(db_session, phase2_profile):
    from uuid import uuid4
    repo = CandidateKnowledgeRepository(db_session)
    with pytest.raises(ProfileNotFoundError):
        await repo.patch_evidence(uuid4(), EvidencePatch(user_confirmed=True))
    await repo.add_evidence(EvidenceWrite(evidence_type="other", title="Notes", content="Factual note"))
    profile_id = phase2_profile.id
    await db_session.rollback()
    assert not await repo.evidence(profile_id)


def test_evidence_project_url_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EvidenceWrite(evidence_type="project", title="Untrusted", content="Notes", project={**PROJECT, "url": "https://127.0.0.1/admin"})
