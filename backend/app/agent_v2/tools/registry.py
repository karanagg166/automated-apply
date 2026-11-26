"""The agent tool registry: every READ and WRITE ToolSpec, name-checked against the guardrails."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.app.agent_v2.tools.guardrails import check_tool_name
from backend.app.agent_v2.tools.read_tools import READ_SPECS
from backend.app.agent_v2.tools.spec import ToolSpec
from backend.app.agent_v2.tools.write_profile import PROFILE_SPECS
from backend.app.agent_v2.tools.write_queue import QUEUE_SPECS
from backend.app.agent_v2.tools.write_tools import OPS_SPECS
from backend.app.browser_v2.store.agent_records import TOOL_NAME

ALL_SPECS: tuple[ToolSpec, ...] = (*READ_SPECS, *PROFILE_SPECS, *OPS_SPECS, *QUEUE_SPECS)


def build_registry(specs: Iterable[ToolSpec] = ALL_SPECS) -> dict[str, ToolSpec]:
    registry: dict[str, ToolSpec] = {}
    for spec in specs:
        check_tool_name(spec.name)
        if not TOOL_NAME.match(spec.name) or spec.name in registry:
            raise ValueError(f"invalid or duplicate tool name: {spec.name}")
        registry[spec.name] = spec
    return registry


TOOL_REGISTRY = build_registry()
READ_TOOL_NAMES = frozenset(name for name, spec in TOOL_REGISTRY.items() if spec.kind == "read")
WRITE_TOOL_NAMES = frozenset(name for name, spec in TOOL_REGISTRY.items() if spec.kind == "write")


def catalog(registry: dict[str, ToolSpec] | None = None) -> list[dict[str, Any]]:
    return [spec.catalog_entry() for spec in (registry or TOOL_REGISTRY).values()]
