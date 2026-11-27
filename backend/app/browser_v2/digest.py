"""Nightly Telegram digest (Phase 6A): one crisp summary per day at DIGEST_HOUR_IST.

Applied today by portal, Gmail drafts created, tomorrow's retry queue, recruiter
replies detected, open HITL count and free-LLM quota status. Sent at most once per
local date: `claim()` atomically sets telegram_v2_state.last_digest_on BEFORE sending
(UPDATE ... WHERE last_digest_on IS DISTINCT FROM today), so a worker restart around
21:00 or two senders can never double-send; a failed send releases the claim so the
next housekeeping tick retries. DIGEST_DISABLED=true turns it off; DIGEST_HOUR_IST
(0-23, default 21) moves it.

Followup 007: DIGEST_TIMES_IST="09,21" (default) sends a morning and an evening digest; each slot
is claimed atomically (telegram_v2_state.last_digest_slot). The digest also carries the queued
routine (P2) notifications and anything deferred by quiet hours, /mute or the hourly push budget,
and with skip_empty it is not sent at all when nothing meaningful happened.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.portals import portal_label
from backend.app.browser_v2.state import ApplicationState

logger = logging.getLogger(__name__)
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


def digest_hours(env: Mapping[str, str] | None = None) -> tuple[int, ...]:
    """DIGEST_TIMES_IST ("09:00,21:00" or "9,21"); falls back to the single DIGEST_HOUR_IST."""
    from backend.app.browser_v2.env_loader import load_env

    values = env if env is not None else load_env()
    single = digest_hour(values)
    if single is None:
        return ()
    raw = (values.get("DIGEST_TIMES_IST") or "").strip()
    if not raw:
        return (9, 21) if not (values.get("DIGEST_HOUR_IST") or "").strip() else (single,)
    hours = set()
    for part in raw.split(","):
        try:
            hour = int(part.strip().split(":")[0])
        except ValueError:
            continue
        if 0 <= hour <= 23:
            hours.add(hour)
    return tuple(sorted(hours)) or (single,)


def local_day_start(now: datetime) -> datetime:
    local = now.astimezone(DIGEST_TZ)
    return datetime.combine(local.date(), time(0, 0), tzinfo=DIGEST_TZ)


async def build_digest(store: Any, now: datetime, *, ai: Any = None, mail_events: Any = None,
                       queued: list[Any] | None = None) -> str:
    text, _ = await build_digest_report(store, now, ai=ai, mail_events=mail_events, queued=queued)
    return text


async def build_digest_report(store: Any, now: datetime, *, ai: Any = None, mail_events: Any = None,
                              queued: list[Any] | None = None) -> tuple[str, bool]:
    """(text, meaningful). meaningful = anything happened or needs the owner.
    `queued` = notification digest items (router), not the DRAFTED_AND_QUEUED retry count."""
    items = list(queued or [])
    start = local_day_start(now)
    morning = now.astimezone(DIGEST_TZ).hour < 12
    lines = [f"{'☀️ Morning' if morning else '🌙 Daily'} digest — {start.strftime('%a %d %b')} (IST)"]
    applied_total, portal_lines = 0, []
    for rules in await store.list_rules():
        count = await store.applied_since(rules.platform, start)
        applied_total += count
        if count or rules.enabled:
            portal_lines.append(f"  • {portal_label(rules.platform)}: {count}/{rules.max_applies_per_day}")
    lines.append(f"✅ Applied today: {applied_total}")
    lines.extend(portal_lines)
    drafts = await store.count_email_drafts("CREATED", since=start)
    retry_queue = await store.count_state(ApplicationState.DRAFTED_AND_QUEUED)
    lines.append(f"✉️ Gmail drafts created: {drafts} (review in Gmail → Drafts; never sent automatically)")
    lines.append(f"🔁 Queued for tomorrow's retry: {retry_queue}")
    replies = 0
    if mail_events is not None:
        try:
            replies = sum(1 for e in await mail_events.recent(("RECRUITER_REPLY", "INTERVIEW"), limit=100)
                          if e.created_at is None or e.created_at >= start)
        except Exception:  # noqa: BLE001 - mail_events table may be missing before 004
            replies = 0
    lines.append(f"📬 Recruiter replies / interview alerts: {replies}")
    open_hitl = await store.count_open_hitl()
    lines.append(f"🙋 Open HITL requests: {open_hitl}")
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
    if items:
        lines.append(f"🗂 Since the last digest ({len(items)}):")
        lines.extend(f"  • {getattr(item, 'text', item)}" for item in items[:40])
        if len(items) > 40:
            lines.append(f"  … and {len(items) - 40} more")
    meaningful = bool(applied_total or drafts or replies or open_hitl or items)
    return "\n".join(lines), meaningful


class DigestScheduler:
    """One slot (hour=21): the original once-per-IST-day claim. Several slots (hours=(9, 21)):
    one atomic claim per 'YYYY-MM-DDTHH' slot."""

    def __init__(self, store: Any, *, hour: int | None = DEFAULT_HOUR, hours: tuple[int, ...] | None = None,
                 skip_empty: bool = False) -> None:
        self.store = store
        self.hours = tuple(sorted(set(hours))) if hours else (() if hour is None else (hour,))
        self.hour = self.hours[0] if len(self.hours) == 1 else None
        self.skip_empty = skip_empty
        self.sent_on: Any = None
        self.sent_slot: str | None = None
        self._previous_slot: str | None = None

    def slot(self, now: datetime) -> str | None:
        local = now.astimezone(DIGEST_TZ)
        past = [h for h in self.hours if local.hour >= h]
        return f"{local.date().isoformat()}T{max(past):02d}" if past else None

    @property
    def multi(self) -> bool:
        return len(self.hours) > 1

    async def due(self, now: datetime) -> bool:
        if not self.hours:
            return False
        if self.multi:
            slot = self.slot(now)
            if slot is None or slot == self.sent_slot:
                return False
            state = await self.store.get_telegram_state()
            if getattr(state, "last_digest_slot", None) == slot:
                self.sent_slot = slot
                return False
            return True
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

    async def claim(self, now: datetime) -> tuple[bool, Any]:
        """(claimed, previous last_digest_on). Falls back to the in-memory guard before 004."""
        if self.multi:
            return await self._claim_slot(now)
        day = now.astimezone(DIGEST_TZ).date()
        claim = getattr(self.store, "claim_digest_day", None)
        if claim is None:
            return True, None
        try:
            previous = getattr(await self.store.get_telegram_state(), "last_digest_on", None)
            claimed = await claim(day)
        except Exception:  # noqa: BLE001 - column missing before 004: in-memory guard still holds
            return True, None
        if not claimed:
            self.sent_on = day
        return bool(claimed), previous

    async def _claim_slot(self, now: datetime) -> tuple[bool, Any]:
        slot = self.slot(now)
        if slot is None:
            return False, None
        try:
            previous = getattr(await self.store.get_telegram_state(), "last_digest_slot", None)
            claimed = await self.store.claim_digest_slot(slot, previous)
        except Exception:  # noqa: BLE001 - followup 007 missing: the in-memory guard still holds
            return slot != self.sent_slot, None
        if not claimed:
            self.sent_slot = slot
        return bool(claimed), previous

    async def release(self, now: datetime, previous: Any) -> None:
        if self.multi:
            slot = self.slot(now)
            self.sent_slot = None
            if slot is not None:
                try:
                    await self.store.claim_digest_slot(previous, slot)  # CAS back to the previous slot
                except Exception:  # noqa: BLE001
                    logger.info("digest slot release failed")
            return
        day = now.astimezone(DIGEST_TZ).date()
        self.sent_on = None
        release = getattr(self.store, "release_digest_day", None)
        if release is not None:
            try:
                await release(day, previous)
            except Exception:  # noqa: BLE001, S110
                pass

    async def mark_sent(self, now: datetime) -> None:
        if self.multi:
            self.sent_slot = self.slot(now)
            return
        day = now.astimezone(DIGEST_TZ).date()
        self.sent_on = day
        try:
            await self.store.update_telegram_state(last_digest_on=day)
        except Exception:  # noqa: BLE001, S110 - column missing before 004: in-memory guard still holds
            pass
