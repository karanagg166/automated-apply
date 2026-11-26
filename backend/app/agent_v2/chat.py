"""LLM-first owner chat (Telegram, API, MCP, CLI): confirmations, PII placeholders, memory and
the deterministic fallback.

Order: "confirm"/"cancel" with a pending risky write -> ReAct agent (open HITL items, last 12
turns and a safe profile summary in its context) -> on zero providers / all exhausted / invalid
steps twice: the Phase 6A deterministic path (`intent.parse` + ControlAgent graph) with a short
note naming the failed providers (at most once per hour per chat unless nothing understood it).

Never sent to an LLM and never stored in memory: OTP codes (masked as [CODE_n] while an OTP
request is open) and HITL answers (the user turn is replaced by a marker once a request is
resolved through the agent).
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from backend.app.agent_v2.react import HITL_TOOL, ReactAgent
from backend.app.agent_v2.tools import AuditedToolRunner, ToolResult
from backend.app.ai_v2.pii import (
    build_safe_llm_profile,
    profile_secrets,
    scrub_pii,
    scrub_with_map,
)
from backend.app.browser_v2.store import AuditEntry, ConversationTurn

logger = logging.getLogger(__name__)
CONFIRM_RE = re.compile(r"^\s*(?:yes[,!. ]*)?(?:confirm(?:ed)?|do it)\s*[.!]*\s*$", re.IGNORECASE)
CANCEL_RE = re.compile(r"^\s*(?:no[,!. ]*)?(?:cancel|abort)\s*[.!]*\s*$", re.IGNORECASE)
NOTE_EVERY = timedelta(hours=1)
HITL_MARKER = "[answered an open request; the answer is not stored]"
DETERMINISTIC_WRITES = {"update_portal_rule", "update_preferences", "teach_semantic_cache", "control_worker"}
_TAGS = re.compile(r"<[^>]+>")
_last_note: dict[str, datetime] = {}  # chat_key -> last fallback note (process-wide rate limit)
# Pleasantries never answer an open question (mirrors telegram_v2.base.CHIT_CHAT).
_CHIT_CHAT = re.compile(r"^(?:thanks?(?: you)?|thx|ty|ok(?:ay)?|k|cool|nice|great|hi|hello|hey|yo|"
                        r"good (?:morning|night|evening)|👍|🙏|👌|✅)[.!\s]*$", re.IGNORECASE)


def html_to_text(text: str) -> str:
    return html.unescape(_TAGS.sub("", text or ""))


def _hitl_line(row: Any) -> dict[str, Any]:
    return {"ref": row.ref, "kind": row.kind, "portal": row.platform, "company": row.company, "title": row.title,
            "question": (row.prompt_text or "")[:200], "options": list(row.options)[:8]}


class AgentChat:
    def __init__(self, store: Any, router: Any, runner: AuditedToolRunner, *,
                 fallback: Callable[[str], Awaitable[dict[str, Any]]], clock: Callable[[], datetime]) -> None:
        self.store = store
        self.router = router
        self.runner = runner
        self.fallback = fallback
        self.clock = clock

    # --- helpers -----------------------------------------------------------------------------
    async def _open_hitl(self) -> list[Any]:
        try:
            rows, _ = await self.store.list_hitl("OPEN", limit=20)
            return list(rows)
        except Exception:  # noqa: BLE001 - context is best effort
            return []

    async def _profile(self) -> dict[str, Any]:
        try:
            profile, _ = await self.store.load_profile()
            return dict(profile or {})
        except Exception:  # noqa: BLE001
            return {}

    async def _history(self, chat_key: str) -> list[dict[str, str]]:
        try:
            return [{"role": t.role, "content": t.content} for t in await self.store.recent_turns(chat_key, 12)]
        except Exception:  # noqa: BLE001 - followup 005 not applied yet: no memory
            return []

    async def _remember(self, chat_key: str, user: str, assistant: str) -> None:
        for role, content in (("user", user), ("assistant", assistant)):
            if not content.strip():
                continue
            try:
                await self.store.append_turn(ConversationTurn(chat_key, role, content))
            except Exception as exc:  # noqa: BLE001 - memory is optional
                logger.info("agent memory write skipped: %s", type(exc).__name__)
                return

    def outcome_dict(self, result: ToolResult, *, tool: str | None, verdict: str) -> dict[str, Any]:
        html_reply = result.user_html or html.escape(result.message, quote=False)
        return {"reply": html_to_text(html_reply), "reply_html": html_reply, "tool": tool, "tools": [tool] if tool
                else [], "source": "owner", "verdict": verdict, "ok": result.ok, "mode": "confirmation",
                "confirmation": None, "hitl_resolutions": [r for r in [result.data.get("resolution")] if r]}

    # --- entry -----------------------------------------------------------------------------------
    async def handle(self, text: str, *, chat_key: str, source: str) -> dict[str, Any]:
        text = (text or "").strip()[:2000]
        now = self.clock()
        if CONFIRM_RE.match(text) and self.runner.pending.latest(chat_key, now) is not None:
            pending = self.runner.pending.latest(chat_key, now)
            result = await self.runner.confirm(None, chat_key=chat_key, source=source)
            return self.outcome_dict(result, tool=pending.tool_name if pending else None,
                                verdict="ok" if result.ok else "rejected")
        if CANCEL_RE.match(text) and self.runner.pending.latest(chat_key, now) is not None:
            return self.outcome_dict(await self.runner.cancel(None, chat_key=chat_key, source=source), tool=None,
                                verdict="cancelled")
        open_rows = await self._open_hitl()
        if self.router is None or not getattr(self.router, "any_configured", False):
            return await self._fallback(text, chat_key, source, open_rows, "no LLM provider is configured")
        profile = await self._profile()
        secrets = tuple(profile_secrets(profile))
        otp_open = any(row.kind == "OTP" for row in open_rows)
        scrubbed, mapping = scrub_with_map(text, secrets, mask_codes=otp_open)
        context = {"history": await self._history(chat_key), "profile": build_safe_llm_profile(profile),
                   "open_requests": [_hitl_line(row) for row in open_rows[:8]]}

        async def load() -> dict[str, Any]:
            return context

        agent = ReactAgent(self.router, self.runner, load_context=load, secrets=secrets, clock=self.clock)
        try:
            state = await agent.run(scrubbed, mapping=mapping, chat_key=chat_key, source=source)
        except Exception as exc:  # noqa: BLE001 - a graph bug must never lose the message
            logger.warning("agent react failed: %s", type(exc).__name__)
            state = {"failure": f"agent error ({type(exc).__name__})"}
        if state.get("failure") and not state.get("tools"):
            return await self._fallback(text, chat_key, source, open_rows, str(state["failure"]))
        prose = html.escape(str(state.get("reply") or ""), quote=False)
        blocks = [b for b in state.get("blocks") or [] if b]
        reply_html = "\n\n".join([p for p in (prose, *blocks) if p]) or "Done."
        tools = list(state.get("tools") or [])
        memory_user = HITL_MARKER if HITL_TOOL in tools else scrub_pii(scrubbed, secrets)
        memory_reply = scrub_pii(str(state.get("reply") or ""), secrets)
        for placeholder, value in mapping.items():  # a rehydrated OTP code never lands in memory
            if placeholder.startswith("[CODE_"):
                memory_reply = memory_reply.replace(value, "[code]")
        await self._remember(chat_key, memory_user, memory_reply)
        outcomes = list(state.get("outcomes") or [])
        confirmation = state.get("confirmation")
        verdict = "confirm" if confirmation else "rejected" if "refused" in outcomes else "ok"
        return {"reply": html_to_text(reply_html), "reply_html": reply_html, "tool": tools[-1] if tools else None,
                "tools": tools, "source": "llm", "verdict": verdict, "provider": state.get("provider"),
                "ok": verdict == "ok" and "error" not in outcomes, "mode": "llm", "confirmation": confirmation,
                "hitl_resolutions": list(state.get("resolutions") or []), "data": {}}

    # --- deterministic fallback -------------------------------------------------------------------
    async def _fallback(self, text: str, chat_key: str, source: str, open_rows: list[Any],
                        note: str) -> dict[str, Any]:
        result = dict(await self.fallback(text))
        tool, verdict = result.get("tool"), result.get("verdict")
        handled = tool not in (None, "help") or verdict == "help" and text.lower().strip("/? ") in ("help", "")
        reply = str(result.get("reply") or "")
        answers = [row for row in open_rows if row.kind in ("QUESTION", "OTP")]
        questions = [row for row in answers if row.kind == "QUESTION"]
        resolutions: list[Any] = []
        if not handled and len(answers) == 1 and questions and text and not _CHIT_CHAT.match(text):
            # Offline: exactly one open question and a plain reply -> that is the answer (Phase 8 behaviour).
            answered = await self.runner.run("resolve_hitl_via_agent",
                                             {"hitl_id_or_ref": questions[0].ref, "answer": text},
                                             source=source, chat_key=chat_key)
            if answered.ok:
                data = answered.data if isinstance(answered.data, dict) else {}
                if data.get("resolution") is not None:
                    resolutions.append(data["resolution"])
                result |= {"tool": "resolve_hitl_via_agent", "verdict": "ok", "ok": True}
                reply, handled = answered.message, True
        if not handled and answers:
            refs = "\n".join(f"• {row.ref} {row.company or row.platform} ({row.kind.lower()}): "
                             f"{(row.prompt_text or '')[:90]}" for row in answers[:10])
            reply = (f"❓ {len(answers)} open request(s), and I won't guess which one that answers without the "
                     f"LLM. Swipe-reply to the request's message, or send /answer <ref> <text>:\n{refs}")
        now = self.clock()
        show_note = not handled or now - _last_note.get(chat_key, datetime.min.replace(tzinfo=now.tzinfo)) \
            >= NOTE_EVERY
        reply_html = html.escape(reply, quote=False)
        if show_note:
            _last_note[chat_key] = now
            reply_html += f"\n\n<i>ℹ️ {html.escape(note, quote=False)}; used the built-in command parser.</i>"
        await self._audit_deterministic(result, source)
        if handled and not resolutions:  # HITL answers never enter conversation memory
            await self._remember(chat_key, scrub_pii(text), scrub_pii(reply))
        return result | {"reply": html_to_text(reply_html), "reply_html": reply_html, "mode": "deterministic",
                         "llm_note": note if show_note else None, "confirmation": None,
                         "hitl_resolutions": resolutions}

    async def _audit_deterministic(self, result: dict[str, Any], source: str) -> None:
        tool, verdict = str(result.get("tool") or ""), result.get("verdict")
        if tool == "forbidden" or (tool in DETERMINISTIC_WRITES and verdict in ("ok", "rejected", "confirm")):
            if tool == "control_worker" and "desired=" in str(result.get("reply") or ""):
                return  # status query
            outcome = {"ok": "ok" if result.get("ok") else "error", "rejected": "refused",
                       "confirm": "needs_confirmation"}.get(str(verdict), "refused")
            try:
                await self.store.append_audit(AuditEntry(
                    source=source, tool_name="forbidden_request" if tool == "forbidden" else tool, outcome=outcome,
                    args={"path": "deterministic"}, error=None if outcome == "ok" else scrub_pii(
                        str(result.get("reply") or ""))[:300]))
            except Exception as exc:  # noqa: BLE001
                logger.info("deterministic audit skipped: %s", type(exc).__name__)


__all__ = ["CANCEL_RE", "CONFIRM_RE", "HITL_MARKER", "AgentChat", "html_to_text"]
