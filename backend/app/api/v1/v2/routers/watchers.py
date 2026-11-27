"""ATS watchlist: list / add / toggle watched boards and the SSRF-safe auto-detect probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.api.v1.v2.deps import StoreDep
from backend.app.browser_v2.schemas.proof import (
    ProbeInput,
    ProbeResult,
    WatcherRow,
    WatcherUpsert,
)
from backend.app.browser_v2.store import ProfileMissing

router = APIRouter()


@router.get("/portals/watchers", response_model=list[WatcherRow])
async def list_watched_boards(store: StoreDep) -> list[WatcherRow]:
    from backend.app.browser_v2.watchers.watchlist import list_watchers

    return [WatcherRow(**row) for row in await list_watchers(store)]


@router.post("/portals/watchers", response_model=WatcherRow)
async def upsert_watched_board(data: WatcherUpsert, store: StoreDep) -> WatcherRow:
    """Add a Greenhouse / Lever / Ashby / SmartRecruiters board to the watchlist, or pause / resume it."""
    from backend.app.browser_v2.watchers.watchlist import WatchlistFull, upsert_watcher

    try:
        return WatcherRow(**await upsert_watcher(store, data.platform, data.slug, data.active))
    except ProfileMissing:
        raise HTTPException(409, "Create the candidate profile first") from None
    except WatchlistFull as exc:
        raise HTTPException(422, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)[:300]) from None


async def _probe(target: str, store: Any) -> dict[str, Any]:
    """Seam for tests (monkeypatched): the real probe reads the fixed public ATS API hosts."""
    from backend.app.browser_v2.watchers.probe import detect_board, probe

    profile, _ = await store.load_profile()
    prefs = profile.get("preferences") if isinstance(profile, dict) else None
    ref = await detect_board(target)  # careers pages are fetched (guarded) at most once, here
    rules = await store.get_rules(ref.platform)
    return await probe(f"{ref.platform}:{ref.slug}", rules=rules, preferences=prefs or {})


@router.post("/portals/watchers/probe", response_model=ProbeResult)
async def probe_board(data: ProbeInput, store: StoreDep) -> ProbeResult:
    """Detect the ATS behind a careers URL (or `platform:slug`), count its open jobs and preview how
    many pass the current rules. Private / non-HTTPS / credentialed URLs are refused (422)."""
    from backend.app.browser_v2.watchers.probe import ProbeError

    try:
        return ProbeResult(**await _probe(data.target, store))
    except ProbeError as exc:
        raise HTTPException(422, f"{exc} ({exc.code})") from None
