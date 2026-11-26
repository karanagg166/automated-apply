"""Prompts and the JSON step schema for the provider-agnostic ReAct agent (task `agent_react`).

The catalog goes into the system prompt (one line per tool); the user prompt is one JSON
object (message, history, open requests, safe profile, observations) kept under the router's
8000-character cap by dropping the oldest history first.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.agent_v2.tools import TOOL_REGISTRY, ToolSpec

MAX_TOOL_STEPS = 4
HISTORY_TURNS = 12
USER_PROMPT_BUDGET = 7600
OBSERVATION_CHARS = 1200

RULES = (
    "You are the owner's job-application control agent (Telegram). Answer with ONE JSON object only: "
    '{"thought": "<=300 chars", "action": "tool" or "final", "tool_name": "...", "tool_args": {...}, '
    '"reply": "<=1500 chars"}. Read facts with tools before answering; never invent numbers. One tool per step, '
    f"at most {MAX_TOOL_STEPS} tool steps, then action=final. Write tools change real settings; a "
    "needs_confirmation observation means: tell the owner to tap Confirm. Impossible by design: sending email, "
    "deleting data, re-applying or touching APPLIED/SUBMISSION_UNKNOWN jobs - refuse with action=final. "
    "Placeholders like [PHONE_1], [EMAIL_1], [CODE_1] stand for values the owner typed: copy them verbatim "
    "into tool_args. If the message answers an open request, call resolve_hitl_via_agent with its ref; if it "
    "is unclear which request, ask. reply: short plain text (no HTML); the system appends what changed.")


SHORT_TYPES = {"string": "str", "integer": "int", "boolean": "bool", "object": "obj", "array": "list", "null": ""}


def _short(kind: str) -> str:
    optional = kind.endswith("?")
    parts = [SHORT_TYPES.get(p, p) for p in kind.rstrip("?").split("/")]
    text = "/".join(p for p in parts if p) or "any"
    if text.count("|") > 6:  # long enums (application states) are listed in the description instead
        text = "enum"
    return text + ("?" if optional else "")


def catalog_line(spec: ToolSpec) -> str:
    entry = spec.catalog_entry()
    args = ", ".join(f"{k}:{_short(v)}" for k, v in entry["args"].items())
    flag = "write, may need confirm" if entry["risky"] else entry["kind"]
    return f"- {spec.name}({args}) [{flag}]: {spec.description}"


def system_prompt(registry: dict[str, ToolSpec] | None = None) -> str:
    tools = "\n".join(catalog_line(spec) for spec in (registry or TOOL_REGISTRY).values())
    return f"{RULES}\nTools:\n{tools}"


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    thought: str = Field(default="", max_length=300)
    action: Literal["tool", "final"]
    tool_name: str | None = Field(default=None, max_length=60)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    reply: str = Field(default="", max_length=1500)

    @field_validator("thought", mode="before")
    @classmethod
    def _thought(cls, value: Any) -> Any:
        return _clip(value or "", 300)

    @field_validator("reply", mode="before")
    @classmethod
    def _reply(cls, value: Any) -> Any:
        return _clip(value or "", 1500)

    @field_validator("tool_args", mode="before")
    @classmethod
    def _args(cls, value: Any) -> Any:
        return value if isinstance(value, dict) else {}


def user_prompt(message: str, *, history: list[dict[str, str]], open_requests: list[dict[str, Any]],
                profile: dict[str, Any], steps: list[dict[str, Any]], note: str | None = None) -> str:
    history = [{"role": t["role"], "content": _clip(t["content"], 400)} for t in history[-HISTORY_TURNS:]]
    observed = [dict(s, observation=_clip(s.get("observation"), OBSERVATION_CHARS)) for s in steps]
    while True:
        payload: dict[str, Any] = {"message": _clip(message, 1500), "history": history,
                                   "open_requests": open_requests[:8], "profile": profile,
                                   "steps_so_far": observed, "tool_steps_left": MAX_TOOL_STEPS - len(steps)}
        if note:
            payload["note"] = note
        text = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
        if len(text) <= USER_PROMPT_BUDGET:
            return text
        if history:
            history = history[1:]
        elif any(len(str(s.get("observation") or "")) > 300 for s in observed):
            observed = [dict(s, observation=_clip(s.get("observation"), 300)) for s in observed]
        elif profile:
            profile = {}
        else:
            return text[:USER_PROMPT_BUDGET]
