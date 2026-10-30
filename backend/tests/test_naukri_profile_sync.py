"""Fictional verified-profile reconciliation; no portal changes or PII fixtures."""

from uuid import uuid4

import pytest

from backend.app.agent.tools import ToolDenied
from backend.app.execution import application_queue as queue
from backend.app.execution import profile_sync as sync
from backend.app.execution.queue_contracts import NaukriWorkReport, QueueControl
from backend.tests.test_naukri_background_queue import setup
from backend.tests.test_naukri_submission import admit, call, claim
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


@pytest.mark.parametrize("canonical,observed,approved,state,update", [
    ("verified", "verified", [], "MATCHED", False),
    ("verified", "old", [], "CONFLICT", False),
    ("verified", "old", ["summary"], "OUTDATED", True),
    ("verified", "", ["summary"], "MISSING_FROM_PLATFORM", True),
    (None, "genuine portal information", ["summary"], "MISSING_FROM_DATABASE", False),
    (None, None, ["summary"], "MATCHED", False),
])
def test_scoped_sync_never_invents_or_clears_facts(canonical, observed, approved, state, update):
    summary = sync.compare({"summary": canonical}, {"summary": observed}, approved)[3]
    assert summary["field"] == "summary" and summary["state"] == state
    assert summary["may_update"] is update
    assert canonical not in str(summary) if canonical else True


def test_unsupported_fields_and_salary_preferences_cannot_be_written():
    result = sync.compare({"email": "new@example.com", "skills": ["Python"]}, {"email": "old@example.com"}, ["email", "skills"])
    email = next(x for x in result if x["field"] == "email")
    skills = next(x for x in result if x["field"] == "skills")
    assert not email["may_update"] and not email["update_supported"]
    assert skills["state"] == "UNSUPPORTED" and not skills["may_update"]


async def test_unconfirmed_or_changed_profile_cannot_enable_sync(db_session, phase2_profile):
    with pytest.raises(ToolDenied, match="current_confirmed_profile_version_required"):
        await sync.configure(db_session, sync.SyncPolicyUpdate(expected_revision=0,
            policy=sync.SyncPolicy(enabled=True, auto_profile_sync=True, profile_version=phase2_profile.version, approved_fields=["summary"])))


async def enable(session, case, auto=True):
    context = await setup(session)
    from backend.app.execution.recurring import context as career_context

    profile, confirmed, _ = await career_context(session)
    assert confirmed
    profile.summary = "Verified fictional summary"
    await session.flush()
    from backend.app.local_agent.profile_confirmation import confirm_profile
    await confirm_profile(session, profile, profile.version)
    await sync.configure(session, sync.SyncPolicyUpdate(expected_revision=0,
        policy=sync.SyncPolicy(enabled=True, auto_profile_sync=auto, profile_version=profile.version, approved_fields=["summary"])))
    await session.commit()
    return context, profile


def report(work, state, **extra):
    return {"kind": "execution_observation", "observed_url": work["target_url"],
            "execution": {"state": state, "document_id": str(uuid4()), "evidence_sha256": "a" * 64,
                          "account_sha256": work["execution"]["expected_account_sha256"], **extra}}


async def test_profile_save_requires_scope_then_independent_reload_to_verify(db_session, upload_case):
    case = upload_case
    context, profile = await enable(db_session, case)
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    assert work["operation"] == "inspect_profile_sync"
    observed = report(work, "PROFILE_OBSERVED", profile_fields={"summary": "Outdated fictional summary"})
    finished = await call(db_session, case, context, "finish_naukri_work", work, work_report=observed)
    assert finished.ok and finished.data["continue"]
    work = await admit(db_session, case, context, finished.data["work"])
    assert work["operation"] == "sync_profile" and work["execution"]["approved_summary"] == profile.summary
    saved = await call(db_session, case, context, "finish_naukri_work", work, work_report=report(work, "PROFILE_SAVE_ATTEMPTED"))
    assert saved.ok and saved.data["continue"]
    work = await admit(db_session, case, context, saved.data["work"])
    observed = report(work, "PROFILE_OBSERVED", profile_fields={"summary": profile.summary})
    result = await call(db_session, case, context, "finish_naukri_work", work, work_report=observed)
    assert result.ok and not result.data["continue"]
    status = await sync.status(db_session)
    assert status["latest"]["outcome"] == "SYNC_VERIFIED"
    assert profile.summary not in str(status)  # Audit is reference-only.


async def test_compare_only_profile_scope_never_grants_save(db_session, upload_case):
    case = upload_case
    context, profile = await enable(db_session, case, auto=False)
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    result = await call(db_session, case, context, "finish_naukri_work", work,
                        work_report=report(work, "PROFILE_OBSERVED", profile_fields={"summary": "old"}))
    assert result.ok and not result.data["continue"]
    assert (await sync.status(db_session))["latest"]["outcome"] == "COMPARED"


async def test_stop_revokes_profile_save_and_retains_uncertain_attempt(db_session, upload_case):
    case = upload_case
    context, _ = await enable(db_session, case)
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    prepared = await call(db_session, case, context, "finish_naukri_work", work,
                         work_report=report(work, "PROFILE_OBSERVED", profile_fields={"summary": "old"}))
    work = prepared.data["work"]
    current = await queue.configuration(db_session)
    await queue.control(db_session, QueueControl(action="stop", expected_revision=current["revision"]))
    await db_session.commit()
    result = await call(db_session, case, context, "admit_naukri_work", work)
    assert not result.ok


def test_report_rejects_arbitrary_profile_payloads():
    with pytest.raises(ValueError, match="bounded_supported_profile_fields"):
        NaukriWorkReport.model_validate({"kind": "execution_observation", "execution": {
            "state": "PROFILE_OBSERVED", "document_id": str(uuid4()), "evidence_sha256": "a" * 64,
            "account_sha256": "b" * 64, "profile_fields": {"password": "do not retain"}}})
