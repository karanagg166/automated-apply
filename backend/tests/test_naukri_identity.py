"""Fictional aliases and durable owner approval; never use contact email as login."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import naukri_identity as identity
from backend.app.execution.queue_preparation import prepare_one
from backend.tests.test_naukri_background_queue import setup
from backend.tests.test_naukri_submission import ready
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def test_alias_binding_survives_new_connection_without_modifying_contact(db_session, phase2_profile):
    email = phase2_profile.email
    context = await setup(db_session)
    binding = await identity.require(db_session, phase2_profile.id, context["profile_binding_id"])
    assert binding["account_sha256"] != __import__("hashlib").sha256(email.strip().casefold().encode()).hexdigest()
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as restarted:
        assert (await identity.require(restarted, phase2_profile.id))["revision"] == 1
    assert phase2_profile.email == email and email not in str(binding)


async def test_missing_owner_approval_never_falls_back_to_contact_email(db_session, phase2_profile):
    with pytest.raises(ToolDenied, match="approved_naukri_account_binding_required"):
        await identity.require(db_session, phase2_profile.id)


@pytest.mark.parametrize("change", ["candidate", "chrome", "revision", "account"])
async def test_stale_or_wrong_binding_cannot_admit_work(db_session, phase2_profile, change):
    context = await setup(db_session)
    binding = await identity.require(db_session, phase2_profile.id)
    value = {"candidate_profile_id": str(phase2_profile.id), "binding": {"profile_binding_id": context["profile_binding_id"]},
             "account_sha256": binding["account_sha256"], "account_binding_revision": binding["revision"]}
    if change == "candidate":
        value["candidate_profile_id"] = str(uuid4())
    elif change == "chrome":
        value["binding"]["profile_binding_id"] = str(uuid4())
    elif change == "revision":
        value["account_binding_revision"] += 1
    else:
        value["account_sha256"] = "0" * 64
    with pytest.raises(ToolDenied, match="naukri_account_binding"):
        await identity.check_work(db_session, value)


async def test_real_preparation_uses_approved_alias(db_session, upload_case):
    _, item, _ = await ready(db_session, upload_case)
    from backend.app.execution.application_queue import load

    prepared = (await load(db_session, item["id"])).value
    assert prepared["account_sha256"] == (await identity.require(db_session))["account_sha256"]
    assert prepared["account_binding_revision"] == 1


async def test_preparation_without_binding_waits_for_owner(db_session, upload_case):
    _, item, _ = await ready(db_session, upload_case)
    row = await db_session.get(OwnerPreference, identity.KEY)
    await db_session.delete(row)
    from backend.app.execution.application_queue import load

    work = await load(db_session, item["id"])
    work.value = {**work.value, "operation": "prepare", "stage": "MATCHED", "status": "queued"}
    await db_session.commit()
    assert await prepare_one(db_session, upload_case.settings)
    value = (await load(db_session, item["id"])).value
    assert value["stage"] == "NEEDS_INPUT" and value["reason"] == "approved_naukri_account_binding_required"


@pytest.mark.parametrize("change,reason", [("revision", "account_binding_revision_conflict"), ("approval", "owner_account_confirmation_required"), ("profile", "account_binding_context_changed")])
async def test_binding_updates_require_explicit_current_owner_context(db_session, phase2_profile, change, reason):
    context = await setup(db_session)
    data = identity.AccountApproval(expected_revision=1, candidate_profile_id=phase2_profile.id,
        profile_binding_id=context["profile_binding_id"], account_sha256="b" * 64, evidence_sha256="a" * 64, owner_confirmed=True)
    if change == "revision":
        data.expected_revision = 0
    elif change == "approval":
        data.owner_confirmed = False
    else:
        data.profile_binding_id = uuid4()
    with pytest.raises(ToolDenied, match=reason):
        await identity.approve(db_session, data)
    assert (await identity.require(db_session))["revision"] == 1
