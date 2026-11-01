"""Discovery remains useful when filter-only observations await an owner choice."""

import pytest
from sqlalchemy import func, select

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.queue_contracts import (
    QueueControl,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.tests.test_application_queue import URL, running


async def limit(session, count):
    current = await queue.configuration(session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.max_pending = count
    changed = await queue.configure(session, QueuePolicyUpdate(expected_revision=current["revision"], policy=policy))
    await queue.control(session, QueueControl(action="start", expected_revision=changed["revision"]))


async def hold(session, req):
    item = await queue.enqueue(session, "naukri", URL.rsplit("-", 1)[0] + "-" + req, "naukri_ui_search")
    row = await queue.load(session, item["id"])
    row.value = {**row.value, "stage": "NEEDS_INPUT", "status": "waiting", "reason": "applicant_count_requires_review"}
    await session.flush()
    return row


async def test_filter_history_does_not_exhaust_capacity_and_dedup_preserves_holds(db_session):
    await running(db_session)
    await limit(db_session, 1)
    holds = [await hold(db_session, str(291026230000 + index)) for index in range(12)]
    originals = {row.key: dict(row.value) for row in holds}
    assert await queue.enqueue_batch(db_session, [URL, URL.rsplit("-", 1)[0] + "-291026999999"], "naukri_ui_search") == 1
    with pytest.raises(ToolDenied, match="queue_backpressure"):
        await queue.enqueue(db_session, "naukri", URL.rsplit("-", 1)[0] + "-291026999999", "naukri_ui_search")
    for row in holds:
        assert (await queue.enqueue(db_session, "naukri", row.value["url"], "naukri_ui_search")) == originals[row.key]
    assert len(await queue.items(db_session)) == 13
    assert await db_session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX), queue.capacity_condition(),
    )) == 1


@pytest.mark.parametrize("protected", ["packet", "form", "lease", "action", "missing_actions", "personal_question", "unknown_outcome"])
async def test_personal_form_packet_or_uncertain_work_still_consumes_capacity(db_session, protected):
    await running(db_session)
    await limit(db_session, 1)
    row = await hold(db_session, "291026230000")
    value = dict(row.value)
    if protected == "packet":
        value["packet_id"] = "fictional-packet"
    elif protected == "form":
        value["form_pending"] = True
    elif protected == "lease":
        value["lease_until"] = "2030-01-01T00:00:00+00:00"
    elif protected == "action":
        value["admitted_actions"] = [{"fingerprint": "apply:fictional"}]
    elif protected == "missing_actions":
        value.pop("admitted_actions")
    elif protected == "personal_question":
        value["reason"] = "missing_verified_notice_period"
    else:
        value.update(stage="SUBMISSION_UNKNOWN", status="unknown")
    row.value = value
    await db_session.flush()
    assert queue.uses_capacity(value)
    assert await db_session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX), queue.capacity_condition(),
    )) == 1
    assert await queue.enqueue_batch(db_session, [URL], "naukri_ui_search") == 0

