"""Trusted inactive setup-tab receipt. No profile Save or job operation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.browser import chrome_profiles as profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.naukri_identity import require
from backend.app.execution.naukri_native import MAINTENANCE
from backend.app.execution.queue_contracts import QueueControl
from backend.tests.test_naukri_background_queue import call, setup
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def test_operator_helper_refuses_suspended_webui_before_loading_configuration(tmp_path):
    from backend.scripts.request_naukri_maintenance import request_setup

    with pytest.raises(ValueError, match="^extension_manager_navigation_suspended$"):
        await request_setup(tmp_path / "missing-private-env")


async def prepare(session):
    context = await setup(session)
    config = await queue.configuration(session)
    await queue.control(session, QueueControl(action="stop", expected_revision=config["revision"]))
    chrome = await session.get(OwnerPreference, profiles.PROFILE + str(context["profile_binding_id"]))
    selected = await profiles.selection(session)
    account = await require(session)
    intent = {"kind": "open_naukri_profile_setup", "request_id": str(uuid4()),
              "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
              "account_binding_revision": account["revision"], "candidate_profile_id": account["candidate_profile_id"],
              "binding": {"profile_binding_id": chrome.value["id"], "profile_version": chrome.value["version"],
                          "selection_version": selected["version"], "browser_session_id": str(context["browser_session_id"]),
                          "window_id": context["window_id"], "tab_id": None}}
    await queue.put(session, MAINTENANCE, intent)
    return context, intent


async def test_setup_ack_is_idempotent_bound_and_owner_adoption_is_permanent(db_session, upload_case):
    context, intent = await prepare(db_session)
    initial = await call(db_session, context, "poll_naukri_work")
    assert initial.ok and initial.data["maintenance"]["kind"] == "open_naukri_profile_setup"
    for _ in range(2):
        result = await call(db_session, context, "poll_naukri_work", tab_id=44, work_id=intent["request_id"])
        assert result.ok and result.data["maintenance_recorded"] and result.data["work"] is None
    subsequent = await call(db_session, context, "poll_naukri_work")
    assert subsequent.ok and subsequent.data["work"] is None and "maintenance" not in subsequent.data
    result = await call(db_session, context, "poll_naukri_work", tab_id=44, work_id=intent["request_id"],
                        work_report={"kind": "needs_input", "reason": "owner_tab_active"})
    assert result.ok
    await call(db_session, context, "poll_naukri_work", tab_id=44, work_id=intent["request_id"])
    stored = await db_session.get(OwnerPreference, MAINTENANCE, populate_existing=True)
    assert stored.value["owner_adopted"] and stored.value["opened_tab_id"] == 44
    assert (await queue.configuration(db_session))["state"] == "STOPPED"
    assert not await queue.items(db_session)


@pytest.mark.parametrize("fault", ["wrong_request", "different_tab", "unexpected_report", "running", "expired", "binding", "account"])
async def test_setup_ack_cannot_change_context_or_grant_work(db_session, upload_case, fault):
    context, intent = await prepare(db_session)
    kwargs = {"tab_id": 44, "work_id": intent["request_id"]}
    if fault == "wrong_request":
        kwargs["work_id"] = str(uuid4())
    elif fault == "different_tab":
        assert (await call(db_session, context, "poll_naukri_work", **kwargs)).ok
        kwargs["tab_id"] = 55
    elif fault == "unexpected_report":
        kwargs["work_report"] = {"kind": "failed", "reason": "fictional_error"}
    elif fault == "running":
        config = await queue.configuration(db_session)
        await queue.control(db_session, QueueControl(action="start", expected_revision=config["revision"]))
    else:
        if fault == "expired":
            intent["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        elif fault == "binding":
            intent["binding"] = {**intent["binding"], "window_id": 999}
        else:
            intent["account_binding_revision"] += 1
        await queue.put(db_session, MAINTENANCE, intent)
    result = await call(db_session, context, "poll_naukri_work", **kwargs)
    assert not result.ok
    stored = (await db_session.get(OwnerPreference, MAINTENANCE, populate_existing=True)).value
    assert stored.get("opened_tab_id") == (44 if fault == "different_tab" else None)
    assert not await queue.items(db_session)
