"""Zero-spam notification policy (pure: no I/O). Maps bus events to a 4-tier priority.

| Tier | Examples                                              | Delivery                                  |
| P0   | CAPTCHA/OTP/HITL cards, auth/login breaker            | immediate push (+ buttons), may break quiet hours |
| P1   | first-mover applied, recruiter reply, breaker open    | silent rollup (one message per window)    |
| P2   | routine applies, discoveries, quota reached           | never pushed: scheduled digest only       |
| P3   | heartbeats, empty sweeps, transient retries           | logs/metrics only (/status, /health)      |

Dedup keys are stable per (event, portal, entity or error fingerprint); cooldowns come from
`NotifyConfig` (env-configurable). HITL cards are rendered and dispatched by the bot itself
(they carry inline keyboards and live in hitl_requests), so `hitl.*` topics map to None here.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import IntEnum
from typing import Any
from zoneinfo import ZoneInfo

TOPICS = ("job.priority_discovered", "job.applied", "job.quota_hit", "quota.summary", "portal.circuit_open",
          "portal.circuit_closed", "portal.auth_required", "mail.recruiter_reply", "system.error")
_KEY_PART = re.compile(r"[^a-z0-9_.-]+")
_AUTHISH = re.compile(r"auth|login|session|captcha|otp|challenge|wall", re.IGNORECASE)


class Priority(IntEnum):
    P0 = 0  # action required
    P1 = 1  # high-signal win
    P2 = 2  # routine: digest only
    P3 = 3  # debug: never pushed


@dataclass(frozen=True)
class Notification:
    topic: str
    priority: Priority
    text: str  # Telegram HTML (escaped)
    digest_line: str  # plain one-liner for the digest / rollup
    dedup_key: str | None = None
    cooldown: timedelta | None = None
    resolves: str | None = None  # recovery event: edit/resolve the live card of this dedup key


@dataclass(frozen=True)
class NotifyConfig:
    tz: ZoneInfo = ZoneInfo("Asia/Kolkata")
    quiet_start: time | None = time(23, 30)
    quiet_end: time | None = time(8, 0)
    quiet_hitl_override: bool = False  # QUESTION/ERROR/AUTH cards wait for morning; OTP/CAPTCHA never wait
    max_pushes_per_hour: int = 5
    rollup: timedelta = timedelta(minutes=15)
    auth_cooldown: timedelta = timedelta(hours=6)
    error_cooldown: timedelta = timedelta(hours=2)
    p1_score: float = 80.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> NotifyConfig:
        def number(name: str, default: float) -> float:
            try:
                return float(env.get(name) or default)
            except ValueError:
                return default

        start, end = _quiet_window(env.get("TELEGRAM_QUIET_HOURS"))
        try:
            tz = ZoneInfo((env.get("TELEGRAM_QUIET_HOURS_TZ") or "Asia/Kolkata").strip())
        except Exception:  # noqa: BLE001 - unknown zone: keep IST
            tz = ZoneInfo("Asia/Kolkata")
        return cls(tz=tz, quiet_start=start, quiet_end=end,
                   quiet_hitl_override=_flag(env.get("TELEGRAM_QUIET_HITL_OVERRIDE")),
                   max_pushes_per_hour=max(1, int(number("TELEGRAM_MAX_PUSHES_PER_HOUR", 5))),
                   rollup=timedelta(minutes=max(1.0, number("TELEGRAM_ROLLUP_MINUTES", 15))),
                   auth_cooldown=timedelta(hours=max(0.1, number("TELEGRAM_AUTH_ALERT_COOLDOWN_HOURS", 6))),
                   error_cooldown=timedelta(hours=max(0.1, number("TELEGRAM_ERROR_COOLDOWN_HOURS", 2))),
                   p1_score=number("TELEGRAM_P1_SCORE_THRESHOLD", 80))

    def in_quiet(self, now: datetime) -> bool:
        if self.quiet_start is None or self.quiet_end is None:
            return False
        local = now.astimezone(self.tz).time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= local < self.quiet_end
        return local >= self.quiet_start or local < self.quiet_end

    def quiet_ends_at(self, now: datetime) -> datetime:
        local = now.astimezone(self.tz)
        end = local.replace(hour=self.quiet_end.hour if self.quiet_end else 8,
                            minute=self.quiet_end.minute if self.quiet_end else 0, second=0, microsecond=0)
        return end if end > local else end + timedelta(days=1)


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _quiet_window(value: str | None) -> tuple[time | None, time | None]:
    raw = (value if value is not None else "23:30-08:00").strip().lower()
    if raw in {"", "off", "none", "0", "false"}:
        return None, None
    try:
        left, right = (part.strip() for part in raw.split("-", 1))
        return time.fromisoformat(left.zfill(5)), time.fromisoformat(right.zfill(5))
    except ValueError:
        return time(23, 30), time(8, 0)


def dedup_key(*parts: Any) -> str:
    """Stable ledger key '<a>:<b>:<c>' (<= 64 chars, hashed tail when longer)."""
    text = ":".join(_KEY_PART.sub("-", str(p).lower()).strip("-") or "x" for p in parts if p is not None)
    if len(text) <= 64:
        return text if len(text) >= 3 else (text + "___")[:3]
    return text[:47] + ":" + hashlib.sha256(text.encode()).hexdigest()[:16]


def next_reset(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _e(value: Any, limit: int = 120) -> str:
    return html.escape(str(value or "")[:limit], quote=False)


def _who(payload: Mapping[str, Any]) -> str:
    parts = [str(payload.get("company") or "").strip(), str(payload.get("title") or "").strip()]
    return " · ".join(p[:100] for p in parts if p) or str(payload.get("external_job_id") or "job")[:60]


def _int(value: Any) -> int | None:
    try:
        return None if value is None or isinstance(value, bool) else int(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def classify(topic: str, payload: Mapping[str, Any], config: NotifyConfig, now: datetime) -> Notification | None:
    platform = str(payload.get("platform") or "system")[:40]
    if topic == "job.priority_discovered":
        who, url = _who(payload), payload.get("apply_url") or payload.get("url")
        key = dedup_key("disc", platform, payload.get("external_job_id"))
        if payload.get("ats_supported") is False and payload.get("apply_url"):
            text = f"⚡ <b>Fresh job needs a manual apply</b> · {_e(platform, 30)} {_e(who)}\n{_e(url, 300)}"
            return Notification(topic, Priority.P1, text, f"⚡ manual apply: {platform} {who} {url}", key,
                                timedelta(days=7))
        return Notification(topic, Priority.P2, "", f"⚡ new P0 job: {platform} {who}", key, timedelta(days=7))
    if topic == "job.applied":
        who, lag = _who(payload), _num(payload.get("first_mover_lag_seconds"))
        lag_text = f" · {int(lag // 60)}m after discovery" if lag is not None else ""
        score, prio = _num(payload.get("score")), _int(payload.get("priority"))
        high = (prio is not None and prio <= 1) or (score is not None and score >= config.p1_score)
        key = dedup_key("applied", platform, payload.get("external_job_id"))
        line = f"✅ applied: {platform} {who}{lag_text}"
        if high:
            return Notification(topic, Priority.P1, f"✅ <b>Applied</b> · {_e(platform, 30)} {_e(who)}{lag_text}",
                                line, key, timedelta(days=30))
        return Notification(topic, Priority.P2, "", line, key, timedelta(days=30))
    if topic in {"job.quota_hit", "quota.summary"}:
        text = str(payload.get("text") or f"daily quota reached ({payload.get('reason') or 'limit'})")
        return Notification(topic, Priority.P2, "", f"📊 {platform}: {text}"[:500],
                             dedup_key("quota", topic.split(".")[-1], platform, now.astimezone(config.tz).date()),
                             next_reset(now, config.tz) - now)
    if topic == "portal.circuit_open":
        reason = str(payload.get("reason") or "")[:200]
        tier = Priority.P0 if _AUTHISH.search(reason) else Priority.P1
        until = payload.get("open_until") or ""
        text = (f"🛑 <b>{_e(platform, 40)}</b> paused by its circuit breaker"
                + (f" until {_e(until, 40)}" if until else "") + (f"\nReason: {_e(reason, 200)}" if reason else "")
                + "\nOther portals keep running.")
        return Notification(topic, tier, text, f"🛑 {platform} breaker open: {reason}",
                            dedup_key("circuit", platform), config.auth_cooldown)
    if topic == "portal.circuit_closed":
        return Notification(topic, Priority.P2, "", f"🟢 {platform} breaker closed (recovered)",
                            None, None, resolves=dedup_key("circuit", platform))
    if topic == "mail.recruiter_reply":
        alert = str(payload.get("alert") or "recruiter reply")[:300]
        return Notification(topic, Priority.P1, f"📬 {_e(alert, 300)}", f"📬 {alert}",
                            dedup_key("mail", hashlib.sha256(alert.encode()).hexdigest()[:20]), timedelta(days=3))
    if topic == "system.error":
        fingerprint = str(payload.get("fingerprint") or payload.get("error") or "error")[:80]
        detail = str(payload.get("detail") or fingerprint)[:200]
        return Notification(topic, Priority.P1, f"⚠️ <b>Worker error</b>: {_e(detail, 200)}",
                            f"⚠️ worker error: {detail}", dedup_key("err", platform, fingerprint),
                            config.error_cooldown)
    if topic == "portal.auth_required":
        # The AUTH HITL card (one OPEN per portal, 6 h dispatch cooldown) is the P0 alert.
        return Notification(topic, Priority.P3, "", f"🔐 {platform} needs login", dedup_key("authlog", platform))
    return None
