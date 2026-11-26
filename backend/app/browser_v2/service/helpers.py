"""Shared service helpers: state aliases, JSON copies, quota counts, env profile fallbacks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import NEVER_REPLAY, TRANSITIONS, ApplicationState
from backend.app.browser_v2.store import ApplicationRecord, Store

S = ApplicationState
# A duplicate in any of these states means the role was (or is being) applied to elsewhere.
DUPLICATE_BLOCKING = NEVER_REPLAY | {S.APPLYING, S.WAITING_FOR_USER}


def plain(value: Any) -> Any:
    """JSON-friendly copy of adapter dataclasses/enums."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    return value


def day_start(rules: PortalRules, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(rules.timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def quota_counts(store: Store, rules: PortalRules, now: datetime | None = None) -> dict[str, Any]:
    """Live APPLIED counts for the portal's local day and the last rolling hour."""
    now = now or datetime.now(UTC)
    start = day_start(rules, now)
    today = await store.applied_since(rules.platform, start)
    hour = await store.applied_since(rules.platform, now - timedelta(hours=1))
    portal_limit_today = bool(rules.portal_limit_hit_at and rules.portal_limit_hit_at >= start)
    return {"applied_today": today, "applied_this_hour": hour,
            "daily_limit_hit": today >= rules.max_applies_per_day,
            "hourly_limit_hit": hour >= rules.max_applies_per_hour,
            "portal_limit_hit_today": portal_limit_today}


def can_move(record: ApplicationRecord, target: ApplicationState) -> bool:
    return record.state == target or target in TRANSITIONS[record.state]


def env_profile_overrides(env: Mapping[str, str]) -> dict[str, str]:
    """Project-.env candidate fallbacks: only values the owner stored (never invented)."""
    path = (env.get("CANDIDATE_RESUME_PATH") or env.get("MAIL_DRAFT_RESUME_PATH") or "").strip()
    return {"resume_path": str(Path(path).expanduser())} if path else {}


def apply_env_profile(facts: CandidateFacts, overrides: Mapping[str, str]) -> CandidateFacts:
    """Fill the resume fallback from the project .env when the DB profile has no resume_files."""
    path = overrides.get("resume_path")
    if not path or not Path(path).is_file():
        return facts
    facts.identity.setdefault("resume_path", path)
    if not facts.resume_files:
        facts.resume_files = {"default": path}
    return facts
