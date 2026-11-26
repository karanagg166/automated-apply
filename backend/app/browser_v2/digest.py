"""Nightly Telegram digest (Phase 6A): one crisp summary per day at DIGEST_HOUR_IST.

Applied today by portal, Gmail drafts created, tomorrow's retry queue, recruiter
replies detected, open HITL count and free-LLM quota status. Sent at most once per
local date (telegram_v2_state.last_digest_on survives restarts). DIGEST_DISABLED=true
turns it off; DIGEST_HOUR_IST (0-23, default 21) moves it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.portals import portal_label
from backend.app.browser_v2.state import ApplicationState

DIGEST_TZ = ZoneInfo("Asia/Kolkata")
DEFAULT_HOUR = 21


def digest_hour(env: Mapping[str, str] | None = None) -> int | None:
    from backend.app.browser_v2.env_loader import load_env

    values = env if env is not None else load_env()
    if (values.get("DIGEST_DISABLED") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    try:
        hour = int(values.get("DIGEST_HOUR_IST") or DEFAULT_HOUR)
    except ValueError:
        return DEFAULT_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_HOUR


def local_day_start(now: datetime) -> datetime:
    local = now.astimezone(DIGEST_TZ)
    return datetime.combine(local.date(), time(0, 0), tzinfo=DIGEST_TZ)


async def build_digest(store: Any, now: datetime, *, ai: Any = None, mail_events: Any = None) -> str:
    start = local_day_start(now)
    lines = [f"🌙 Daily digest — {start.strftime('%a %d %b')} (IST)"]
    applied_total, portal_lines = 0, []
    for rules in await store.list_rules():
        count = await store.applied_since(rules.platform, start)
        applied_total += count
        if count or rules.enabled:
            portal_lines.append(f"  • {portal_label(rules.platform)}: {count}/{rules.max_applies_per_day}")
    lines.append(f"✅ Applied today: {applied_total}")
    lines.extend(portal_lines)
    drafts = await store.count_email_drafts("CREATED", since=start)
    queued = await store.count_state(ApplicationState.DRAFTED_AND_QUEUED)
    lines.append(f"✉️ Gmail drafts created: {drafts} (review in Gmail → Drafts; never sent automatically)")
    lines.append(f"🔁 Queued for tomorrow's retry: {queued}")
    replies = 0
    if mail_events is not None:
        try:
            replies = sum(1 for e in await mail_events.recent(("RECRUITER_REPLY", "INTERVIEW"), limit=100)
                          if e.created_at is None or e.created_at >= start)
        except Exception:  # noqa: BLE001 - mail_events table may be missing before 004
            replies = 0
    lines.append(f"📬 Recruiter replies / interview alerts: {replies}")
    lines.append(f"🙋 Open HITL requests: {await store.count_open_hitl()}")
    if ai is not None:
        try:
            providers = [p for p in await ai.router.status() if p["status"] != "unconfigured"]
        except Exception:  # noqa: BLE001
            providers = []
        if providers:
            usage = ", ".join(f"{p['provider']} {p['requests_today']}/{p['rpd_limit']}"
                              + ("" if p["status"] == "healthy" else f" ({p['status']})") for p in providers)
            lines.append(f"🤖 Free LLM usage today: {usage}")
        else:
            lines.append("🤖 Free LLM: no provider configured (deterministic + cache mode)")
    return "\n".join(lines)


class DigestScheduler:
    def __init__(self, store: Any, *, hour: int | None = DEFAULT_HOUR) -> None:
        self.store = store
        self.hour = hour
        self.sent_on: Any = None

    async def due(self, now: datetime) -> bool:
        if self.hour is None:
            return False
        local = now.astimezone(DIGEST_TZ)
        if local.hour < self.hour or local - local_day_start(now) > timedelta(hours=23, minutes=59):
            return False
        if self.sent_on == local.date():
            return False
        state = await self.store.get_telegram_state()
        if getattr(state, "last_digest_on", None) == local.date():
            self.sent_on = local.date()
            return False
        return True

    async def mark_sent(self, now: datetime) -> None:
        day = now.astimezone(DIGEST_TZ).date()
        self.sent_on = day
        try:
            await self.store.update_telegram_state(last_digest_on=day)
        except Exception:  # noqa: BLE001, S110 - column missing before 004: in-memory guard still holds
            pass
