"""Typed, guardrailed, audited tools for the control agent (Phase 6A deterministic tools + the
Phase 9C LLM-agent registry). There is no send, mail, delete or replay tool at all.

Layout: `base` (ToolResult, errors, rule validation), `agent_tools` (Phase 6A AgentTools),
`spec` (ToolSpec / ToolContext), `args` (Pydantic args), `guardrails`, `read_tools`,
`write_profile` / `write_tools` / `write_queue` (WRITE tools), `registry`, `audit` (runner).
"""

from __future__ import annotations

from backend.app.agent_v2.tools.agent_tools import AgentTools
from backend.app.agent_v2.tools.audit import (
    PENDING,
    AuditedToolRunner,
    PendingAction,
    PendingConfirmations,
)
from backend.app.agent_v2.tools.base import (
    CONFIRM_DAILY_ABOVE,
    PREFERENCE_LISTS,
    PREFERENCE_SCALARS,
    GuardrailViolation,
    NeedsConfirmation,
    ToolResult,
    _show,
    resolve_platforms,
    validate_rule_changes,
)
from backend.app.agent_v2.tools.registry import (
    READ_TOOL_NAMES,
    TOOL_REGISTRY,
    WRITE_TOOL_NAMES,
    build_registry,
    catalog,
)
from backend.app.agent_v2.tools.spec import ProfileSync, ToolContext, ToolSpec

__all__ = [
    "CONFIRM_DAILY_ABOVE",
    "PENDING",
    "PREFERENCE_LISTS",
    "PREFERENCE_SCALARS",
    "READ_TOOL_NAMES",
    "TOOL_REGISTRY",
    "WRITE_TOOL_NAMES",
    "AgentTools",
    "AuditedToolRunner",
    "GuardrailViolation",
    "NeedsConfirmation",
    "PendingAction",
    "PendingConfirmations",
    "ProfileSync",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "_show",
    "build_registry",
    "catalog",
    "resolve_platforms",
    "validate_rule_changes",
]
