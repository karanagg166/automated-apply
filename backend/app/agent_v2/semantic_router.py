"""Zero-LLM fast path in front of the ReAct agent (owner chat on every channel).

    Tier A  pleasantry regex (hi / thanks / bye / how are you / are you there) -> canned reply
            + a one-line live status. The ONLY tier allowed while a QUESTION/OTP request is open,
            and it never resolves one (a greeting is never an answer).
    Tier B  `intent.parse` found a READ-ONLY intent (status counts, pending, failures, why,
            drafts, digest, worker status, help) -> run that read directly. Writes, forbidden
            requests and anything unparsed fall through, so confirmations are never bypassed.
    Tier C  local-embedding nearest neighbour (bge-small, CPU, off the event loop) over labelled
            example utterances; only read-only routes, score >= THRESHOLD with a MARGIN over the
            runner-up route. Skipped silently when no embedder is available.
    else    None -> the caller runs the ReAct agent unchanged.

Each answered message saves at least one `agent_react` LLM call (`STATS`).
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import weakref
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.agent_v2.intent import Intent, parse, portals_in
from backend.app.ai_v2.embeddings import Embedder, FastEmbedder, cosine

logger = logging.getLogger(__name__)
THRESHOLD = 0.84  # bge-small: paraphrases score 0.84-0.95, unrelated owner requests 0.55-0.80
MARGIN = 0.04  # best route must beat the runner-up route by this much
STATUS_TIMEOUT_SEC = 1.5
MAX_WORDS_B = 12
MAX_WORDS_C = 10
# A longer message, or one asking for a change, is more than a status read ("the last question was
# wrong, change it to 30 days" parses as "list questions"): the agent handles it.
_CHANGE_WORDS = re.compile(r"\b(?:change|set|update|edit|fix|add|remove|pause|resume|stop|start|enable|disable|"
                           r"apply|answer|use|make|tell|wrong|instead|should)\b", re.IGNORECASE)
STATS: Counter[str] = Counter()  # "A:greeting" -> answered count == agent_react calls saved (at least)

_FILLER = r"(?: (?:there|bot|buddy|bro|man|dude|mate|boss|again|all|everyone))*"
_PLEASANTRY_BODIES = (
    ("presence", r"(?:are|r) (?:you|u) (?:there|alive|awake|up|online|around|working)|(?:you|u) there|"
                 r"anyone (?:there|home)|ping|still alive|alive"),
    ("wellbeing", r"how (?:are|r) (?:you|u|things)(?: doing| today)?|how(?:'?s| is) it going|how (?:you|u) doing|"
                  r"(?:you|u) (?:good|ok|okay)|wh?at'?s up|wassup|sup"),
    ("greeting", r"h+i+|h+e+y+|heya|he+l+o+|hiya|howdy|yo+|namaste|hola|gm|"
                 r"good (?:morning|afternoon|evening|day)"),
    ("thanks", r"thanks?(?: you)?(?: so much| a lot| again)?|thank u|thx|ty|tysm|much appreciated|appreciate it"),
    ("bye", r"bye+|good ?bye|good ?night|gn|see (?:you|ya)(?: later| soon)?|cya|ttyl|talk (?:to you )?later"),
)
PLEASANTRIES = tuple((name, re.compile(rf"(?:{body}){_FILLER}")) for name, body in _PLEASANTRY_BODIES)
_RANK = {"presence": 0, "wellbeing": 1, "greeting": 2, "thanks": 3, "bye": 4}
REPLIES: dict[str, tuple[str, ...]] = {
    "greeting": ("👋 Hi! I'm here.", "👋 Hey! Good to hear from you.", "👋 Hello! Ready when you are."),
    "wellbeing": ("😊 Doing well, thanks for asking!", "🙂 All good here, busy applying for you."),
    "presence": ("✅ Yes, I'm here and listening.", "✅ Online and listening."),
    "thanks": ("🙏 Anytime!", "😊 Happy to help.", "👍 You're welcome!"),
    "bye": ("👋 Bye! I'll keep applying in the background.", "🌙 Talk later; I'll ping you if anything needs you."),
}
HINT = "Try <i>status</i>, <i>pending</i> or <i>how many applied today?</i>"

# Tier C: read-only routes only. Each maps to a canned pleasantry or one AgentTools read.
EXAMPLES: dict[str, tuple[str, ...]] = {
    "greeting": ("hi there", "hello bot", "hey what's up", "good morning", "how are you doing", "are you there",
                 "you awake"),
    "status": ("what's the status", "is the worker running", "how is the bot doing", "give me a status update",
               "what are you doing right now", "is everything working"),
    "applied_today": ("how many jobs did you apply to today", "how many applications today",
                      "today's application count", "how many did you apply", "count of applications today"),
    "pending": ("what's pending", "any questions for me", "do you need anything from me", "open requests",
                "anything waiting for me"),
    "help": ("what can you do", "help me", "show commands", "how do I use you"),
    "recent": ("show my recent applications", "which jobs did you apply to", "list the latest applications",
               "what did you apply to recently"),
    "failed": ("what failed", "show failed applications", "why did applications fail", "any errors"),
}
ROUTE_INTENTS: dict[str, Intent] = {
    "status": Intent("control_worker", {"action": "status"}),
    "applied_today": Intent("query_application_status", {"kind": "counts"}),
    "pending": Intent("query_application_status", {"kind": "hitl", "limit": 10}),
    "help": Intent("help"),
    "recent": Intent("query_application_status", {"kind": "applications", "limit": 5}),
    "failed": Intent("query_application_status", {"kind": "failed", "limit": 5}),
}
# embedder -> [(route, vector)]; computed once per embedder (the shared FastEmbedder lives all process long)
_example_vectors: weakref.WeakKeyDictionary[Any, list[tuple[str, list[float]]]] = weakref.WeakKeyDictionary()
_downloaded: dict[str, bool] = {}


@dataclass(frozen=True)
class Routed:
    tier: str  # A | B | C
    route: str
    reply_html: str
    tool: str | None = None
    remember: bool = True  # pleasantries stay out of the 12-turn agent memory (fewer prompt tokens)


def _normalize(text: str) -> str:
    text = re.sub(r"[^\w\s']+", " ", (text or "").lower().replace("’", "'"))
    return " ".join(text.split())


def pleasantry(text: str) -> str | None:
    """Route name when EVERY clause of `text` is a pleasantry ("hi, how are you?"), else None."""
    clauses = [_normalize(c) for c in re.split(r"[,.!?;\n]+", text or "")]
    clauses = [c for c in clauses if c]
    if not clauses or len(" ".join(clauses).split()) > 8:
        return None
    found = []
    for clause in clauses:
        name = next((n for n, pattern in PLEASANTRIES if pattern.fullmatch(clause)), None)
        if name is None:
            return None
        found.append(name)
    return min(found, key=_RANK.__getitem__)


def read_only(intent: Intent | None) -> bool:
    if intent is None:
        return False
    return intent.tool in ("query_application_status", "help") or (
        intent.tool == "control_worker" and intent.args.get("action") == "status")


def routing_embedder(ai: Any) -> Embedder | None:
    """The semantic cache's local FastEmbedder, only when its model is already on disk (the chat path
    never downloads ~80 MB). Other embedders (test fakes) are opted in explicitly by the caller."""
    embedder = getattr(getattr(ai, "cache", None), "embedder", None)
    if not isinstance(embedder, FastEmbedder):
        return None
    if embedder.ready:
        return embedder
    key = str(embedder.cache_dir)
    if key not in _downloaded:
        _downloaded[key] = embedder.downloaded()
    return embedder if _downloaded[key] else None


class SemanticRouter:
    def __init__(self, tools: Any, *, help_text: str, embedder: Embedder | None = None,
                 clock: Callable[[], datetime] | None = None, threshold: float = THRESHOLD,
                 margin: float = MARGIN, rng: random.Random | None = None) -> None:
        self.tools = tools  # AgentTools (legacy deterministic tools); only its READ methods are called
        self.help_text = help_text
        self.embedder = embedder
        self.clock = clock or (lambda: datetime.now(UTC))
        self.threshold = threshold
        self.margin = margin
        self.rng = rng or random.Random()  # noqa: S311 - reply variety, not security

    async def route(self, text: str, *, hitl_open: bool) -> Routed | None:
        text = (text or "").strip()
        if not text:
            return None
        routed = await self._tier_a(text)
        if routed is None and not hitl_open:  # an open question may be answered by any other text
            intent = parse(text, now=self.clock())
            if intent is None or read_only(intent):  # a parsed write / forbidden request is the agent's
                routed = await self._tier_b(text, intent) or await self._tier_c(text)
        if routed is not None:
            STATS[f"{routed.tier}:{routed.route}"] += 1
            logger.info("semantic_router tier=%s route=%s llm_calls_saved_total=%d", routed.tier, routed.route,
                        sum(STATS.values()))
        return routed

    # --- tiers -------------------------------------------------------------------------------------
    async def _tier_a(self, text: str) -> Routed | None:
        name = pleasantry(text)
        return await self._canned(name, "A") if name else None

    async def _tier_b(self, text: str, intent: Intent | None) -> Routed | None:
        if intent is None or len(text.split()) > MAX_WORDS_B or _CHANGE_WORDS.search(text) or not text.strip("/? "):
            return None
        return await self._read(intent, "B", str(intent.args.get("kind") or intent.args.get("action") or intent.tool))

    async def _tier_c(self, text: str) -> Routed | None:
        if self.embedder is None or portals_in(text) or re.search(r"\d", text) or len(text.split()) > MAX_WORDS_C:
            return None  # numbers / portal names carry arguments a canned route would drop
        try:
            examples = await self._examples()
            vector = await self.embedder.embed(_normalize(text))  # FastEmbedder: asyncio.to_thread
        except Exception as exc:  # noqa: BLE001 - embedder unavailable: tier C is optional
            logger.info("semantic_router tier C skipped: %s", type(exc).__name__)
            return None
        best: dict[str, float] = {}
        for route, example in examples:
            best[route] = max(best.get(route, -1.0), cosine(vector, example))
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < self.threshold or (
                len(ranked) > 1 and ranked[0][1] - ranked[1][1] < self.margin):
            return None
        route = ranked[0][0]
        if route == "greeting":
            return await self._canned("greeting", "C")
        return await self._read(ROUTE_INTENTS[route], "C", route)

    async def _examples(self) -> list[tuple[str, list[float]]]:
        assert self.embedder is not None
        cached = _example_vectors.get(self.embedder)
        if cached is None:
            cached = [(route, await self.embedder.embed(example))
                      for route, examples in EXAMPLES.items() for example in examples]
            _example_vectors[self.embedder] = cached
        return cached

    # --- replies ----------------------------------------------------------------------------------
    async def _canned(self, name: str, tier: str) -> Routed:
        reply = self.rng.choice(REPLIES[name])
        if name in ("greeting", "wellbeing", "presence"):
            line = await self.status_line()
            reply += f"\n<i>{html.escape(line, quote=False)}</i>" if line else ""
            reply += f"\n{HINT}" if name == "greeting" else ""
        return Routed(tier, name, reply, remember=False)

    async def _read(self, intent: Intent, tier: str, route: str) -> Routed | None:
        args = intent.args
        try:
            if intent.tool == "help":
                message = self.help_text
            elif intent.tool == "control_worker":
                message = (await self.tools.control_worker("status")).message
            else:
                result = await self.tools.query_application_status(
                    args.get("kind") or "counts", company=args.get("company"), platform=args.get("platform"),
                    limit=args.get("limit") or 5)
                message = result.message
        except Exception as exc:  # noqa: BLE001 - "Which company?" etc.: let the agent handle it
            logger.info("semantic_router read %s fell through: %s", route, type(exc).__name__)
            return None
        return Routed(tier, route, html.escape(message, quote=False), tool=intent.tool)

    async def status_line(self) -> str:
        """`Worker RUNNING · 3 applied today · 1 waiting for you` (empty on any error / slow store)."""
        # Shielded: a slow store query is never cancelled mid-flight on the worker's shared connection.
        task = asyncio.ensure_future(self._status_line())
        try:
            return await asyncio.wait_for(asyncio.shield(task), STATUS_TIMEOUT_SEC)
        except Exception as exc:  # noqa: BLE001 - a greeting never fails because of the status line
            task.add_done_callback(lambda done: done.cancelled() or done.exception())
            logger.info("semantic_router status line skipped: %s", type(exc).__name__)
            return ""

    async def _status_line(self) -> str:
        from backend.app.browser_v2.service import day_start

        store, now = self.tools.store, self.clock()
        control = await store.get_worker_control()
        applied = 0
        for rules in await store.list_rules():
            if rules.enabled:
                applied += await store.applied_since(rules.platform, day_start(rules, now))
        waiting = await store.count_open_hitl()
        state = str(control.observed_state or "OFFLINE")
        desired = getattr(control.desired_state, "value", control.desired_state)
        if desired == "PAUSED" and state != "PAUSED":
            state += " (pause requested)"
        parts = [f"Worker {state}", f"{applied} applied today"]
        if waiting:
            parts.append(f"{waiting} waiting for you")
        return " · ".join(parts)


__all__ = ["EXAMPLES", "STATS", "THRESHOLD", "Routed", "SemanticRouter", "pleasantry", "read_only",
           "routing_embedder"]
