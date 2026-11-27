"""Operational slash commands (followup 007): /health /queue /hitl /mute /digest /cache and
portal-scoped /pause /resume, plus the setMyCommands menu and the queue tap buttons.

Every command is a direct reply to the owner (never counted against the push budget). Inline
`q:go:<uuid>` / `q:skip:<uuid>` buttons stay <= 64 bytes and change state with a version CAS
(`store.transition` / `set_owner_priority`), so a double tap acts once.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import WorkerState
from backend.app.telegram_v2.base import TelegramBotBase, logger

BOT_COMMANDS: list[tuple[str, str]] = [
    ("status", "Worker, portals, today's applies vs quota, pending HITL"),
    ("health", "Breakers, portal sessions, DB, Telegram delivery health"),
    ("queue", "Top pending jobs with one-tap Apply/Skip"),
    ("hitl", "Open questions waiting for you"),
    ("pause", "/pause [portal|all] - pause applying"),
    ("resume", "/resume [portal|all] - resume (portal: after login-setup)"),
    ("mute", "/mute 2h | /mute off - hold non-urgent pushes"),
    ("digest", "Send the digest now"),
    ("cache", "Semantic answer cache stats"),
    ("help", "All commands"),
]
_DURATION = re.compile(r"^(\d{1,3})\s*([mhd])$")
QUEUE_LIMIT = 8


def parse_duration(text: str) -> timedelta | None:
    match = _DURATION.match((text or "").strip().lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=value), "h": timedelta(hours=value), "d": timedelta(days=value)}[unit]
    return delta if timedelta(minutes=1) <= delta <= timedelta(days=7) else None


def _e(value: Any, limit: int = 80) -> str:
    return html.escape(str(value or "")[:limit], quote=False)


def _age(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "?"
    minutes = int((now - then).total_seconds() // 60)
    return f"{minutes}m" if minutes < 120 else f"{minutes // 60}h"


class OpsCommandsMixin(TelegramBotBase):
    async def handle_ops_command(self, command: str, argument: str) -> str | tuple[str, dict[str, Any]] | None:
        """Reply text (or (text, keyboard)) for an ops command, None when `command` is not one."""
        if command == "/health":
            return await self.health_text()
        if command == "/queue":
            return await self.queue_view()
        if command == "/hitl":
            from backend.app.telegram_v2.formatting import render_pending

            rows, total = await self.store.list_hitl("OPEN", limit=20)
            return render_pending(rows, total) if total else "✅ 0 open questions."
        if command == "/mute":
            return await self.mute(argument)
        if command == "/digest":
            return await self.digest_now()
        if command == "/cache":
            return await self.cache_text()
        if command == "/pause" and argument and argument.lower() != "all":
            return await self.pause_portal(argument.split()[0].lower())
        if command == "/pause":
            control = await self.store.set_worker_control(WorkerState.PAUSED)
            return f"⏸ Worker: <b>{control.desired_state.value}</b> (takes effect between jobs)."
        if command == "/resume" and (not argument or argument.lower() == "all"):
            control = await self.store.set_worker_control(WorkerState.RUNNING)
            return f"▶️ Worker: <b>{control.desired_state.value}</b> ({'DRY RUN' if control.dry_run else 'LIVE'})."
        return None

    async def register_commands(self) -> None:
        if self.client is None:
            return
        try:
            await self.client.set_my_commands(BOT_COMMANDS)
        except Exception as exc:  # noqa: BLE001 - the menu is cosmetic
            logger.info("setMyCommands failed: %s", type(exc).__name__)

    async def latency_line(self, now: datetime) -> str | None:
        """First-mover speed today: median / best lag from posting (or discovery) to submit."""
        from statistics import median

        from backend.app.browser_v2.digest import local_day_start
        from backend.app.browser_v2.store import ApplicationQuery

        try:
            rows, _ = await self.store.list_applications(ApplicationQuery(
                state=ApplicationState.APPLIED.value, since=local_day_start(now), limit=200))
        except Exception:  # noqa: BLE001
            return None
        lags = [timing["first_mover_lag_seconds"] for r in rows
                if isinstance(timing := (r.receipt or {}).get("timing"), dict)
                and isinstance(timing.get("first_mover_lag_seconds"), (int, float))]
        if not lags:
            return None
        return (f"⚡ First-mover lag today: median {int(median(lags) // 60)}m · best {int(min(lags) // 60)}m "
                f"({len(lags)} applies)")

    # --- /pause <portal> ------------------------------------------------------------------------
    async def pause_portal(self, platform: str) -> str:
        try:
            rules = await self.store.get_rules(platform)
            await self.store.update_rules(platform, {"paused_until": self.clock() + timedelta(days=30)},
                                          rules.revision)
        except Exception as exc:  # noqa: BLE001 - unknown portal / revision race
            return f"Could not pause <b>{_e(platform)}</b>: {_e(type(exc).__name__)}"
        return f"⏸ <b>{_e(platform)}</b> paused (other portals keep running). <code>/resume {_e(platform)}</code>"

    async def unpause_portal(self, platform: str) -> None:
        try:
            rules = await self.store.get_rules(platform)
            if rules.paused_until is not None:
                await self.store.update_rules(platform, {"paused_until": None}, rules.revision)
        except Exception as exc:  # noqa: BLE001
            logger.info("unpause %s failed: %s", platform, type(exc).__name__)

    # --- /mute ---------------------------------------------------------------------------------
    async def mute(self, argument: str) -> str:
        if self.notifier is None:
            return "Mute needs the worker's notification router (run the worker)."
        if argument.strip().lower() in {"off", "0", "no"}:
            await self.notifier.set_mute(None)
            return "🔔 Unmuted. Held updates arrive in the next digest (/digest to get them now)."
        delta = parse_duration(argument or "2h")
        if delta is None:
            return "Usage: <code>/mute 2h</code> (1m..7d) or <code>/mute off</code>"
        until = self.clock() + delta
        await self.notifier.set_mute(until)
        return (f"🔕 Muted non-urgent pushes until {until.astimezone(self.notifier.config.tz):%a %H:%M}. "
                "Questions, OTP and CAPTCHA still reach you.")

    # --- /digest -------------------------------------------------------------------------------
    async def digest_now(self) -> str:
        from backend.app.browser_v2.digest import build_digest_report

        queued = await self.notifier.pending_digest() if self.notifier is not None else []
        text, _ = await build_digest_report(self.store, self.clock(), ai=self.ai, mail_events=self.mail_events,
                                            queued=queued)
        if self.notifier is not None and queued:
            await self.notifier.mark_digest_delivered(queued)
        return html.escape(text, quote=False)

    # --- /cache --------------------------------------------------------------------------------
    async def cache_text(self) -> str:
        cache = getattr(self.ai, "cache", None) if self.ai is not None else None
        stats_fn = getattr(cache, "stats", None)
        if cache is None or stats_fn is None:
            return "Semantic cache is not configured in this process."
        try:
            stats = stats_fn()
            if hasattr(stats, "__await__"):
                stats = await stats
        except Exception as exc:  # noqa: BLE001
            return f"Cache stats unavailable: {_e(type(exc).__name__)}"
        lines = ["🧠 <b>Semantic cache</b>"]
        for key, value in (stats or {}).items():
            if isinstance(value, dict):
                inner = ", ".join(f"{_e(k, 40)} {_e(v, 20)}" for k, v in list(value.items())[:12])
                lines.append(f"• {_e(key, 40)}: {inner or '-'}")
            else:
                lines.append(f"• {_e(key, 40)}: {_e(value, 60)}")
        return "\n".join(lines)

    # --- /health -------------------------------------------------------------------------------
    async def health_text(self) -> str:
        now = self.clock()
        lines = ["🩺 <b>Health</b>"]
        try:
            worker = await self.store.get_worker_control()
            beat = getattr(worker, "heartbeat_at", None)
            lines.append(f"Worker: {_e(worker.observed_state)} · heartbeat {_age(now, beat)} ago"
                         + (" ⚠️ stale" if beat is None or now - beat > timedelta(minutes=15) else ""))
            lines.append("DB: ok")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"DB: ⚠️ {_e(type(exc).__name__)}")
        try:
            for rules in await self.store.list_rules():
                if not rules.enabled:
                    continue
                breaker = getattr(rules, "circuit_open_until", None)
                state = f"breaker open until {breaker:%H:%M}" if breaker and breaker > now else "breaker ok"
                paused = " · paused" if rules.paused_until and rules.paused_until > now else ""
                lines.append(f"• {_e(rules.platform, 30)}: auth {_e(rules.auth_status, 20)} · {state}{paused}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Portals: ⚠️ {_e(type(exc).__name__)}")
        telegram = await self.store.get_telegram_state()
        lines.append(f"Telegram: {_e(telegram.polling_state)} · last poll {_age(now, telegram.last_poll_at)} ago")
        if self.notifier is not None:
            h = self.notifier.health()
            lines.append(f"Pushes: {h['pushes_last_hour']}/{h['budget']} this hour · queued {h['queued']} · "
                         f"429s {h['client_rate_limited']}" + (" · ⚠️ send circuit open" if h["client_circuit_open"]
                                                                  else ""))
        cache = getattr(self.ai, "cache", None) if self.ai is not None else None
        lines.append("Embeddings/cache: " + ("configured" if cache is not None else "off"))
        return "\n".join(lines)

    # --- /queue + tap buttons ------------------------------------------------------------------
    async def queue_view(self) -> tuple[str, dict[str, Any]] | str:
        now = self.clock()
        rows = await self.store.priority_candidates(now, max_priority=3, limit=QUEUE_LIMIT)
        if not rows:
            return "📭 Queue is empty."
        lines, keyboard = [f"📋 <b>Top {len(rows)} queued jobs</b>"], []
        for index, record in enumerate(rows, 1):
            posted = getattr(record, "posted_at", None) or record.created_at
            lines.append(f"{index}. P{record.priority} · {_e(record.platform, 20)} · {_e(record.company_name, 40)} · "
                         f"{_e(record.role_title, 60)} · {_age(now, posted)} old")
            keyboard.append([{"text": f"▶️ {index} apply next", "callback_data": f"q:go:{record.id}"},
                             {"text": f"⏭ {index} skip", "callback_data": f"q:skip:{record.id}"}])
        return "\n".join(lines), {"inline_keyboard": keyboard}

    async def queue_button(self, action: str, application_id: str) -> str:
        record = await self.store.get_application(application_id)
        if record is None:
            return "That job no longer exists."
        if action == "skip":
            if record.state not in (ApplicationState.DISCOVERED, ApplicationState.SCORED):
                return f"Already {record.state.value.lower()} — nothing changed."
            try:
                await self.store.transition(record, ApplicationState.FILTERED_OUT, "owner_skipped_via_telegram")
            except Exception:  # noqa: BLE001 - stale version: another tap/worker got there first
                return "Already changed — nothing done."
            return "⏭ Skipped."
        if record.state not in (ApplicationState.DISCOVERED, ApplicationState.SCORED):
            return f"Already {record.state.value.lower()} — nothing changed."
        await self.store.set_owner_priority(record.id, 0, "owner_tapped_apply_next")
        if self.agent_wake is not None:
            self.agent_wake()
        return "▶️ Moved to the front of the queue."
