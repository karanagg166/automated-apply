"""LangGraph control agent (Phase 6A): owner free-text -> one guardrailed tool call.

    classify_intent -> plan_safe_tool_call -> validate_guardrails -> execute_tool -> format_reply
                                                     \\-- rejected / needs confirm --> format_reply

- Deterministic parser first; the free LLM router (task `agent_intent`) only proposes a
  call when the parser finds nothing. Guardrails validate every call either way.
- No send / delete / replay tool exists; such requests are refused in `validate_guardrails`.
- No Postgres checkpointer (would open extra Supabase connections): the graph is compiled
  without one, state lives for one turn in memory, and every effect is persisted through
  the caller's single v2 store connection (`SerializedConnection` in the worker).
- Runs as a background task from Telegram/dashboard: it never touches the browser, so an
  in-flight application is never interrupted; rule changes apply on the next cycle.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent_v2.intent import Intent, llm_parse, parse
from backend.app.agent_v2.tools import (
    AgentTools,
    GuardrailViolation,
    NeedsConfirmation,
    ToolResult,
)

logger = logging.getLogger(__name__)

HELP = ("I can change portal rules (\"raise Naukri daily limit to 60\", \"enable Instahyre\", \"pause Internshala "
        "for 3 hours\", \"set max job age to 5 days\"), preferences (\"blacklist TCS and Infosys\", \"set expected "
        "CTC to 18 LPA\", \"add FastAPI to required keywords\"), answer status questions (\"how many applied "
        "today?\", \"why did you skip Razorpay?\", \"why failed\", \"pending\", \"digest\", \"show last 5 drafts\"), "
        "toggle unknown posting dates (\"set instahyre allow_unknown_age true\"), remember answers (\"remember my notice "
        "period is immediate\") and control the worker (pause / resume / status / run once). I never send email, "
        "delete data or re-apply to a job.")
ALLOWED_TOOLS = frozenset({"update_portal_rule", "update_preferences", "query_application_status",
                           "teach_semantic_cache", "control_worker", "help"})
FORBIDDEN_ARG_KEYS = frozenset({"send", "send_email", "delete", "drop", "replay", "state", "applied_at", "receipt",
                                "auth_status", "revision", "portal_limit_hit_at"})


class AgentState(TypedDict, total=False):
    text: str
    now: datetime
    intent: Intent | None
    plan: dict[str, Any]
    verdict: str  # ok | rejected | confirm
    message: str
    result: ToolResult | None
    reply: str


class ControlAgent:
    def __init__(self, store: Any, *, ai: Any = None, mail_events: Any = None, event_bus: Any = None,
                 clock: Any = None) -> None:
        self.tools = AgentTools(store, ai=ai, mail_events=mail_events, clock=clock)
        self.router = getattr(ai, "router", None) if ai is not None else None
        self.event_bus = event_bus
        self.clock = clock or (lambda: datetime.now(UTC))
        self.graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("classify_intent", self.classify_intent)
        graph.add_node("plan_safe_tool_call", self.plan_safe_tool_call)
        graph.add_node("validate_guardrails", self.validate_guardrails)
        graph.add_node("execute_tool", self.execute_tool)
        graph.add_node("format_reply", self.format_reply)
        graph.add_edge(START, "classify_intent")
        graph.add_edge("classify_intent", "plan_safe_tool_call")
        graph.add_edge("plan_safe_tool_call", "validate_guardrails")
        graph.add_conditional_edges("validate_guardrails",
                                    lambda state: "execute_tool" if state.get("verdict") == "ok" else "format_reply",
                                    {"execute_tool": "execute_tool", "format_reply": "format_reply"})
        graph.add_edge("execute_tool", "format_reply")
        graph.add_edge("format_reply", END)
        return graph.compile()  # no checkpointer: zero extra DB connections

    # --- nodes -----------------------------------------------------------------------------
    async def classify_intent(self, state: AgentState) -> AgentState:
        text = state.get("text") or ""
        intent = parse(text, now=state.get("now"))
        if intent is None:
            try:
                intent = await llm_parse(self.router, text)
            except Exception as exc:  # noqa: BLE001 - offline / provider error: deterministic help
                logger.info("agent llm intent failed: %s", type(exc).__name__)
                intent = None
        return {"intent": intent or Intent("help", note="not_understood")}

    async def plan_safe_tool_call(self, state: AgentState) -> AgentState:
        intent = state["intent"]
        assert intent is not None
        args: dict[str, Any] = dict(intent.args)
        if intent.tool == "update_portal_rule":
            args["changes"] = dict(intent.args.get("changes") or {})
        text = state.get("text") or ""
        plan: dict[str, Any] = {"tool": intent.tool, "args": args, "source": intent.source,
                                "confirmed": intent.confirmed or "confirm" in text.lower()}
        return {"plan": plan}

    async def validate_guardrails(self, state: AgentState) -> AgentState:
        plan = state["plan"]
        tool = plan["tool"]
        if tool == "forbidden":
            return {"verdict": "rejected", "message": "⛔ " + str(plan["args"].get("reason") or "Not allowed.")}
        if tool not in ALLOWED_TOOLS:
            return {"verdict": "rejected", "message": "⛔ Unknown or disallowed action."}
        if tool == "help":
            return {"verdict": "help", "message": HELP}
        changes = plan["args"].get("changes") or {}
        if set(changes) & FORBIDDEN_ARG_KEYS:
            return {"verdict": "rejected",
                    "message": "⛔ Application state, receipts and auth status can't be changed from chat."}
        if tool == "update_portal_rule":
            from backend.app.agent_v2.tools import (
                resolve_platforms,
                validate_rule_changes,
            )

            try:
                names = resolve_platforms(plan["args"].get("platforms"))
                rules = {r.platform: r for r in await self.tools.store.list_rules()}
                validate_rule_changes(names, changes, rules, confirmed=plan["confirmed"])
            except NeedsConfirmation as exc:
                return {"verdict": "confirm", "message": "⚠️ " + str(exc)}
            except GuardrailViolation as exc:
                return {"verdict": "rejected", "message": "⛔ " + str(exc)}
        if tool == "update_preferences" and plan["args"].get("key") is None:
            return {"verdict": "rejected", "message": "⛔ Which preference?"}
        return {"verdict": "ok"}

    async def execute_tool(self, state: AgentState) -> AgentState:
        plan = state["plan"]
        args = plan["args"]
        try:
            if plan["tool"] == "update_portal_rule":
                result = await self.tools.update_portal_rule(args["platforms"], args["changes"],
                                                             confirmed=plan["confirmed"])
            elif plan["tool"] == "update_preferences":
                result = await self.tools.update_preferences(args.get("op", "set"), args.get("key"),
                                                             value=args.get("value"), values=args.get("values"))
            elif plan["tool"] == "teach_semantic_cache":
                result = await self.tools.teach_semantic_cache(args.get("question"), args.get("answer"))
            elif plan["tool"] == "control_worker":
                result = await self.tools.control_worker(args.get("action") or "status")
            else:
                result = await self.tools.query_application_status(
                    args.get("kind") or "counts", company=args.get("company"), platform=args.get("platform"),
                    limit=args.get("limit") or 5)
        except (GuardrailViolation, NeedsConfirmation) as exc:
            return {"result": ToolResult(False, "⛔ " + str(exc))}
        except Exception as exc:  # noqa: BLE001 - report, never crash the bot
            logger.warning("agent tool %s failed: %s", plan["tool"], type(exc).__name__)
            return {"result": ToolResult(False, f"⚠️ {plan['tool']} failed ({type(exc).__name__}).")}
        if result.ok and self.event_bus is not None and plan["tool"] in ("update_portal_rule", "update_preferences",
                                                                         "control_worker", "teach_semantic_cache"):
            try:
                await self.event_bus.publish("agent.action", {"tool": plan["tool"], "source": plan["source"]})
            except Exception:  # noqa: BLE001, S110
                pass
        return {"result": result}

    async def format_reply(self, state: AgentState) -> AgentState:
        result = state.get("result")
        if result is not None:
            text = ("✅ " if result.ok else "") + result.message if not result.message.startswith(("⛔", "⚠️")) \
                else result.message
        else:
            text = state.get("message") or HELP
        intent = state.get("intent")
        if intent is not None and intent.note == "not_understood" and result is None:
            text = "I didn't understand that. " + HELP
        return {"reply": text[:3500]}

    # --- entry ---------------------------------------------------------------------------------
    async def run(self, text: str) -> dict[str, Any]:
        final = await self.graph.ainvoke({"text": (text or "")[:2000], "now": self.clock()})
        intent = final.get("intent")
        result = final.get("result")
        return {"reply": final.get("reply") or HELP, "tool": intent.tool if intent else None,
                "source": intent.source if intent else None, "verdict": final.get("verdict"),
                "ok": bool(result.ok) if result is not None else final.get("verdict") == "help",
                "data": result.data if result is not None else {}}
