"""First receipt prerequisite over the real queue/native code and fake pages.

These tests never visit a provider or count as live submission acceptance.
"""

import pytest
from sqlalchemy import func, select

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.naukri_automatic import require_first_receipt
from backend.app.execution.queue_contracts import (
    QueueControl,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.tests.test_application_queue import BINDING, prepared_message, running
from backend.tests.test_naukri_submission import (
    admit,
    apply_ready,
    finish,
    history_ready,
    observation,
)
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def confirmed(session, case):
    context, item, work = await apply_ready(session, case)
    work = await admit(session, case, context, work)
    await finish(session, case, context, work, observation(work, "CLICKED", document_id=work["execution"]["document_id"]))
    for _ in range(2):
        history = await history_ready(session, case, context)
        await finish(session, case, context, history,
                     observation(history, "APPLICATION_SENT", title="Backend Developer", company="Fictional Labs"))
    return await queue.load(session, item["id"])


async def auto_policy(session):
    current = await queue.configuration(session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.platforms["naukri"].mode = "AUTOMATIC"
    return QueuePolicyUpdate(expected_revision=current["revision"], policy=policy)


async def test_auto_configuration_without_receipt_is_denied_without_changing_policy(db_session, upload_case):
    from backend.tests.test_naukri_background_queue import setup

    await setup(db_session)
    before = await queue.configuration(db_session)
    with pytest.raises(ToolDenied, match="automatic_first_verified_worker_receipt_required"):
        await queue.configure(db_session, await auto_policy(db_session))
    assert await queue.configuration(db_session) == before


async def test_denied_auto_edit_preserves_and_allows_the_first_supervised_apply(db_session, upload_case):
    context, item, work = await apply_ready(db_session, upload_case)
    configuration = await queue.configuration(db_session)
    before = dict((await queue.load(db_session, item["id"])).value)
    with pytest.raises(ToolDenied, match="automatic_first_verified_worker_receipt_required"):
        await queue.configure(db_session, await auto_policy(db_session))
    assert await queue.configuration(db_session) == configuration
    assert (await queue.load(db_session, item["id"])).value == before
    admitted = await admit(db_session, upload_case, context, work)
    assert admitted["status"] == "executing"
    stored = (await queue.load(db_session, item["id"])).value
    assert stored["admitted_actions"][0]["fingerprint"].startswith("apply:")


@pytest.mark.parametrize("fault", ["historical_prefix", "not_persistent", "no_admitted_apply", "wrong_account",
                                   "binding_changed", "reconciled_only", "missing_work", "uncertain_work"])
async def test_historical_damaged_or_wrong_context_proof_cannot_unlock_auto(db_session, upload_case, fault):
    work = await confirmed(db_session, upload_case)
    receipt = await db_session.get(OwnerPreference, "naukri_worker_receipt:" + work.value["requisition"])
    if fault == "historical_prefix":
        receipt.key = receipt.key.replace("naukri_worker_receipt:", "naukri_receipt:")
    elif fault == "not_persistent":
        receipt.value = {**receipt.value, "persistent_after_reload": False}
    elif fault == "no_admitted_apply":
        work.value = {**work.value, "admitted_actions": []}
    elif fault == "wrong_account":
        receipt.value = {**receipt.value, "account_sha256": "f" * 64,
                         "second_observation": {**receipt.value["second_observation"], "account_sha256": "f" * 64}}
    elif fault == "binding_changed":
        binding = await db_session.get(OwnerPreference, "naukri_account_binding")
        binding.value = {**binding.value, "revision": binding.value["revision"] + 1}
    elif fault == "reconciled_only":
        receipt.value = {**receipt.value, "worker_dispatched": False}
    elif fault == "missing_work":
        await db_session.delete(work)
    else:
        work.value = {**work.value, "stage": "SUBMISSION_UNKNOWN", "status": "unknown"}
    await db_session.flush()
    with pytest.raises(ToolDenied, match="automatic_first_verified_worker_receipt_required"):
        await require_first_receipt(db_session)


async def test_first_supervised_apply_and_independent_receipt_allow_next_auto_admission(db_session, upload_case):
    first = await confirmed(db_session, upload_case)
    assert await require_first_receipt(db_session) == first.value["requisition"]
    changed = await queue.configure(db_session, await auto_policy(db_session))
    await queue.control(db_session, QueueControl(action="start", expected_revision=changed["revision"]))
    await prepared_message(db_session, upload_case, "291026555444", source="saved_verified_job")
    from backend.app.execution.naukri_identity import require

    binding = {**BINDING, "profile_binding_id": (await require(db_session))["profile_binding_id"]}
    claimed = await queue.claim(db_session, "naukri", binding)
    value = await queue.admit(db_session, claimed["id"], claimed["revision"], claimed["lease_token"], binding, upload_case.settings)
    assert value["operation"] == "apply" and value["status"] == "executing"
    assert len(value["admitted_actions"]) == 1
    assert (await queue.load(db_session, first.value["id"])).value["stage"] == "SUBMITTED_CONFIRMED"


async def test_previously_saved_auto_cannot_start_or_admit_without_first_receipt(db_session, upload_case):
    await running(db_session)
    await prepared_message(db_session, upload_case, "291026555444")
    from backend.app.execution.naukri_identity import require

    binding = {**BINDING, "profile_binding_id": (await require(db_session))["profile_binding_id"]}
    claimed = await queue.claim(db_session, "naukri", binding)
    current = await queue.configuration(db_session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.platforms["naukri"].mode = "AUTOMATIC"
    # Simulate a prior release's saved policy; new configure itself rejects it.
    await queue.put(db_session, queue.POLICY_KEY, {**current, "policy": policy.model_dump(mode="json")})
    for action in ("start", "admit"):
        with pytest.raises(ToolDenied, match="automatic_first_verified_worker_receipt_required"):
            if action == "start":
                await queue.control(db_session, QueueControl(action="start", expected_revision=current["revision"]))
            else:
                await queue.admit(db_session, claimed["id"], claimed["revision"], claimed["lease_token"], binding, upload_case.settings)
    assert not (await queue.load(db_session, claimed["id"])).value["admitted_actions"]
    assert await db_session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith("apply_budget:"),
    )) == 0
