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
    (None, None, ["summary"], "MISSING_INFORMATION", False),
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
    assert "verify_saved_resume" not in (await sync.configuration(db_session))["policy"]
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    result = await call(db_session, case, context, "finish_naukri_work", work,
                        work_report=report(work, "PROFILE_OBSERVED", profile_fields={"summary": "old"}))
    assert result.ok and not result.data["continue"]
    assert (await sync.status(db_session))["latest"]["outcome"] == "COMPARED"


@pytest.mark.parametrize("change", [None, "checksum", "byte_count", "missing", "canonical_changed"])
async def test_read_only_saved_resume_requires_actual_pdf_bytes_and_current_canonical(db_session, upload_case, change):
    import hashlib

    from cryptography.fernet import Fernet

    case = upload_case
    context, profile = await enable(db_session, case, auto=False)
    config = await sync.configuration(db_session)
    await sync.configure(db_session, sync.SyncPolicyUpdate(expected_revision=config["revision"],
        policy=sync.SyncPolicy(enabled=True, profile_version=profile.version, verify_saved_resume=True)))
    await db_session.commit()
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    assert work["operation"] == "inspect_profile_sync"
    assert work["execution"]["verify_saved_resume"] is True
    assert work["execution"]["expected_resume_sha256"] == case.private.sha256
    fields = {"resume_sha256": case.private.sha256, "resume_bytes": len(case.raw)}
    if change == "checksum":
        fields["resume_sha256"] = "0" * 64
    elif change == "byte_count":
        fields["resume_bytes"] += 1
    elif change == "missing":
        fields = {}
    elif change == "canonical_changed":
        raw = b"%PDF-1.4\nChanged fictional canonical\n%%EOF"
        case.private.ciphertext = Fernet(case.key).encrypt(raw)
        case.private.sha256 = hashlib.sha256(raw).hexdigest()
        await db_session.commit()
    result = await call(db_session, case, context, "finish_naukri_work", work,
                        work_report=report(work, "PROFILE_OBSERVED", **fields))
    if change:
        expected = "profile_sync_canonical_resume_changed" if change == "canonical_changed" else "provider_saved_resume_differs_from_canonical_pdf"
        assert not result.ok and result.error_code == expected
        assert (await sync.status(db_session))["latest"] is None
    else:
        assert result.ok and not result.data["continue"]
        latest = (await sync.status(db_session))["latest"]
        assert latest["outcome"] == "COMPARED"
        assert latest["resume_verification"]["state"] == "MATCHED_PDF_BYTES"
        assert latest["resume_verification"]["byte_count"] == len(case.raw)
        assert next(v for v in latest["decisions"] if v["field"] == "resume")["state"] == "MATCHED"
        assert case.private.sha256 not in str(latest) and "ciphertext" not in str(latest)


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


async def test_profile_gap_notices_deduplicate_and_keep_email_binding_separate(db_session):
    from sqlalchemy import select

    from backend.app.dashboard.models import Notification, NotificationDelivery

    desired = {"summary": "Verified fictional summary", "skills": ["Python"],
               "email": "contact@example.test", "education": [], "phone": None}
    observed = {"summary": "", "skills": ["Python"], "email": "platform@example.test",
                "education": [], "phone": "fictional private phone"}
    decisions = sync.compare(desired, observed)
    await sync.notify_missing_facts(db_session, decisions)
    await sync.notify_missing_facts(db_session, decisions)
    notices = list((await db_session.scalars(select(Notification))).all())
    assert len(notices) == 3
    assert all(n.href == "/profile" and n.kind == "profile_information_required" for n in notices)
    text = str([(n.dedup_key, n.body) for n in notices])
    assert all(raw not in text for raw in [desired["summary"], desired["email"], observed["email"], observed["phone"]])
    assert "Review email" not in text and "Review skills" not in text
    assert len((await db_session.scalars(select(NotificationDelivery))).all()) == 3
    observed["summary"] = "Different fictional portal summary"
    await sync.notify_missing_facts(db_session, sync.compare(desired, observed))
    assert len((await db_session.scalars(select(Notification))).all()) == 4


@pytest.mark.parametrize("automatic", [False, True])
async def test_read_only_poll_follows_confirmed_version_but_write_scope_stays_pinned(db_session, upload_case, automatic):
    context, profile = await enable(db_session, upload_case, auto=automatic)
    from backend.app.local_agent.profile_confirmation import confirm_profile

    profile.version += 1
    await db_session.flush()
    await confirm_profile(db_session, profile, profile.version)
    config = await queue.configuration(db_session)
    work = await sync.work(db_session, config, {"profile_binding_id": str(context["profile_binding_id"])})
    if automatic:
        assert work is None
    else:
        assert work["profile_version"] == profile.version
        assert work["operation"] == "inspect_profile_sync"
        assert "approved_summary" not in work
        policy = sync.SyncPolicy.model_validate((await sync.configuration(db_session))["policy"])
        assert policy.interval_seconds == 1800
        assert policy.profile_version != profile.version
