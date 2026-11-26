"""AuditedToolRunner: validate -> guard -> confirm-if-risky -> execute -> audit -> publish.

Every write, refusal and confirmation request lands in agent_audit_log with sanitized args and
before/after summaries. Risky writes return `needs_confirmation` plus a token; the owner confirms
(Telegram button `agc:<token>` or typing "confirm") or cancels (`agx:<token>`) within 10 minutes.
"""

from __future__ import annotations

import json
import logging
import secrets as token_source
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.app.agent_v2.tools.base import (
    GuardrailViolation,
    NeedsConfirmation,
    ToolResult,
)
from backend.app.agent_v2.tools.guardrails import (
    FORBIDDEN_TOOL_WORDS,
    audit_args,
    fence_reason,
    sanitize,
)
from backend.app.agent_v2.tools.registry import TOOL_REGISTRY
from backend.app.agent_v2.tools.spec import ToolContext, ToolSpec, h, refused
from backend.app.browser_v2.store.agent_records import (
    TOOL_NAME,
    AuditEntry,
    FencedRowError,
)

logger = logging.getLogger(__name__)
CONFIRM_TTL = timedelta(minutes=10)


@dataclass
class PendingAction:
    token: str
    chat_key: str
    tool_name: str
    args: dict[str, Any]
    source: str
    reason: str
    created_at: datetime


class PendingConfirmations:
    """In-memory pending risky writes, 10-minute TTL (never persisted: a restart cancels them)."""

    def __init__(self, ttl: timedelta = CONFIRM_TTL) -> None:
        self.ttl = ttl
        self.items: dict[str, PendingAction] = {}

    def purge(self, now: datetime) -> list[PendingAction]:
        expired = [p for p in self.items.values() if now - p.created_at > self.ttl]
        for item in expired:
            self.items.pop(item.token, None)
        return expired

    def add(self, chat_key: str, tool_name: str, args: dict[str, Any], source: str, reason: str,
            now: datetime) -> PendingAction:
        self.purge(now)
        action = PendingAction(token_source.token_hex(5), chat_key, tool_name, args, source, reason, now)
        self.items[action.token] = action
        return action

    def latest(self, chat_key: str, now: datetime) -> PendingAction | None:
        self.purge(now)
        mine = [p for p in self.items.values() if p.chat_key == chat_key]
        return max(mine, key=lambda p: p.created_at) if mine else None

    def take(self, token: str | None, chat_key: str, now: datetime) -> PendingAction | None:
        """Pop a live pending action of this chat (latest when token is None); None if expired/unknown."""
        self.purge(now)
        action = self.latest(chat_key, now) if token is None else self.items.get(token)
        if action is None or action.chat_key != chat_key:
            return None
        return self.items.pop(action.token, None)


PENDING = PendingConfirmations()  # process-wide: Telegram, API, MCP and CLI share one map


def _args_dict(args: BaseModel) -> dict[str, Any]:
    return args.model_dump(mode="json", exclude_none=True)


