"""Milestone 2: the dashboard ATS watchlist (list / add / pause / resume watched boards).

Boards live where the watchers and feed adapters already read them: `preferences.<platform>_boards`
(plus the optional *_BOARDS env settings). Pausing never deletes the token: it adds
"<platform>:<slug>" to `preferences.paused_watch_boards`, which `adapters.watchlist.active_boards`
honours in both the fast-poll watchers and the adapters' sweeps. Poll stats come from watcher_state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.app.browser_v2.adapters.greenhouse import MAX_BOARDS, board_map
from backend.app.browser_v2.adapters.watchlist import (
    PAUSED_KEY,
    WATCH_PLATFORMS,
    paused_boards,
    watch_key,
)
from backend.app.browser_v2.watchers.probe import BoardRef

SETTINGS = {"greenhouse": "GREENHOUSE_BOARDS", "lever": "LEVER_BOARDS", "ashby": "ASHBY_BOARDS",
            "smartrecruiters": "SMARTRECRUITERS_BOARDS"}


class WatchlistFull(ValueError):
    pass


def _settings_boards(platform: str) -> dict[str, str | None]:
    try:
        from backend.app.core.config import get_settings

        return board_map(getattr(get_settings(), SETTINGS[platform], None))
    except Exception:  # noqa: BLE001 - settings are optional
        return {}


def _prefs_of(profile: Any) -> dict[str, Any]:
    prefs = profile.get("preferences") if isinstance(profile, Mapping) else None
    return dict(prefs) if isinstance(prefs, Mapping) else {}


async def _row(store: Any, platform: str, slug: str, paused: frozenset[str]) -> dict[str, Any]:
    state = None
    if platform != "smartrecruiters":  # no fast-poll watcher for SmartRecruiters (sweeps only)
        try:
            state = await store.get_watcher_state(watch_key(platform, slug))
        except Exception:  # noqa: BLE001 - followup 005 missing: stats unknown
            state = None
    return {"platform": platform, "slug": slug, "active": watch_key(platform, slug) not in paused,
            "board_url": BoardRef(platform, slug).board_url,
            "last_polled_at": getattr(state, "last_poll_at", None), "last_status": getattr(state, "last_status", None),
            "jobs_found": len(state.seen_ids) if state is not None else None}


async def list_watchers(store: Any) -> list[dict[str, Any]]:
    profile, _ = await store.load_profile()
    prefs = _prefs_of(profile)
    paused = paused_boards(prefs)
    rows = []
    for platform in WATCH_PLATFORMS:
        boards = _settings_boards(platform) | board_map(prefs.get(f"{platform}_boards"))
        for slug in list(boards)[:MAX_BOARDS]:
            rows.append(await _row(store, platform, slug, paused))
    return rows


async def upsert_watcher(store: Any, platform: str, slug: str, active: bool) -> dict[str, Any]:
    """Add the board if new, then pause/resume it. Raises WatchlistFull past 25 boards per platform."""
    profile, _ = await store.load_profile()
    prefs = _prefs_of(profile)
    key = f"{platform}_boards"
    boards = board_map(prefs.get(key))
    changes: dict[str, Any] = {}
    if slug not in boards and slug not in _settings_boards(platform):
        if len(boards) >= MAX_BOARDS:
            raise WatchlistFull(f"{platform} already watches {MAX_BOARDS} boards")
        changes[key] = boards | {slug: None}
    paused = set(paused_boards(prefs))
    target = watch_key(platform, slug)
    (paused.discard if active else paused.add)(target)
    if paused != set(paused_boards(prefs)):
        changes[PAUSED_KEY] = sorted(paused)
    if changes:
        await store.update_preferences(changes)
    return await _row(store, platform, slug, frozenset(paused))
