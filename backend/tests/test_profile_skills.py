"""Preserving add-only edits and durable, non-replayable provider Save intent."""
from uuid import uuid4

import pytest

from backend.app.agent.tools import ToolDenied
from backend.app.execution import profile_skills as skills
from backend.app.execution import profile_sync as sync
from backend.app.execution.recurring import context as profile_context
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.tests.test_naukri_profile_sync import enable, report
from backend.tests.test_naukri_submission import admit, call, claim
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


def test_only_equivalent_published_spellings_prevent_duplicate_additions():
    assert skills.additions(["React", "PostgreSQL", "FastAPI", "RAG"], ["React.js", "Postgres", "Existing skill"]) == ["FastAPI", "RAG"]
    assert skills.additions(["FastAPI"], []) == ["FastAPI"]
    assert skills.prepared(["Python", "Existing skill"], ["FastAPI", "RAG"], ["Python", "Existing skill", "FastAPI"]) == ["Python", "Existing skill", "FastAPI"]


@pytest.mark.parametrize("final", [
    ["Python", "FastAPI"], ["Existing skill", "Python", "FastAPI"],
    ["Python", "Existing skill"], ["Python", "Existing skill", "Rust"],
    ["Python", "Existing skill", "FastAPI", "Fast API"],
    ["Python", "Existing skill", {"not": "a skill"}],
])
def test_preparation_cannot_remove_reorder_invent_or_duplicate_skills(final):
    with pytest.raises(ToolDenied):
        skills.prepared(["Python", "Existing skill"], ["FastAPI", "RAG"], final)


async def prepare(session, case):
    context, profile = await enable(session, case, auto=False)
    profile.verified_skills = ["Python", "FastAPI", "RAG"]
    await session.flush()
    await confirm_profile(session, profile, profile.version)
    config = await sync.configuration(session)
    await sync.configure(session, sync.SyncPolicyUpdate(expected_revision=config["revision"],
        policy=sync.SyncPolicy(enabled=True, auto_profile_sync=True, profile_version=profile.version, approved_fields=["skills"])))
    await session.commit()
    work = await admit(session, case, context, await claim(session, case, context))
    observed = report(work, "PROFILE_OBSERVED", profile_fields={"skills": ["Python", "Existing skill"]})
    result = await call(session, case, context, "finish_naukri_work", work, work_report=observed)
    assert result.ok and result.data["continue"]
    work = await admit(session, case, context, result.data["work"])
    assert work["execution"]["sync_phase"] == "prepare"
    assert work["execution"]["skills_additions"] == ["FastAPI", "RAG"]
    assert not (await sync.status(session))["latest"].get("attempt")
    assert work["execution"].get("permit_expires_at") is None
    return context, profile, work, observed["execution"]["document_id"]


async def prepared(session, case, context, work, document_id, final=None):
    observed = report(work, "PROFILE_SKILLS_PREPARED", profile_fields={"skills": final or ["Python", "Existing skill", "FastAPI"]})
    observed["execution"]["document_id"] = document_id
    return await call(session, case, context, "finish_naukri_work", work, work_report=observed)


async def test_partial_capacity_addition_has_separate_save_intent_and_independent_exact_verification(db_session, upload_case):
    case = upload_case
    context, profile, work, doc = await prepare(db_session, case)
    ready = await prepared(db_session, case, context, work, doc)
    assert ready.ok and ready.data["continue"] and ready.data["work"]["execution"]["sync_phase"] == "save"
    assert not (await sync.status(db_session))["latest"].get("attempt")
    work = await admit(db_session, case, context, ready.data["work"])
    latest = (await sync.status(db_session))["latest"]
    assert latest["outcome"] == "SYNC_ADMITTED_OUTCOME_UNKNOWN" and latest["attempt"]["field"] == "skills"
    assert all(text not in str(latest) for text in ["Python", "Existing skill", "FastAPI"])
    saved = await call(db_session, case, context, "finish_naukri_work", work, work_report=report(work, "PROFILE_SAVE_ATTEMPTED"))
    assert saved.ok and saved.data["continue"]
    work = await admit(db_session, case, context, saved.data["work"])
    observed = report(work, "PROFILE_OBSERVED", profile_fields={"skills": ["Existing skill", "Python", "FastAPI"]})
    verified = await call(db_session, case, context, "finish_naukri_work", work, work_report=observed)
    assert verified.ok and not verified.data["continue"]
    latest = (await sync.status(db_session))["latest"]
    assert latest["outcome"] == "SYNC_VERIFIED"
    assert next(x for x in latest["decisions"] if x["field"] == "skills")["state"] != "MATCHED"
    assert (await profile_context(db_session))[0].verified_skills == profile.verified_skills


@pytest.mark.parametrize("fault", ["removed", "unapproved", "document", "canonical", "same_reload", "lost_save"])
async def test_skills_context_or_uncertain_save_never_becomes_another_save(db_session, upload_case, fault):
    case = upload_case
    context, profile, work, doc = await prepare(db_session, case)
    if fault in {"removed", "unapproved", "document", "canonical"}:
        if fault == "canonical":
            profile.verified_skills = [*profile.verified_skills, "SQL"]
            await db_session.flush()
        final = ["Python", "FastAPI"] if fault == "removed" else ["Python", "Existing skill", "Rust"] if fault == "unapproved" else None
        result = await prepared(db_session, case, context, work, str(uuid4()) if fault == "document" else doc, final)
        assert not result.ok
        assert (await sync.status(db_session))["latest"]["outcome"] == "COMPARED"
        return
    ready = await prepared(db_session, case, context, work, doc)
    work = await admit(db_session, case, context, ready.data["work"])
    if fault == "lost_save":
        result = await call(db_session, case, context, "abandon_naukri_work", work, work_report={"kind": "failed", "reason": "response_lost"})
        assert result.ok and not result.data["continue"]
        assert (await sync.status(db_session))["latest"]["outcome"] == "SYNC_UNCONFIRMED_NO_RETRY"
        replay = await call(db_session, case, context, "admit_naukri_work", result.data["work"])
        assert not replay.ok
    else:
        saved = await call(db_session, case, context, "finish_naukri_work", work, work_report=report(work, "PROFILE_SAVE_ATTEMPTED"))
        work = await admit(db_session, case, context, saved.data["work"])
        observed = report(work, "PROFILE_OBSERVED", profile_fields={"skills": ["Python", "Existing skill", "FastAPI"]})
        observed["execution"]["document_id"] = doc
        result = await call(db_session, case, context, "finish_naukri_work", work, work_report=observed)
        assert not result.ok and result.error_code == "independent_profile_reload_required"


def test_native_framed_prepared_skills_report_preserves_the_new_state():
    import io
    import json
    import struct

    from backend.app.local_agent.native_host import read_message

    value = {"version": 1, "request_id": str(uuid4()), "command": "finish_naukri_work",
             "work_report": {"kind": "execution_observation", "observed_url": "https://www.naukri.com/mnjuser/profile",
                             "execution": {"state": "PROFILE_SKILLS_PREPARED", "document_id": "fictional-document-123456",
                                           "account_sha256": "a" * 64, "evidence_sha256": "b" * 64,
                                           "profile_fields": {"skills": ["Python", "FastAPI"]}}}}
    payload = json.dumps(value).encode()
    command = read_message(io.BytesIO(struct.pack("<I", len(payload)) + payload))
    assert command.work_report.execution.state == "PROFILE_SKILLS_PREPARED"
    assert command.work_report.execution.profile_fields == {"skills": ["Python", "FastAPI"]}
