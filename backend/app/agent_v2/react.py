"""Provider-agnostic JSON ReAct agent on LangGraph (no checkpointer, no Send).

    load_context -> plan -> guard -> run_tool -> plan ... (<= 4 tool steps) -> compose_reply
                      \\-- providers exhausted / invalid twice --> END (failure: caller falls back)

- `plan` calls `LLMRouter.generate_json("agent_react", ...)` (the router PII-scrubs every prompt)
  and gets one `AgentStep`. Tool args are rehydrated locally (placeholders -> owner values) and
  run through the AuditedToolRunner; the LLM only sees each tool's compact `llm_summary`.
- The final Telegram text is the LLM's prose (HTML-escaped by the caller) plus the code-rendered
  `ToolResult.user_html` blocks: the LLM is never trusted to describe what changed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent_v2.prompts import (
    MAX_TOOL_STEPS,
    AgentStep,
    system_prompt,
    user_prompt,
)
from backend.app.agent_v2.tools import AuditedToolRunner
from backend.app.ai_v2.pii import rehydrate

logger = logging.getLogger(__name__)
HITL_TOOL = "resolve_hitl_via_agent"
MAX_INVALID_STEPS = 2


class ReactState(TypedDict, total=False):
    text: str  # placeholder-scrubbed owner message
    mapping: dict[str, str]
    chat_key: str
    source: str
    context: dict[str, Any]
    steps: list[dict[str, Any]]
    step: AgentStep | None
    route: str
    invalid: int
    blocks: list[str]
    tools: list[str]
    outcomes: list[str]
    resolutions: list[Any]
    confirmation: dict[str, Any] | None
    reply: str
    provider: str | None
    failure: str | None
    attempts: list[dict[str, Any]]


def provider_note(attempts: list[dict[str, Any]]) -> str:
    tried = [f"{a.get('provider')}: {a.get('outcome')}" for a in attempts
             if a.get("outcome") not in (None, "unconfigured")]
    return ("LLM providers unavailable (" + ", ".join(tried[:6]) + ")") if tried else \
        "no LLM provider is configured"


class ReactAgent:
    def __init__(self, router: Any, runner: AuditedToolRunner, *, load_context: Callable[..., Any],
                 secrets: tuple[str, ...] = (), clock: Callable[[], datetime] | None = None,
                 max_steps: int = MAX_TOOL_STEPS) -> None:
        self.router = router
        self.runner = runner
        self._load_context = load_context
        self.secrets = secrets
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_steps = max_steps
        self.system = system_prompt(runner.registry)
        self.graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(ReactState)
        graph.add_node("load_context", self.load_context)
        graph.add_node("plan", self.plan)
        graph.add_node("guard", self.guard)
        graph.add_node("run_tool", self.run_tool)
        graph.add_node("compose_reply", self.compose_reply)
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "plan")
        graph.add_conditional_edges("plan", lambda s: END if s.get("failure") else "guard",
                                    {END: END, "guard": "guard"})
        graph.add_conditional_edges("guard", lambda s: s.get("route") or "compose_reply",
                                    {"run_tool": "run_tool", "compose_reply": "compose_reply", "plan": "plan",
                                     "fail": END})
        graph.add_conditional_edges("run_tool", lambda s: "compose_reply" if s.get("confirmation") else "plan",
                                    {"compose_reply": "compose_reply", "plan": "plan"})
        graph.add_edge("compose_reply", END)
        return graph.compile()  # no checkpointer: zero extra DB connections

    # --- nodes ---------------------------------------------------------------------------------
    async def load_context(self, state: ReactState) -> ReactState:
        return {"context": await self._load_context(), "steps": [], "blocks": [], "tools": [], "outcomes": [],
                "resolutions": [], "invalid": 0, "confirmation": None, "failure": None}

    async def plan(self, state: ReactState) -> ReactState:
        from backend.app.ai_v2.router import AllLLMProvidersExhaustedError

        context = state.get("context") or {}
        prompt = user_prompt(state.get("text") or "", history=context.get("history") or [],
                             open_requests=context.get("open_requests") or [], profile=context.get("profile") or {},
                             steps=state.get("steps") or [], note=context.get("note"))
        try:
            result = await self.router.generate_json("agent_react", self.system, prompt, AgentStep,
                                                     extra_secrets=self.secrets, max_output_tokens=700)
        except AllLLMProvidersExhaustedError as exc:
            return {"failure": provider_note(exc.attempts), "attempts": exc.attempts}
        return {"step": result.value, "provider": result.provider}

    async def guard(self, state: ReactState) -> ReactState:
        step = state.get("step")
        steps = state.get("steps") or []
        if step is None or step.action == "final":
            return {"route": "compose_reply"}
        if not step.tool_name:
            invalid = int(state.get("invalid") or 0) + 1
            if invalid >= MAX_INVALID_STEPS:
                return {"route": "fail", "invalid": invalid, "failure": "the LLM returned invalid steps twice"}
            return {"route": "plan", "invalid": invalid,
                    "steps": [*steps, {"tool": None, "observation": "invalid step: tool_name is required"}]}
        if len(steps) >= self.max_steps:
            return {"route": "compose_reply"}
        return {"route": "run_tool"}

    async def run_tool(self, state: ReactState) -> ReactState:
        step = state["step"]
        assert step is not None and step.tool_name is not None
        args = rehydrate(step.tool_args, state.get("mapping") or {})
        result = await self.runner.run(step.tool_name, args, source=state.get("source") or "telegram",
                                       chat_key=state["chat_key"])
        observation = result.llm_summary or result.message
        update: ReactState = {
            "steps": [*(state.get("steps") or []), {"tool": step.tool_name, "args": step.tool_args,
                                                    "observation": observation}],
            "tools": [*(state.get("tools") or []), step.tool_name],
            "outcomes": [*(state.get("outcomes") or []), result.outcome],
            "blocks": [*(state.get("blocks") or []), *([result.user_html] if result.user_html else [])]}
        resolution = result.data.get("resolution") if isinstance(result.data, dict) else None
        if resolution is not None:
            update["resolutions"] = [*(state.get("resolutions") or []), resolution]
        if result.outcome == "needs_confirmation":
            update["confirmation"] = {"token": result.token, "tool": step.tool_name}
        return update

    async def compose_reply(self, state: ReactState) -> ReactState:
        step = state.get("step")
        if state.get("confirmation"):
            reply = (step.reply if step is not None and step.action == "final" else "") or \
                "That change needs your confirmation first."
        elif step is not None and step.action == "final":
            reply = step.reply or "Done."
        else:
            reply = f"I stopped after {len(state.get('steps') or [])} tool steps; here is what I found so far."
        return {"reply": rehydrate(reply, state.get("mapping") or {})}

    async def run(self, text: str, *, mapping: dict[str, str], chat_key: str, source: str) -> ReactState:
        final: ReactState = await self.graph.ainvoke(
            {"text": text, "mapping": mapping, "chat_key": chat_key, "source": source}, {"recursion_limit": 40})
        return final
