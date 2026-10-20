"""Owner boundary, planning, profile approvals and notification windows."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.automation.schemas import ScheduleConfiguration
from backend.app.dashboard.notifications import notification_window, synchronize
from backend.app.dashboard.schemas import NotificationPreferences


@pytest.mark.parametrize(
    "changes",
    [
        {"sources": ["linkedin"]},
        {"sources": ["wellfound"]},
        {"sources": ["gmail_alert"]},
        {"sources": ["remotive"], "interval_seconds": 21599},
        {"interval_seconds": 299},
        {"sources": ["arbeitnow", "arbeitnow"]},
        {"enabled": True},
        {"approved_profile_version": 1},
        {"approved_profile_id": str(uuid4())},
        {"limit": 51},
        {"allow_paid": True},
    ],
)
def test_unsafe_configuration_rejected(changes):
    with pytest.raises(ValidationError):
        ScheduleConfiguration(**changes)


@pytest.mark.parametrize(
    ("zone", "at", "expected"),
    [
        ("Asia/Kolkata", "2026-01-01T16:29:59+00:00", "available"),
        ("Asia/Kolkata", "2026-01-01T16:30:00+00:00", "quiet_hours"),
        ("Asia/Kolkata", "2026-01-02T02:29:59+00:00", "quiet_hours"),
        ("Asia/Kolkata", "2026-01-02T02:30:00+00:00", "available"),
        ("America/New_York", "2026-11-01T05:30:00+00:00", "quiet_hours"),
        ("America/New_York", "2026-11-01T06:30:00+00:00", "quiet_hours"),
        ("America/New_York", "2026-03-08T07:00:00+00:00", "quiet_hours"),
    ],
)
def test_timezone_boundaries(zone, at, expected):
    assert (
        notification_window(
            NotificationPreferences(timezone=zone), datetime.fromisoformat(at)
        )
        == expected
    )


@pytest.mark.parametrize("changes", [{"paused": True}, {"in_app": False}])
def test_notification_opt_out(changes):
    assert (
        notification_window(
            NotificationPreferences(**changes), datetime.now(timezone.utc)
        )
        == "paused"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ""),
        ("PUT", ""),
        ("GET", "/history"),
        ("GET", "/matches"),
        ("POST", "/preview"),
        ("POST", "/run"),
    ],
)
async def test_api_requires_owner(async_client, method, path, phase2_auth):
    result = await async_client.request(method, "/api/v1/dashboard/automation" + path)
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_default_disabled_preview_and_gate(async_client, phase2_auth):
    base = "/api/v1/dashboard/automation"
    result = await async_client.get(base, headers=phase2_auth)
    assert result.status_code == 200 and result.json()["state"] == "disabled"
    assert "no-store" in result.headers["cache-control"]
    plan = (await async_client.post(base + "/preview", headers=phase2_auth)).json()
    assert plan["provider_calls"] == 0 and plan["planning_only"]
    run = await async_client.post(
        base + "/run",
        headers=phase2_auth,
        json={"expected_version": 1, "idempotency_key": "fixture"},
    )
    assert run.status_code == 409
    enabled = await async_client.put(
        base,
        headers=phase2_auth,
        json={
            "expected_version": 1,
            "configuration": {"enabled": True, "sources": ["arbeitnow"]},
        },
    )
    assert enabled.status_code == 409
    history = (await async_client.get(base + "/history", headers=phase2_auth)).json()
    assert history["executions"] == []


@pytest.mark.asyncio
async def test_profile_approval_and_conflicting_settings(
    async_client, phase2_auth, phase2_profile
):
    base = "/api/v1/dashboard/automation"
    config = {
        "enabled": False,
        "sources": ["arbeitnow"],
        "approved_profile_id": str(phase2_profile.id),
        "approved_profile_version": phase2_profile.version,
    }
    response = await async_client.put(
        base, headers=phase2_auth, json={"expected_version": 1, "configuration": config}
    )
    assert response.status_code == 200 and response.json()["matching"] == "approved"
    stale_write = await async_client.put(
        base, headers=phase2_auth, json={"expected_version": 1, "configuration": config}
    )
    assert stale_write.status_code == 409
    config["approved_profile_version"] += 1
    invalid_approval = await async_client.put(
        base, headers=phase2_auth, json={"expected_version": 2, "configuration": config}
    )
    assert invalid_approval.status_code == 409


@pytest.mark.asyncio
async def test_scheduler_notifications_deferred_deduplicated_and_read(
    async_client, phase2_auth, db_session
):
    from sqlalchemy import func, select

    from backend.app.automation.models import AutomationExecution
    from backend.app.dashboard.models import (
        Notification,
        NotificationDelivery,
        OwnerPreference,
    )

    db_session.add(
        OwnerPreference(key="notifications", value={"in_app": True, "paused": True})
    )
    db_session.add(
        AutomationExecution(
            request_key="fixture",
            source="remotive",
            trigger_type="scheduled",
            state="blocked",
            schedule_version=1,
            configuration={},
        )
    )
    await db_session.commit()
    assert (await synchronize(db_session, automation=True))["created"] == 0
    prefs = await db_session.get(OwnerPreference, "notifications")
    prefs.value = {
        "in_app": True,
        "quiet_start": 0,
        "quiet_end": 0,
        "daily_digest": False,
    }
    await db_session.commit()
    first = await synchronize(db_session, automation=True)
    await db_session.commit()
    second = await synchronize(db_session, automation=True)
    await db_session.commit()
    assert first["created"] == 2 and second["created"] == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(NotificationDelivery))
        == 2
    )
    item = await db_session.scalar(
        select(Notification).where(Notification.kind == "scheduled_discovery_failed")
    )
    response = await async_client.post(
        f"/api/v1/dashboard/notifications/{item.id}/read", headers=phase2_auth
    )
    assert response.status_code == 200
    await db_session.refresh(item)
    assert item.read_at is not None


@pytest.mark.asyncio
async def test_postgres_required_for_worker():
    from backend.app.automation.worker import DiscoveryWorker
    from backend.app.core.config import Settings
    from backend.app.db.session import get_session_factory

    worker = DiscoveryWorker(get_session_factory(), Settings(_env_file=None))
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        await worker.claim()


@pytest.mark.asyncio
async def test_worker_graceful_stop_stops_admission(monkeypatch):
    import asyncio

    from backend.app.automation import worker
    from backend.app.core.config import Settings

    stop = asyncio.Event()
    calls = []

    async def tick(self):
        calls.append(True)
        stop.set()

    monkeypatch.setattr(worker.DiscoveryWorker, "tick", tick)
    await asyncio.wait_for(
        worker.serve(None, Settings(_env_file=None), stop), timeout=1
    )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_owner_disable_survives_stale_approved_profile(
    async_client, phase2_auth, phase2_profile, monkeypatch, db_session
):
    from backend.app.core.config import get_settings
    from backend.app.models.candidate_profile import CandidateProfile

    monkeypatch.setenv("AUTOMATION_EXECUTION_ENABLED", "true")
    get_settings.cache_clear()
    base = "/api/v1/dashboard/automation"
    config = {
        "enabled": True,
        "sources": ["arbeitnow"],
        "approved_profile_id": str(phase2_profile.id),
        "approved_profile_version": phase2_profile.version,
    }
    enabled = await async_client.put(
        base, headers=phase2_auth, json={"expected_version": 1, "configuration": config}
    )
    assert enabled.status_code == 200
    record = await db_session.get(CandidateProfile, phase2_profile.id)
    record.summary = "Fictional owner-edited summary"
    await db_session.commit()
    config["enabled"] = False
    disabled = await async_client.put(
        base, headers=phase2_auth, json={"expected_version": 2, "configuration": config}
    )
    assert disabled.status_code == 200 and disabled.json()["state"] == "disabled"
    get_settings.cache_clear()
