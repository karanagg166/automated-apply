"""v2 control plane: application list (filter + search), per-portal summary, one application's detail
(safe receipt projection + timeline) and per-application state events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.app.api.v1.v2.deps import StoreDep
from backend.app.api.v1.v2.routers.application_views import (
    SUMMARY_TZ,
    build_detail,
    build_summary,
    summary_window,
)
from backend.app.browser_v2.schemas import (
    ApplicationDetail,
    ApplicationPage,
    ApplicationRead,
    ApplicationSummary,
    StateEventRead,
)
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import ApplicationQuery

router = APIRouter()


# --- applications -------------------------------------------------------------------
@router.get("/applications", response_model=ApplicationPage)
async def list_applications(
    store: StoreDep,
    platform: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z][a-z0-9_]{1,39}$")] = None,
    state: ApplicationState | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    q: Annotated[str | None, Query(max_length=100, description="Company or role contains (case-insensitive)")]
    = None,
) -> ApplicationPage:
    rows, total = await store.list_applications(ApplicationQuery(
        platform=platform, state=state.value if state else None, since=since, until=until,
        limit=limit, offset=offset, q=(q or "").strip() or None))
    return ApplicationPage(items=[ApplicationRead(**row.public()) for row in rows], total=total,
                           limit=limit, offset=offset)


# Registered before /applications/{application_id} so "summary" is never read as an id.
@router.get("/applications/summary", response_model=ApplicationSummary)
async def applications_summary(store: StoreDep, days: Annotated[int, Query(ge=1, le=90)] = 14
                               ) -> ApplicationSummary:
    """Per-portal counts by state (all time), applied today / last 7 days on the owner's local
    calendar (Asia/Kolkata) and a daily applied series for the last `days` days."""
    now = datetime.now(UTC)
    _, since = summary_window(days, now)
    states, daily = await store.application_summary(since, SUMMARY_TZ)
    platforms = [rules.platform for rules in await store.list_rules()]
    return build_summary(states, daily, platforms, days=days, now=now)


def _application_id_or_404(application_id: str) -> None:
    from uuid import UUID

    try:
        UUID(application_id)
    except ValueError:
        if not application_id.startswith("mem-"):
            raise HTTPException(404, "Application not found") from None


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def application_detail(application_id: str, store: StoreDep) -> ApplicationDetail:
    """One application plus a safe receipt projection (screening Q&A, verification, screenshot flag;
    never file paths or raw JSON) and its state timeline."""
    _application_id_or_404(application_id)
    record = await store.get_application(application_id)
    if record is None:
        raise HTTPException(404, "Application not found")
    return build_detail(record, await store.application_events(application_id) or [])


@router.get("/applications/{application_id}/events", response_model=list[StateEventRead])
async def application_events(application_id: str, store: StoreDep
                             ) -> list[StateEventRead]:
    _application_id_or_404(application_id)
    events = await store.application_events(application_id)
    if events is None:
        raise HTTPException(404, "Application not found")
    return [StateEventRead(**event) for event in events]
