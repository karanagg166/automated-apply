"""Milestone 2: owner pause switches for watched ATS boards (pure).

A watched board is a token in `preferences.<platform>_boards`; pausing it adds "<platform>:<token>" to
`preferences.paused_watch_boards`. Paused boards are skipped by both the fast-poll watchers and the
feed adapters' own sweeps, and resumed by removing the key (the board token itself is kept).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

WATCH_PLATFORMS = ("greenhouse", "lever", "ashby", "smartrecruiters")
PAUSED_KEY = "paused_watch_boards"


def watch_key(platform: str, slug: str) -> str:
    return f"{platform}:{slug}"


def paused_boards(prefs: Mapping[str, Any] | None) -> frozenset[str]:
    raw = (prefs or {}).get(PAUSED_KEY)
    return frozenset(str(v) for v in raw if isinstance(v, str)) if isinstance(raw, (list, tuple)) else frozenset()


def active_boards(platform: str, boards: Mapping[str, str | None],
                  prefs: Mapping[str, Any] | None) -> dict[str, str | None]:
    paused = paused_boards(prefs)
    return {token: company for token, company in boards.items() if watch_key(platform, token) not in paused}