class AuditedToolRunner:
    def __init__(self, ctx: ToolContext, registry: dict[str, ToolSpec] | None = None,
                 pending: PendingConfirmations | None = None) -> None:
        self.ctx = ctx
        self.registry = registry if registry is not None else TOOL_REGISTRY
        self.pending = pending if pending is not None else PENDING

    async def _audit(self, source: str, tool_name: str, outcome: str, args: dict[str, Any], *,
                     before: Any = None, after: Any = None, error: str | None = None) -> None:
        try:
            secrets = await self.ctx.secrets()
            entry = AuditEntry(source=source if source in ("telegram", "api", "mcp", "cli", "worker") else "api",
                               tool_name=tool_name if TOOL_NAME.match(tool_name) else "unknown_tool",
                               outcome=outcome, args=audit_args(tool_name, args, secrets),
                               before_summary=sanitize(before, secrets) if isinstance(before, dict) else None,
                               after_summary=sanitize(after, secrets) if isinstance(after, dict) else None,
                               error=sanitize(error, secrets) if error else None)
            await self.ctx.store.append_audit(entry)
        except Exception as exc:  # noqa: BLE001 - auditing must never break the owner's chat
            logger.warning("agent audit write failed for %s: %s", tool_name, type(exc).__name__)

    async def run(self, name: str, raw_args: dict[str, Any] | None, *, source: str, chat_key: str,
                  confirmed: bool = False) -> ToolResult:
        self.ctx.source = source
        spec = self.registry.get(name)
        if spec is None or any(word in name for word in FORBIDDEN_TOOL_WORDS):
            await self._audit(source, name, "refused", {}, error="unknown_or_forbidden_tool")
            return refused(f"Unknown or disallowed tool: {name[:60]}. I never send email, delete data or "
                           "re-apply to a job.")
        try:
            args = spec.args_model.model_validate(raw_args or {})
        except ValidationError as exc:
            first = exc.errors()[0]
            message = f"Invalid {name} arguments: {'.'.join(str(p) for p in first['loc'])} {first['msg']}"
            await self._audit(source, name, "refused", raw_args if isinstance(raw_args, dict) else {}, error=message)
            return refused(message)
        if spec.guard is not None:
            reason = await spec.guard(self.ctx, args)
            if reason:
                await self._audit(source, name, "refused", _args_dict(args), error=reason)
                return refused(reason)
        if spec.kind == "read":
            return await self._read(spec, args)
        risk = "it cannot be undone from chat" if spec.risky else (
            await spec.assess(self.ctx, args) if spec.assess is not None else None)
        if risk and not confirmed:
            action = self.pending.add(chat_key, name, _args_dict(args), source, risk, self.ctx.clock())
            await self._audit(source, name, "needs_confirmation", action.args, error=risk)
            shown = h(json.dumps(sanitize(action.args, await self.ctx.secrets()), ensure_ascii=False), 600)
            return ToolResult(False, f"Needs confirmation: {risk}", {"token": action.token},
                              user_html=(f"⚠️ <b>Confirm {h(name, 60)}?</b> This {h(risk, 200)}.\n"
                                         f"<code>{shown}</code>\nTap Confirm (valid 10 min) or type "
                                         "<b>confirm</b>."),
                              llm_summary="needs_confirmation: the owner must tap Confirm or type confirm",
                              outcome="needs_confirmation", token=action.token)
        return await self._execute(spec, args, source)

    async def _read(self, spec: ToolSpec, args: BaseModel) -> ToolResult:
        try:
            return await spec.handler(self.ctx, args, False)
        except Exception as exc:  # noqa: BLE001 - a failed read is an observation, not a crash
            logger.warning("agent read tool %s failed: %s", spec.name, type(exc).__name__)
            return ToolResult(False, f"{spec.name} failed", llm_summary=f"error: {type(exc).__name__}",
                              outcome="error")

    async def _execute(self, spec: ToolSpec, args: BaseModel, source: str) -> ToolResult:
        before = await self._snapshot(spec, args)
        try:
            result = await spec.handler(self.ctx, args, True)
        except (GuardrailViolation, NeedsConfirmation) as exc:
            result = refused(str(exc))
        except FencedRowError as exc:
            result = refused(fence_reason(exc.state) or str(exc))
        except Exception as exc:  # noqa: BLE001 - report, audit, never crash the bot
            logger.warning("agent tool %s failed: %s", spec.name, type(exc).__name__)
            result = ToolResult(False, f"{spec.name} failed ({type(exc).__name__}); nothing else was changed.",
                                user_html=f"⚠️ {h(spec.name, 60)} failed ({h(type(exc).__name__, 60)}).",
                                llm_summary=f"error: {type(exc).__name__}", outcome="error")
        outcome = "ok" if result.ok else (result.outcome if result.outcome != "ok" else "error")
        result.outcome = outcome
        after = await self._snapshot(spec, args) if result.ok else None
        await self._audit(source, spec.name, outcome, _args_dict(args), before=before, after=after,
                          error=None if result.ok else result.message)
        if result.ok and self.ctx.event_bus is not None:
            try:
                await self.ctx.event_bus.publish("agent.action", {"tool": spec.name, "source": source})
            except Exception:  # noqa: BLE001, S110 - the event bus is best effort
                pass
        return result

    async def _snapshot(self, spec: ToolSpec, args: BaseModel) -> dict[str, Any] | None:
        if spec.snapshot is None:
            return None
        try:
            return await spec.snapshot(self.ctx, args)
        except Exception:  # noqa: BLE001 - summaries are best effort
            return None

    # --- confirmation flow ------------------------------------------------------------------------
    async def _expire(self) -> None:
        for action in self.pending.purge(self.ctx.clock()):
            await self._audit(action.source, action.tool_name, "cancelled", action.args, error="confirmation_expired")

    async def confirm(self, token: str | None, *, chat_key: str, source: str) -> ToolResult:
        await self._expire()
        action = self.pending.take(token, chat_key, self.ctx.clock())
        if action is None:
            return ToolResult(False, "Nothing to confirm (it expired after 10 minutes or was already handled).",
                              user_html="⌛ Nothing to confirm: it expired after 10 minutes or was already handled.",
                              llm_summary="nothing pending", outcome="cancelled")
        self.ctx.source = action.source
        spec = self.registry[action.tool_name]
        args = spec.args_model.model_validate(action.args)
        if spec.guard is not None:  # state may have changed while waiting (e.g. the job got applied)
            reason = await spec.guard(self.ctx, args)
            if reason:
                await self._audit(source, spec.name, "refused", action.args, error=reason)
                return refused(reason)
        return await self._execute(spec, args, source)

    async def cancel(self, token: str | None, *, chat_key: str, source: str) -> ToolResult:
        await self._expire()
        action = self.pending.take(token, chat_key, self.ctx.clock())
        if action is None:
            return ToolResult(False, "Nothing to cancel.", user_html="Nothing to cancel (already handled).",
                              outcome="cancelled")
        await self._audit(source, action.tool_name, "cancelled", action.args, error="cancelled_by_owner")
        return ToolResult(True, "Cancelled; nothing was changed.", user_html=f"✖️ Cancelled {h(action.tool_name, 60)};"
                          " nothing was changed.", outcome="cancelled")
