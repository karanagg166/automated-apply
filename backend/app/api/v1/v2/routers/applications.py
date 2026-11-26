"""v2 control plane: application list + per-application state events."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.app.api.v1.v2.deps import StoreDep
from backend.app.browser_v2.schemas import (
    ApplicationPage,
    ApplicationRead,
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
) -> ApplicationPage:
    rows, total = await store.list_applications(ApplicationQuery(
        platform=platform, state=state.value if state else None, since=since, until=until,
        limit=limit, offset=offset))
    return ApplicationPage(items=[ApplicationRead(**row.public()) for row in rows], total=total,
                           limit=limit, offset=offset)


@router.get("/applications/{application_id}/events", response_model=list[StateEventRead])
async def application_events(application_id: str, store: StoreDep
                             ) -> list[StateEventRead]:
    from uuid import UUID

    try:
        UUID(application_id)
    except ValueError:
        if not application_id.startswith("mem-"):
            raise HTTPException(404, "Application not found") from None
    events = await store.application_events(application_id)
    if events is None:
        raise HTTPException(404, "Application not found")
    return [StateEventRead(**event) for event in events]
