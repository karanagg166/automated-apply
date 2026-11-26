"""ToolSpec (one typed, audited agent tool) and the ToolContext every handler receives."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from backend.app.agent_v2.tools.agent_tools import AgentTools
from backend.app.agent_v2.tools.base import ToolResult


class ProfileSync(Protocol):
    """Portal profile sync (built in Stage 9D). Dry runs report per-field diffs only."""

    async def sync(self, portals: list[str], *, dry_run: bool, trigger: str) -> dict[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ToolContext:
    store: Any
    ai: Any = None
    mail_events: Any = None
    event_bus: Any = None
    clock: Callable[[], datetime] = _utc_now
    wake: Callable[[], Any] | None = None
    profile_sync: ProfileSync | None = None
    source: str = "telegram"  # set by the runner per call: telegram | api | mcp | cli | worker
    _legacy: AgentTools | None = field(default=None, repr=False)

    @property
    def cache(self) -> Any:
        return getattr(self.ai, "cache", None) if self.ai is not None else None

    @property
    def legacy(self) -> AgentTools:
        """The Phase 6A tools (portal-rule update loop, preference merge, worker control, status)."""
        if self._legacy is None:
            self._legacy = AgentTools(self.store, ai=self.ai, mail_events=self.mail_events, clock=self.clock)
        return self._legacy

    def hitl(self) -> Any:
        from backend.app.browser_v2.hitl import HITLResolutionService

        return HITLResolutionService(self.store, self.cache, clock=self.clock)

    async def secrets(self) -> list[str]:
        """Owner identifiers scrubbed from audit summaries."""
        from backend.app.ai_v2.pii import profile_secrets

        try:
            profile, _ = await self.store.load_profile()
        except Exception:  # noqa: BLE001 - no profile yet
            return []
        return profile_secrets(profile or {})

    async def notify_wake(self) -> bool:
        if self.wake is None:
            return False
        try:
            result = self.wake()
            if isinstance(result, Awaitable):
                await result
            return True
        except Exception:  # noqa: BLE001 - a wake-up is best effort
            return False


Handler = Callable[[ToolContext, Any, bool], Awaitable[ToolResult]]
Check = Callable[[ToolContext, Any], Awaitable[str | None]]
Snapshot = Callable[[ToolContext, Any], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    kind: Literal["read", "write"]
    handler: Handler
    risky: bool = False  # always needs an explicit confirmation
    assess: Check | None = None  # conditional risk: a reason string means "confirm first"
    guard: Check | None = None  # agent guardrail: a reason string means "refuse"
    snapshot: Snapshot | None = None  # before/after summary for the audit log

    def catalog_entry(self) -> dict[str, Any]:
        """Compact description for the LLM prompt: name, kind and argument names/types."""
        schema = self.args_model.model_json_schema()
        props = {}
        for name, prop in (schema.get("properties") or {}).items():
            options = [prop, *prop.get("anyOf", [])]
            enum = next((o["enum"] for o in options if "enum" in o), None)
            kind = "|".join(str(v) for v in enum) if enum else prop.get("type") or "/".join(
                str(o.get("type") or "any") for o in prop.get("anyOf", [])) or "any"
            props[name] = kind if name in schema.get("required", []) else kind + "?"
        return {"name": self.name, "kind": self.kind, "risky": self.risky or self.assess is not None,
                "description": self.description, "args": props}


def h(value: Any, limit: int = 300) -> str:
    """HTML-escape a value for code-rendered Telegram blocks."""
    text = str(value if value is not None else "—")
    return html.escape(text if len(text) <= limit else text[: limit - 1] + "…", quote=False)


def refused(message: str) -> ToolResult:
    return ToolResult(False, message, user_html=f"⛔ {h(message, 500)}", llm_summary=f"refused: {message}",
                      outcome="refused")
