"""Fictional histories beyond the status response's thirty-record limit."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from backend.app.browser import chrome_profiles
from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store


@pytest.mark.parametrize("same_timestamp", [False, True])
@pytest.mark.parametrize("reverse_scan", [False, True])
@pytest.mark.asyncio
async def test_status_retains_newest_commands_and_receipts_independent_of_scan_order(
    db_session, monkeypatch, same_timestamp, reverse_scan
):
    async def forbidden_lock(*args, **kwargs):
        pytest.fail("Reading current history must not take the owner fence")

    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    baseline = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Deliberately disagree with both chronological and key order. SQLite's
    # reverse scan option additionally exercises the opposite database order.
    insertion_order = [*range(34, -1, -2), *range(1, 35, 2)]
    for index in insertion_order:
        identity = f"fictional-{index:02d}"
        created = baseline + timedelta(seconds=0 if same_timestamp else index)
        for prefix in (chrome_profiles.COMMAND, "ext_receipt:"):
            db_session.add(OwnerPreference(
                key=prefix + identity,
                created_at=created,
                value={"id": identity, "state": "completed", "version": 1,
                       **({"lease_token": "fictional-secret", "payload_hash": "private"}
                          if prefix == chrome_profiles.COMMAND else {})},
            ))
    await db_session.commit()
    await db_session.execute(text(
        "PRAGMA reverse_unordered_selects = " + ("ON" if reverse_scan else "OFF")
    ))
    reads = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", observed)
    try:
        result = await chrome_profiles.listing(db_session, Settings(_env_file=None))
    finally:
        event.remove(engine, "before_cursor_execute", observed)
        await db_session.execute(text("PRAGMA reverse_unordered_selects = OFF"))

    expected = [f"fictional-{index:02d}" for index in range(5, 35)]
    assert [value["id"] for value in result["commands"]] == expected
    assert [value["id"] for value in result["receipts"]] == expected
    assert len(reads) == 1
    assert all("lease_token" not in value and "payload_hash" not in value
               for value in result["commands"])
