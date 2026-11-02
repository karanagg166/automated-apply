"""Dashboard filtering stays exact while historical counts remain global."""
import pytest
from sqlalchemy import event

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import profile_sync


async def test_dashboard_profile_status_needs_no_resume_query_and_preserves_references(db_session, phase2_profile):
    from backend.app.local_agent.profile_confirmation import confirm_profile

    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    await queue.put(db_session, profile_sync.WORK, {"last_record": "current", "last_error": "fictional_warning"})
    await queue.put(db_session, profile_sync.RECORD + "current", {"id": "current", "outcome": "SYNC_VERIFIED"})
    await queue.put(db_session, profile_sync.RECORD + "unrelated", {"id": "unrelated", "outcome": "COMPARED"})
    await db_session.flush()
    statements = []
    def observed(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(db_session.bind.sync_engine, "before_cursor_execute", observed)
    try:
        value = await profile_sync.status(db_session)
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", observed)
    assert value["profile_confirmed"] and value["current_profile_version"] == phase2_profile.version
    assert value["latest"] == {"id": "current", "outcome": "SYNC_VERIFIED"}
    assert value["last_error"] == "fictional_warning"
    assert value["configuration"]["revision"] == 0
    assert len(statements) == 2 and all("candidate_resources" not in s for s in statements)


@pytest.mark.parametrize("filters,ids", [
    ({}, ["two", "one", "zero"]),
    ({"platform": "naukri"}, ["one", "zero"]),
    ({"stage": "SKIPPED"}, ["one"]),
    ({"search": "alpha"}, ["zero"]),
    ({"location": "pune"}, ["two", "zero"]),
    ({"minimum_score": 50}, ["two", "zero"]),
    ({"platform": "naukri", "location": "pune", "minimum_score": 50}, ["zero"]),
    ({"search": "no matching listing"}, []),
])
async def test_listing_page_total_filters_and_global_counts_are_independent(db_session, filters, ids):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    for index, (identity, platform, title, location, score, stage) in enumerate([
        ("zero", "naukri", "Alpha Python", "Pune", 95, "NEEDS_INPUT"),
        ("one", "naukri", "Beta Java", "Delhi", None, "SKIPPED"),
        ("two", "wellfound", "Gamma React", "Pune", 80, "SUBMITTED_RECORDED"),
    ]):
        db_session.add(OwnerPreference(key=queue.PREFIX + identity, created_at=now + timedelta(seconds=index),
            value={"id": identity, "platform": platform, "title": title, "location": location,
                   "match_score": score, "stage": stage, "facts": {"description": "private fixture text"}}))
    await db_session.flush()
    result = await queue.listing(db_session, **filters, limit=1, offset=1)
    assert result["total"] == len(ids)
    assert [r["id"] for r in result["items"]] == ids[1:2]
    assert result["counts"] == {"NEEDS_INPUT": 1, "SKIPPED": 1, "SUBMITTED_RECORDED": 1}
    assert "private fixture text" not in str(result)
    assert result["configuration"]["state"] == "STOPPED"
    assert result["discovery"] is None and result["consumer"] is None
