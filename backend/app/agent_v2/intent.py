"""Owner free-text -> one typed tool call. Deterministic parser first (0 tokens, works
offline / keyless); the free LLM router (task `agent_intent`, PII-scrubbed) only when the
parser finds nothing. The LLM can only *propose* a call: guardrails validate everything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal["update_portal_rule", "update_preferences", "query_application_status", "teach_semantic_cache",
                   "control_worker", "help", "forbidden"]

PORTAL_ALIASES: dict[str, str] = {
    "naukri": "naukri", "instahyre": "instahyre", "internshala": "internshala", "wellfound": "wellfound",
    "angellist": "wellfound", "angel list": "wellfound", "work at a startup": "work_at_a_startup",
    "workatastartup": "work_at_a_startup", "waas": "work_at_a_startup", "yc": "work_at_a_startup",
    "himalayas": "himalayas", "we work remotely": "we_work_remotely", "weworkremotely": "we_work_remotely",
    "wwr": "we_work_remotely", "hiringcafe": "hiringcafe", "hiring cafe": "hiringcafe",
    "greenhouse": "greenhouse", "lever": "lever",
}
PORTAL_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(a) for a in PORTAL_ALIASES), key=len, reverse=True))
                       + r")\b", re.IGNORECASE)
NUMBER = r"(\d{1,6}(?:\.\d+)?)"

FORBIDDEN = [
    (re.compile(r"\b(?:send|deliver|dispatch|fire off|shoot)\b.{0,40}\b(?:e-?mails?|mails?|drafts?|messages? to)\b|"
                r"\be-?mail\b.{0,30}\b(?:the )?(?:recruiter|hr|hiring)\b|\bsmtp\b", re.IGNORECASE),
     "Email sending is disabled by design: Gmail is READ + DRAFT ONLY. Drafts wait in Gmail Drafts for you."),
    (re.compile(r"\b(?:delete|drop|truncate|wipe|erase|purge|clear)\b.{0,40}\b(?:data|database|applications?|jobs?|"
                r"history|table|rows?|records?|cache|drafts?|everything|all)\b", re.IGNORECASE),
     "I can't delete data. Use the dashboard for curated, reviewable changes."),
    (re.compile(r"\b(?:re-?apply|apply again|replay|resubmit|retry)\b.{0,40}\b(?:applied|submitted|submission|"
                r"same job|already)\b|\b(?:re-?apply|apply again)\b", re.IGNORECASE),
     "Never-replay guardrail: APPLIED and SUBMISSION_UNKNOWN jobs are never applied to again."),
]


@dataclass
class Intent:
    tool: ToolName
    args: dict[str, Any] = field(default_factory=dict)
    source: str = "deterministic"  # deterministic | llm
    note: str | None = None
    confirmed: bool = False


def portals_in(text: str) -> list[str]:
    return list(dict.fromkeys(PORTAL_ALIASES[m.group(1).lower()] for m in PORTAL_RE.finditer(text)))


def _num(value: str) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number


def _split_items(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|\band\b|&|/)\s*", text.strip().strip(".!"))
    return [p.strip().strip("\"'") for p in parts if p.strip().strip("\"'")][:20]


RULE_FIELDS = (
    (re.compile(r"\b(?:daily|per day|a day|each day|day)\b.{0,15}\b(?:limit|cap|max(?:imum)?|applications?)|"
                r"\b(?:limit|cap)\b.{0,10}\b(?:daily|per day|a day)", re.IGNORECASE), "max_applies_per_day"),
    (re.compile(r"\b(?:hourly|per hour|an hour|each hour)\b", re.IGNORECASE), "max_applies_per_hour"),
    (re.compile(r"\b(?:job age|posting age|age of jobs?|jobs? older than|max(?:imum)? age)\b", re.IGNORECASE), "max_job_age_days"),
    (re.compile(r"\bapplicants?\b", re.IGNORECASE), "max_applicants"),
    (re.compile(r"\b(?:fallback|draft)s?\b.{0,20}\b(?:daily|per day|cap)\b", re.IGNORECASE), "quota_fallback_daily_cap"),
    (re.compile(r"\bdrafts? per cycle\b", re.IGNORECASE), "quota_drafts_per_cycle"),
    # Phase 8: a bare "limit"/"cap" ("set naukri limit 60") means the daily cap.
    (re.compile(r"\b(?:limit|cap|max(?:imum)? applications?)\b", re.IGNORECASE), "max_applies_per_day"),
)
BOOL_WORDS = {"true": True, "on": True, "yes": True, "enable": True, "enabled": True, "allow": True,
              "false": False, "off": False, "no": False, "disable": False, "disabled": False, "block": False}
UNKNOWN_AGE = re.compile(r"\ballow[_ ]unknown[_ ](?:posting[_ ])?age\b\s*(?:=|to|:)?\s*"
                         r"(true|false|on|off|yes|no|enabled?|disabled?)?", re.IGNORECASE)
UNKNOWN_AGE_NATURAL = re.compile(r"\b(allow|accept|block|reject|skip|disallow)\b.{0,25}\b(?:unknown|missing|no)\b"
                                 r".{0,15}\b(?:posting )?(?:age|date)s?\b", re.IGNORECASE)


def parse(text: str, *, now: datetime | None = None) -> Intent | None:
    """Deterministic parse. None = not understood (LLM fallback may try)."""
    raw = " ".join((text or "").split())
    lowered = raw.lower()
    now = now or datetime.now(UTC)
    confirmed = bool(re.search(r"\b(?:confirm(?:ed)?|yes,? do it|i'?m sure)\b", lowered))
    if not raw:
        return Intent("help")
    for pattern, message in FORBIDDEN:
        if pattern.search(raw):
            return Intent("forbidden", {"reason": message})
    if re.fullmatch(r"(?:/?help|\?|what can you do\??|commands?)", lowered):
        return Intent("help")
    portals = portals_in(raw)

    # --- Phase 8 one-word queries -------------------------------------------------------------
    if re.fullmatch(r"(?:show )?(?:pending|open (?:questions|requests|hitl)|what(?:'s| is) pending)\??", lowered):
        return Intent("query_application_status", {"kind": "hitl", "limit": 10})
    if re.fullmatch(r"(?:send |show )?(?:the |today'?s? )?(?:daily )?digest(?: now)?\??", lowered):
        return Intent("query_application_status", {"kind": "digest"})
    if re.fullmatch(r"why (?:did (?:it|they|jobs?|applications?) )?fail(?:ed|ing|ures?)?\??|"
                    r"(?:show |list )?(?:recent |last )?(?:failures|failed(?: jobs| applications)?)\??", lowered):
        return Intent("query_application_status", {"kind": "failed", "limit": 5,
                                                   "platform": portals[0] if portals else None})

    # --- Phase 8: allow_unknown_posting_age ---------------------------------------------------
    match = UNKNOWN_AGE.search(raw)
    if match and portals:
        word = (match.group(1) or "true").lower()
        return Intent("update_portal_rule", {"platforms": portals,
                                             "changes": {"allow_unknown_posting_age": BOOL_WORDS.get(word, True)}},
                      confirmed=confirmed)
    match = UNKNOWN_AGE_NATURAL.search(raw)
    if match and portals:
        return Intent("update_portal_rule", {"platforms": portals, "changes": {
            "allow_unknown_posting_age": match.group(1).lower() in {"allow", "accept"}}}, confirmed=confirmed)

    # --- teach the semantic cache -----------------------------------------------------------
    match = re.match(r"^(?:please )?remember(?: that)?:?\s+(?:my |the )?(.+?)\s+(?:is|are|=|:)\s+(.+)$", raw, re.IGNORECASE)
    if match:
        subject, answer = match.group(1).strip(" ?"), match.group(2).strip(" .")
        question = subject if subject.endswith("?") or len(subject.split()) > 6 else f"What is your {subject}?"
        return Intent("teach_semantic_cache", {"question": question, "answer": answer})
    match = re.match(r"^(?:please )?remember:?\s+(.+?\?)\s*(.+)$", raw, re.IGNORECASE)
    if match:
        return Intent("teach_semantic_cache", {"question": match.group(1).strip(), "answer": match.group(2).strip()})

    # --- worker control (no portal named) ------------------------------------------------------
    if not portals:
        if re.fullmatch(r"(?:please )?(?:pause|stop applying|hold|pause (?:the )?(?:worker|bot|everything|all))\.?",
                        lowered):
            return Intent("control_worker", {"action": "pause"})
        if re.fullmatch(r"(?:please )?(?:resume|unpause|start|continue|go|resume (?:the )?(?:worker|bot|applying))\.?",
                        lowered):
            return Intent("control_worker", {"action": "resume"})
        if re.search(r"\b(?:run (?:once|now|a cycle)|run one cycle|do a cycle now)\b", lowered):
            return Intent("control_worker", {"action": "run_once"})
        if re.fullmatch(r"(?:worker )?status\??|how(?:'s| is) (?:the )?(?:worker|bot)(?: doing)?\??", lowered):
            return Intent("control_worker", {"action": "status"})

    # --- status queries -----------------------------------------------------------------------
    match = re.search(r"\bwhy (?:did you|was|were)\b.{0,20}?\b(?:skip|skipped|filter|filtered|reject|rejected|"
                      r"not apply(?: to)?)\s+(.+?)\??$", raw, re.IGNORECASE)
    if match:
        return Intent("query_application_status", {"kind": "why", "company": match.group(1).strip(" ?")})
    if re.search(r"\bhow many\b.{0,30}\b(?:appl(?:ied|ications?)|jobs?)\b", lowered):
        return Intent("query_application_status", {"kind": "counts", "platform": portals[0] if portals else None})
    match = re.search(r"\b(?:show|list|last)\b.{0,10}?(\d{1,2})?\s*(?:recent |latest |last )?(drafts?|applications?|"
                      r"applied|jobs?|replies|alerts|hitl|questions?)\b", lowered)
    if match and re.search(r"\b(?:show|list|last|latest|recent)\b", lowered):
        what = match.group(2)
        kind = "drafts" if what.startswith("draft") else "replies" if what in ("replies", "alerts") \
            else "hitl" if what in ("hitl", "question", "questions") else "applications"
        return Intent("query_application_status", {"kind": kind, "limit": int(match.group(1) or 5),
                                                   "platform": portals[0] if portals else None})

    # --- preferences --------------------------------------------------------------------------
    match = re.match(r"^(?:please )?(?:blacklist|block|exclude|avoid|never apply to)\s+(?:companies?\s+)?(.+)$", raw, re.IGNORECASE)
    if match and not re.search(r"\bkeywords?\b", lowered):
        return Intent("update_preferences", {"op": "add", "key": "company_blacklist",
                                             "values": _split_items(match.group(1))})
    match = re.match(r"^(?:please )?(?:un-?blacklist|unblock|remove)\s+(.+?)(?:\s+from (?:the )?blacklist)?$", raw, re.IGNORECASE)
    if match and ("blacklist" in lowered or lowered.startswith(("unblacklist", "un-blacklist", "unblock"))):
        return Intent("update_preferences", {"op": "remove", "key": "company_blacklist",
                                             "values": _split_items(match.group(1))})
    match = re.search(r"\b(expected|current|min(?:imum)?)\s+(?:ctc|salary|compensation|package)\b.{0,15}?" + NUMBER
                      + r"\s*(?:lpa|lakhs?|lacs?|l\b)?", raw, re.IGNORECASE)
    if match:
        key = {"expected": "expected_ctc", "current": "current_ctc"}.get(match.group(1).lower(), "min_ctc")
        return Intent("update_preferences", {"op": "set", "key": key, "value": _num(match.group(2))})
    match = re.search(r"\bnotice(?: period)?\b.{0,20}?\b(immediate(?:ly)?|\d{1,3})\s*(days?|weeks?|months?)?", raw, re.IGNORECASE)
    if match:
        if match.group(1).lower().startswith("immediate"):
            days = 0
        else:
            unit = (match.group(2) or "days").lower()
            days = int(match.group(1)) * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        return Intent("update_preferences", {"op": "set", "key": "notice_period_days", "value": days})
    match = re.match(r"^(?:please )?(add|remove)\s+(.+?)\s+(?:to|from)\s+(?:the |my )?(required keywords?|"
                     r"excluded keywords?|keywords? required|keywords? excluded|tech stack|target roles?|"
                     r"blacklist)$", raw, re.IGNORECASE)
    if match:
        bucket = match.group(3).lower()
        key = ("keywords_required" if "required" in bucket else "keywords_excluded" if "excluded" in bucket
               else "tech_stack" if "tech" in bucket else "target_roles" if "role" in bucket else "company_blacklist")
        return Intent("update_preferences", {"op": match.group(1).lower(), "key": key,
                                             "values": _split_items(match.group(2))})
    match = re.search(r"\b(?:remote only|only remote)\b", lowered)
    if match:
        return Intent("update_preferences", {"op": "set", "key": "remote_policy", "value": "remote_only"})

    # --- portal rules -------------------------------------------------------------------------
    targets = portals or (["*"] if re.search(r"\b(?:all portals|every portal|everywhere)\b", lowered) else [])
    match = re.search(r"\b(?:pause|snooze|hold)\b.{0,30}?\bfor\s+(\d{1,3})\s*(h|hrs?|hours?|m|mins?|minutes?|d|days?)\b",
                      lowered)
    if match and targets:
        amount, unit = int(match.group(1)), match.group(2)
        delta = timedelta(minutes=amount) if unit.startswith("m") else timedelta(days=amount) if unit.startswith("d") \
            else timedelta(hours=amount)
        return Intent("update_portal_rule", {"platforms": targets, "changes": {"paused_until": now + delta},
                                             "pause_for": str(delta)}, confirmed=confirmed)
    if targets and re.search(r"\b(?:pause|snooze|hold)\b", lowered):
        return Intent("update_portal_rule", {"platforms": targets,
                                             "changes": {"paused_until": now + timedelta(hours=24)},
                                             "pause_for": "24:00:00"}, confirmed=confirmed)
    if targets and re.search(r"\b(?:resume|unpause|unsnooze)\b", lowered):
        return Intent("update_portal_rule", {"platforms": targets, "changes": {"paused_until": None}},
                      confirmed=confirmed)
    auto = re.search(r"\bauto[- ]?apply\b", lowered)
    if targets and re.search(r"\b(?:enable|turn on|switch on|activate|start)\b", lowered):
        return Intent("update_portal_rule", {"platforms": targets,
                                             "changes": {"auto_apply_enabled" if auto else "enabled": True}},
                      confirmed=confirmed)
    if targets and re.search(r"\b(?:disable|turn off|switch off|deactivate|stop)\b", lowered):
        return Intent("update_portal_rule", {"platforms": targets,
                                             "changes": {"auto_apply_enabled" if auto else "enabled": False}},
                      confirmed=confirmed)
    match = re.search(r"\bdelays?\b.{0,20}?" + NUMBER + r"\s*(?:-|–|to|and)\s*" + NUMBER, lowered)
    if match:
        return Intent("update_portal_rule", {"platforms": targets or ["*"], "changes": {
            "min_delay_sec": int(float(match.group(1))), "max_delay_sec": int(float(match.group(2)))}},
            confirmed=confirmed)
    number = re.search(r"\b(?:to|=|at|as)\s+" + NUMBER + r"\b|" + NUMBER + r"\s*(?:days?|applicants?|/day|per day|"
                       r"/hour|per hour)?\s*$", lowered)
    if number:
        value = _num(next(g for g in number.groups() if g))
        for pattern, rule in RULE_FIELDS:
            if pattern.search(lowered):
                return Intent("update_portal_rule", {"platforms": targets or ["*"], "changes": {rule: value}},
                              confirmed=confirmed)
    return None


# --- LLM fallback -------------------------------------------------------------------------------
class LLMIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tool: ToolName
    platforms: list[str] = Field(default_factory=list, max_length=10)
    rule_changes: dict[str, Any] = Field(default_factory=dict)
    preference_op: Literal["set", "add", "remove"] | None = None
    preference_key: str | None = None
    preference_values: list[Any] = Field(default_factory=list, max_length=20)
    question: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=1000)
    worker_action: Literal["pause", "resume", "status", "run_once"] | None = None
    query_kind: Literal["counts", "why", "failed", "digest", "drafts", "applications", "replies",
                        "hitl"] | None = None
    company: str | None = Field(default=None, max_length=120)
    confidence: float = Field(default=0.0, ge=0, le=1)


SYSTEM_PROMPT = (
    "You map ONE owner message for a job-application bot to ONE tool call. Tools: update_portal_rule "
    "(rule_changes keys: enabled, auto_apply_enabled, max_applies_per_day, max_applies_per_hour, max_job_age_days, allow_unknown_posting_age, "
    "max_applicants, min_delay_sec, max_delay_sec, quota_fallback_daily_cap, quota_drafts_per_cycle), "
    "update_preferences (preference_key one of company_blacklist, keywords_required, keywords_excluded, tech_stack, "
    "target_roles, expected_ctc, current_ctc, min_ctc, notice_period_days, remote_policy), query_application_status "
    "(query_kind counts|why|failed|digest|drafts|applications|replies|hitl), teach_semantic_cache (question + answer), "
    "control_worker (pause|resume|status|run_once), help. Portals: naukri, instahyre, internshala, wellfound, "
    "work_at_a_startup, himalayas, we_work_remotely, hiringcafe, greenhouse, lever. Sending email, deleting data and "
    "re-applying are impossible: use tool=forbidden. If unsure use help. Reply with one JSON object only.")


async def llm_parse(router: Any, text: str) -> Intent | None:
    if router is None or not getattr(router, "any_configured", False):
        return None
    from backend.app.ai_v2.router import AllLLMProvidersExhaustedError

    try:
        result = await router.generate_json("agent_intent", SYSTEM_PROMPT, json.dumps({"message": text[:800]}),
                                            LLMIntent, max_output_tokens=250)
    except AllLLMProvidersExhaustedError:
        return None
    value = result.value
    if value.confidence < 0.6:
        return Intent("help", source="llm", note="low_confidence")
    platforms = [PORTAL_ALIASES.get(p.lower(), p.lower()) for p in value.platforms]
    if value.tool == "update_portal_rule":
        return Intent(value.tool, {"platforms": platforms or ["*"], "changes": value.rule_changes}, "llm")
    if value.tool == "update_preferences":
        op = value.preference_op or "set"
        args: dict[str, Any] = {"op": op, "key": value.preference_key}
        if op == "set":
            args["value"] = value.preference_values[0] if value.preference_values else None
        else:
            args["values"] = [str(v) for v in value.preference_values]
        return Intent(value.tool, args, "llm")
    if value.tool == "teach_semantic_cache":
        return Intent(value.tool, {"question": value.question, "answer": value.answer}, "llm")
    if value.tool == "control_worker":
        return Intent(value.tool, {"action": value.worker_action or "status"}, "llm")
    if value.tool == "query_application_status":
        return Intent(value.tool, {"kind": value.query_kind or "counts", "company": value.company,
                                   "platform": platforms[0] if platforms else None}, "llm")
    return Intent(value.tool, {}, "llm")
