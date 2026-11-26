"""Concise HTML Telegram messages + inline keyboards for HITL requests and commands."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

from backend.app.browser_v2.store import HitlRecord

MAX_BUTTON_OPTIONS = 6
MAX_BUTTON_CHARS = 40
LOGIN_COMMAND = "backend/venv/bin/python -m backend.app.browser_v2.cli login-setup --portal {platform}"
CONFLICT_MESSAGE = "Another poller — likely legacy com.automated-apply.rust — is using this bot token"

HELP_TEXT = "<b>automated-apply HITL bot</b>\nAnswer: tap a button, <b>swipe-reply</b> to a question, or:\n/answer &lt;ref&gt; &lt;text&gt; — answer &amp; save to cache\n/once &lt;ref&gt; &lt;text&gt; — answer without caching\n/skip &lt;ref&gt; · /retry &lt;ref&gt;\n/resume &lt;portal&gt; — after login-setup\n/pending — open requests · /status — worker digest\n/pause · /start_worker (or /unpause)\n\n<b>Free chat</b> (control agent; never interrupts an in-flight application): just type, or /ask &lt;text&gt; — e.g. <i>raise Naukri daily limit to 60</i>, <i>pause Internshala for 3 hours</i>, <i>blacklist TCS</i>, <i>how many applied today?</i>"

KIND_ICON = {"QUESTION": "❓", "AUTH": "🔐", "CAPTCHA": "🧩", "OTP": "🔢", "ERROR": "⚠️"}


def _e(value: object, limit: int = 600) -> str:
    text = str(value or "")
    return escape(text if len(text) <= limit else text[: limit - 1] + "…")


def _job_line(hitl: HitlRecord) -> str:
    parts = [f"<b>{_e(hitl.platform.capitalize(), 40)}</b>"]
    if hitl.company:
        parts.append(_e(hitl.company, 80))
    if hitl.title:
        parts.append(_e(hitl.title, 120))
    return " · ".join(parts)


def _header(hitl: HitlRecord, label: str) -> str:
    return f"{KIND_ICON.get(hitl.kind, '•')} <b>{label}</b> · ref <code>{hitl.ref}</code>"


def buttons_for_options(options: tuple[str, ...]) -> bool:
    return 0 < len(options) <= MAX_BUTTON_OPTIONS and all(len(o) <= MAX_BUTTON_CHARS for o in options)


def render_hitl(hitl: HitlRecord) -> tuple[str, dict[str, Any] | None]:
    """Outbound prompt for one OPEN request: (HTML text, inline keyboard or None)."""
    ref, rows = hitl.ref, []
    lines: list[str]
    if hitl.kind == "QUESTION":
        lines = [_header(hitl, "Screening question"), _job_line(hitl), "", f"<i>{_e(hitl.prompt_text, 1500)}</i>"]
        if hitl.resolver_reason:
            lines.append(f"Why you: {_e(hitl.resolver_reason, 120)}")
        options = hitl.options
        if options:
            lines += ["", "Options:", *[f"{i}. {_e(o, 200)}" for i, o in enumerate(options[:30], 1)]]
        if buttons_for_options(options):
            rows += [[{"text": f"{i}. {o}", "callback_data": f"ans:{ref}:{i - 1}"}] for i, o in enumerate(options, 1)]
        lines += ["", ("Tap a button, reply directly to this message to answer &amp; save to cache, "
                      f"or use <code>/once {ref} &lt;answer&gt;</code> to answer without caching.")]
        rows.append([{"text": "Skip job", "callback_data": f"skip:{ref}"}])
    elif hitl.kind == "AUTH":
        lines = [_header(hitl, f"{_e(hitl.platform.capitalize(), 40)} session expired"),
                 "Only this portal is paused; others keep running.", "", "On the Mac run:",
                 f"<code>{_e(LOGIN_COMMAND.format(platform=hitl.platform), 200)}</code>",
                 f"then tap the button or send <code>/resume {_e(hitl.platform, 40)}</code>."]
        rows.append([{"text": f"I've logged in — resume {hitl.platform}"[:60],
                      "callback_data": f"resume:{hitl.platform}"}])
    elif hitl.kind in {"CAPTCHA", "OTP"}:
        lines = [_header(hitl, f"{hitl.kind} needed"), _job_line(hitl), "", _e(hitl.prompt_text, 600), "",
                 ("Reply to this message with the OTP code" if hitl.kind == "OTP" else "Solve it in Brave, then tap Retry")
                 + f", or <code>/skip {ref}</code>."]
        if hitl.kind == "CAPTCHA":
            rows.append([{"text": "Solved — retry", "callback_data": f"retry:{ref}"}])
        rows.append([{"text": "Skip job", "callback_data": f"skip:{ref}"}])
    else:
        lines = [_header(hitl, "Apply error"), _job_line(hitl), "", _e(hitl.prompt_text, 600), "",
                 f"<code>/retry {ref}</code> or <code>/skip {ref}</code>"]
        rows.append([{"text": "Retry", "callback_data": f"retry:{ref}"},
                     {"text": "Skip job", "callback_data": f"skip:{ref}"}])
    return "\n".join(lines), ({"inline_keyboard": rows} if rows else None)


def render_resolved(hitl: HitlRecord, outcome: str) -> str:
    """Edited version of the original prompt once resolved (keyboard removed)."""
    text, _ = render_hitl(hitl)
    body = text.split("\n\nTap a button", 1)[0].split("\n\nOn the Mac run:", 1)[0]
    return f"{body}\n\n✅ {_e(outcome, 300)}"


def _age(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "never"
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def render_pending(rows: list[HitlRecord], total: int) -> str:
    if not rows:
        return "Nothing pending. ✅"
    lines = [f"<b>{total} open request{'s' if total != 1 else ''}</b>"]
    for hitl in rows:
        who = " · ".join(_e(p, 40) for p in (hitl.platform, hitl.company) if p)
        lines.append(f"<code>{hitl.ref}</code> {hitl.kind} · {who} — {_e(hitl.prompt_text, 70)}")
    if total > len(rows):
        lines.append(f"…and {total - len(rows)} more (see /autopilot).")
    return "\n".join(lines)


def render_status(*, worker: Any, portals: list[dict[str, Any]], open_hitl: int,
                  providers: list[str] | None, telegram_state: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    dry = " · DRY RUN" if worker.dry_run else " · LIVE"
    lines = [f"🤖 Worker <b>{worker.desired_state.value}</b> (observed {_e(worker.observed_state, 20)}){dry}",
             f"Heartbeat {_age(worker.heartbeat_at, now)}"
             + (f" · on {_e(worker.current_platform, 40)}" if worker.current_platform else "")]
    if worker.last_error:
        lines.append(f"Last error: {_e(worker.last_error, 140)}")
    lines.append("")
    for portal in portals:
        if not portal["enabled"]:
            lines.append(f"• {_e(portal['platform'], 40)} — disabled")
            continue
        icon = {"OK": "✅", "AUTH_REQUIRED": "🔐"}.get(portal["auth_status"], "❔")
        auto = "auto-apply on" if portal["auto_apply_enabled"] else "inspect only"
        lines.append(f"• {_e(portal['platform'], 40)} {icon} {portal['auth_status']} · "
                     f"{portal['applied_today']}/{portal['max_applies_per_day']} today · {auto}")
    lines += ["", f"Open HITL: <b>{open_hitl}</b> (/pending)"]
    if providers is None:
        lines.append("LLM router: disabled (deterministic + cache)")
    else:
        lines.append("LLM router: " + (", ".join(_e(p, 30) for p in providers) if providers
                                       else "no free providers configured (deterministic + cache)"))
    lines.append(f"Telegram: {_e(telegram_state, 20)}")
    return "\n".join(lines)
