"""Stop costs must follow active authority, not never-attempted history size."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.queue_contracts import QueueControl
from backend.tests.test_application_queue import BINDING, URL, running


async def held(session, requisition):
    item = await queue.enqueue(session, "naukri", URL.rsplit("-", 1)[0] + "-" + requisition, "naukri_ui_search")
    row = await queue.load(session, item["id"])
    row.value = {**row.value, "stage": "NEEDS_INPUT", "status": "waiting",
                 "reason": "applicant_count_requires_review"}
    await session.flush()
    return row


async def test_stop_does_not_rewrite_unattempted_input_holds_but_revokes_active_claim(db_session):
    configuration = await running(db_session)
    rows = [await held(db_session, str(291026230000 + index)) for index in range(30)]
    before = {row.key: dict(row.value) for row in rows}
    active = await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search")
    claimed = await queue.claim(db_session, "naukri", BINDING)
    assert claimed["id"] == active["id"]
    count = await db_session.scalar(select(func.count()).select_from(OwnerPreference).where(OwnerPreference.key.startswith(queue.EVENT)))
    stopped = await queue.control(db_session, QueueControl(action="stop", expected_revision=configuration["revision"]))
    for row in rows:
        assert (await queue.load(db_session, row.value["id"])).value == before[row.key]
    assert (await queue.load(db_session, active["id"])).value["stage"] == "PAUSED"
    assert await db_session.scalar(select(func.count()).select_from(OwnerPreference).where(OwnerPreference.key.startswith(queue.EVENT))) == count + 1
    assert await queue.claim(db_session, "naukri", BINDING) is None
    await queue.control(db_session, QueueControl(action="start", expected_revision=stopped["revision"]))
    fresh = await queue.claim(db_session, "naukri", BINDING)
    assert fresh["id"] == active["id"] and fresh["lease_token"] != claimed["lease_token"]


@pytest.mark.parametrize("authority", ["packet", "form", "action", "lease", "missing_actions"])
async def test_input_holds_with_authority_or_malformed_history_are_still_fenced(db_session, authority):
    configuration = await running(db_session)
    row = await held(db_session, "291026230000")
    value = dict(row.value)
    if authority == "packet":
        value["packet_id"] = "fictional-packet"
    elif authority == "form":
        value["form_pending"] = True
    elif authority == "action":
        value["admitted_actions"] = [{"fingerprint": "apply:fictional"}]
    elif authority == "lease":
        value["lease_until"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    else:
        value.pop("admitted_actions")
    row.value = value
    await db_session.flush()
    await queue.control(db_session, QueueControl(action="stop", expected_revision=configuration["revision"]))
    assert (await queue.load(db_session, value["id"])).value["stage"] == "PAUSED"
