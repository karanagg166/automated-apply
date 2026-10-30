"""Fresh project fingerprints use one coherent query without approval caching."""
import pytest
from sqlalchemy import event

from backend.app.agent.tools import ToolDenied, approved_projects
from backend.app.browser.service import _ProjectStampRecords, project_stamp
from backend.app.candidate_context.configuration import ProjectConfiguration
from backend.app.candidate_context.persistence import MemoryRecordStore
from backend.app.candidate_context.service import (
    CONFIGURATION_KEY,
    CandidateContextService,
)
from backend.app.dashboard.models import OwnerPreference
from backend.app.services.applications.resume_selector import digest
from backend.tests.test_candidate_context_projects import (
    FictionalReader,
    build_approve,
    configure,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 3, 8])
async def test_fingerprint_matches_existing_approval_rules_in_one_query(db_session, count):
    memory = MemoryRecordStore()
    service = CandidateContextService(memory, reader=FictionalReader())
    projects = tuple(ProjectConfiguration(id=f"project-{i:02d}", name=f"Fictional {i}",
                        priority=i, repository_url="https://github.com/fictional-owner/fictional-project")
                     for i in range(1, count + 1))
    await configure(service, projects=projects)
    for project in projects:
        await build_approve(service, project.id)
    for key, value in memory._values.items():
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()
    _, expected = await approved_projects(db_session)
    queries = []
    def observed(*args):
        queries.append(1)
    engine = db_session.bind.sync_engine
    event.listen(engine, "after_cursor_execute", observed)
    try:
        assert await project_stamp(db_session) == digest(expected)
        assert len(queries) == 1
    finally:
        event.remove(engine, "after_cursor_execute", observed)


@pytest.mark.asyncio
async def test_fingerprint_refetches_configuration_priority_and_draft_invalidation(db_session):
    memory = MemoryRecordStore()
    reader = FictionalReader()
    service = CandidateContextService(memory, reader=reader)
    await configure(service)
    await build_approve(service)
    for key, value in memory._values.items():
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()
    first = await project_stamp(db_session)
    # Direct current records change without ORM identity-map refresh: each call must see fresh data.
    configuration = await db_session.get(OwnerPreference, CONFIGURATION_KEY)
    changed = dict(configuration.value)
    changed["configuration"] = {**changed["configuration"], "projects": [
        {**changed["configuration"]["projects"][0], "priority": 2}
    ]}
    configuration.value = changed
    await db_session.commit()
    second = await project_stamp(db_session)
    _, expected = await approved_projects(db_session)
    assert second != first and second == digest(expected)
    assert second == digest([])  # Configuration no longer matches the approved candidate.


@pytest.mark.asyncio
async def test_snapshot_record_adapter_is_read_only_and_returns_copies():
    values = {"candidate_configuration_v1": {"revision": 1, "nested": {"value": 1}}}
    records = _ProjectStampRecords(values)
    result = await records.read("candidate_configuration_v1")
    result["nested"]["value"] = 2
    assert values["candidate_configuration_v1"]["nested"]["value"] == 1
    with pytest.raises(ToolDenied, match="project_stamp_read_only"):
        await records.compare_and_swap("candidate_configuration_v1", 1, {})


@pytest.mark.asyncio
async def test_document_project_and_pending_revision_keep_exact_approval_semantics(db_session):
    from backend.app.candidate_context.service import project_key
    from backend.tests.test_candidate_context_projects import owner_claim

    memory = MemoryRecordStore()
    service = CandidateContextService(memory, reader=FictionalReader())
    await configure(service, projects=(ProjectConfiguration(
        id="project-01", name="Fictional owner document", priority=1,
    ),))
    await build_approve(service, owner_facts=(owner_claim(),))
    for key, value in memory._values.items():
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()
    _, expected = await approved_projects(db_session)
    assert expected and await project_stamp(db_session) == digest(expected)
    row = await db_session.get(OwnerPreference, project_key("project-01", document=True))
    revision = row.value["candidate"]["revision"]
    changed_revision = ("a" if revision[0] != "a" else "b") + revision[1:]
    row.value = {**row.value, "candidate": {**row.value["candidate"],
                 "revision": changed_revision}}
    await db_session.commit()
    _, pending = await approved_projects(db_session)
    assert pending == [] and await project_stamp(db_session) == digest([])
