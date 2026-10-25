"""Bounded interpretation only. Classifiers cannot grant execution authority."""
import asyncio
import re
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core.urls import PublicHTTPSURL

IntentKind = Literal[
    "FIND_JOBS", "FILTER_JOBS", "SHOW_JOB", "PREPARE_APPLICATION",
    "APPLICATION_STATUS", "CONNECTION_STATUS", "GMAIL_DRAFT_PREVIEW",
    "FOUNDER_RESEARCH_PREVIEW", "HELP", "UNKNOWN",
    "GENERAL_CHAT", "FOLLOW_UP", "JOB_COMPARISON", "PROFILE_QUERY", "PROJECT_QUERY",
    "RESUME_STATUS", "APPROVAL_REQUEST", "RESET_CONTEXT", "ANSWER_PREPARATION",
]

ROUTING_CATEGORIES = {
    "HELP": "GENERAL_CHAT", "UNKNOWN": "UNSUPPORTED_ACTION", "FIND_JOBS": "JOB_DISCOVERY",
    "FILTER_JOBS": "JOB_FILTERING", "SHOW_JOB": "FOLLOW_UP", "RESET_CONTEXT": "FOLLOW_UP",
    "PREPARE_APPLICATION": "APPLICATION_PREPARATION", "ANSWER_PREPARATION": "APPLICATION_PREPARATION",
    "GMAIL_DRAFT_PREVIEW": "APPLICATION_PREPARATION", "FOUNDER_RESEARCH_PREVIEW": "FOUNDER_RESEARCH",
}


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    category: IntentKind
    company: str | None = Field(None, min_length=1, max_length=100)
    role: str | None = Field(None, min_length=1, max_length=100)
    location: str | None = Field(None, min_length=1, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=10)
    remote: bool = False
    startup: bool = False
    days: int | None = Field(None, ge=1, le=365)
    not_applied: bool = False
    url: PublicHTTPSURL | None = None
    selection: int | None = Field(None, ge=1, le=10)
    job_id: UUID | None = None
    connection: Literal["gmail", "telegram", "supabase", "chrome", "agy", "naukri", "wellfound", "instahyre", "internshala", "yc"] | None = None
    subject: str | None = Field(None, max_length=200)
    project_rank: int | None = Field(None, ge=1, le=30)
    follow_up: Literal["filter", "selected", "prepare", "answer", "clarify"] | None = None
    max_words: int = Field(default=100, ge=1, le=500)
    max_characters: int = Field(default=3500, ge=1, le=3500)

    @property
    def routing_category(self):
        return ROUTING_CATEGORIES.get(self.category, self.category)

    @model_validator(mode="after")
    def coherent(self):
        if any(not re.fullmatch(r"[\w .+#&/-]{1,100}", x) for x in [self.company, self.role, self.location, *self.skills] if x is not None):
            raise ValueError("invalid_intent_filter")
        if (self.selection or self.job_id) and self.category != "SHOW_JOB":
            raise ValueError("selection_requires_show_job")
        if self.url and self.category != "PREPARE_APPLICATION":
            raise ValueError("url_requires_preparation")
        if self.category == "PREPARE_APPLICATION" and not (self.url or self.company):
            raise ValueError("preparation_target_required")
        return self


class Classifier(Protocol):
    async def classify(self, message: str) -> str: ...


def _legacy_intent(text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2048:
        return Intent(category="UNKNOWN")
    original = text.strip().replace("’", "'").rstrip(".?!")
    value = original.casefold()
    # Compound instructions and authority-changing requests are never interpreted.
    if re.search(r"[\n\r;`]|ignore .*instructions|system prompt|execute|shell|password|access.?token|send (?:an? |the )?email|submit|bypass|override|disable .*approval", value):
        return Intent(category="UNKNOWN")
    if value in {"help", "hello", "hi", "what can you do"}:
        return Intent(category="HELP")
    if re.fullmatch(r"(?:choose |select |show |job )?(?:[1-9]|10)", value):
        return Intent(category="SHOW_JOB", selection=int(value.split()[-1]))
    if ("connected" in value or "connection" in value) and re.match(r"(?:check|show|is |are |tell)", value):
        target = next((name for name in ["gmail", "telegram", "supabase", "chrome", "agy"] if name in value), None)
        return Intent(category="CONNECTION_STATUS", connection=target)
    if re.search(r"(?:how many|status|pending).*(?:application)|application.*(?:pending|status)", value):
        return Intent(category="APPLICATION_STATUS")
    if re.match(r"(?:preview|show|prepare) .*(?:gmail|email) draft", value):
        return Intent(category="GMAIL_DRAFT_PREVIEW")
    if re.match(r"(?:find|show|research) (?:the )?(?:recruiters|founders)", value):
        return Intent(category="FOUNDER_RESEARCH_PREVIEW")
    prepare = re.fullmatch(r"(?:prepare an application for (?:this url:? )?|apply (?:to|for) )(https://\S+)", original, re.I)
    if prepare:
        try:
            return Intent(category="PREPARE_APPLICATION", url=prepare[1])
        except ValueError:
            return Intent(category="UNKNOWN")
    prepare = re.fullmatch(r"(?:apply (?:to|for)|prepare an application for) ([\w .&-]{1,100})", original, re.I)
    if prepare:
        return Intent(category="PREPARE_APPLICATION", company=prepare[1])
    if not re.match(r"(?:find|show|filter|search|list)\b", value) or not re.search(r"\bjobs?\b", value):
        return Intent(category="UNKNOWN")
    company = re.search(r"\b(?:at|for company) ([\w .&-]+?)(?= in | requiring | posted |$)", original, re.I)
    location = re.search(r"\bin (?!the last\b)([\w .-]+?)(?= posted | requiring |$)", original, re.I)
    role = re.search(r"\b(?:find|show|list|search)(?: all)?(?: remote)? ([\w +#/-]+?) jobs?\b", original, re.I)
    role_value = role[1] if role and role[1].casefold() not in {"startup", "all", "the"} else None
    days = re.search(r"last (\d+|one|two|three|seven|thirty) days?", value)
    numbers = {"one": 1, "two": 2, "three": 3, "seven": 7, "thirty": 30}
    day_count = numbers.get(days[1], int(days[1]) if days and days[1].isdigit() else None) if days else None
    if day_count is not None and not 1 <= day_count <= 365:
        return Intent(category="UNKNOWN")
    skills = re.search(r"requiring ([\w +#.,/-]+)", original, re.I)
    remainder = original
    for match in [skills, company, location, role]:
        if match:
            remainder = remainder.replace(match[0], " ")
    remainder = re.sub(r"(?:posted )?in the last (?:\d+|one|two|three|seven|thirty) days?|(?:posted )?the last (?:\d+|one|two|three|seven|thirty) days?|I (?:haven't|have not) applied to|not applied", " ", remainder, flags=re.I)
    remainder = re.sub(r"\b(?:find|show|filter|search|list|all|remote|startup|jobs?)\b", " ", remainder, flags=re.I)
    if remainder.strip():
        return Intent(category="UNKNOWN")
    return Intent(category="FILTER_JOBS" if "haven't applied" in value or "not applied" in value else "FIND_JOBS",
        company=company[1] if company else None, location=location[1] if location else None,
        role=role_value, remote="remote" in value, startup="startup" in value,
        skills=re.split(r",\s*| and ", skills[1])[:10] if skills else [], days=day_count,
        not_applied="haven't applied" in value or "not applied" in value)


def unsafe_request(text):
    return bool(re.search(r"[;`]|ignore .*instructions|system prompt|\bexecute\b|\bshell\b|password|access.?token|api.?key|send (?:an? |the )?email|\bsubmit\b|\bbypass\b|\boverride\b|disable .*approval", text, re.I))


def deterministic_intent(text):
    """Compositional interpretation; unknown or conflicting requests fail closed.

    Only common command spelling is repaired. Company/project identities are never
    fuzzy-corrected into someone else's records. A model has no execution privilege.
    """
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2048 or unsafe_request(text):
        return Intent(category="UNKNOWN")
    original = " ".join(text.replace("’", "'").split()).rstrip(".?!")
    corrections = {"applicaton": "application", "aplication": "application", "aplications": "applications",
        "conected": "connected", "connnected": "connected", "remtoe": "remote", "pyhton": "Python",
        "staus": "status", "jbos": "jobs", "develper": "developer"}
    original = re.sub(r"\b\w+\b", lambda m: corrections.get(m[0].casefold(), m[0]), original)
    original = re.sub(r"^(?:(?:hi|hello|hey)[,!. ]+)?(?:please |could you |can you )?", "", original, flags=re.I)
    value = original.casefold()
    limit = re.search(r"\b(?:in|under|within|up to|at most) (\d+) (words?|characters?)\b", value)
    if limit:
        number = int(limit[1])
        field = "max_words" if limit[2].startswith("word") else "max_characters"
        if not 1 <= number <= (500 if field == "max_words" else 3500):
            return Intent(category="UNKNOWN")
        reduced = original[:limit.start()] + original[limit.end():]
        return deterministic_intent(reduced).model_copy(update={field: number})
    sentences = re.split(r"[.!?]+\s+", original) if "https://" not in original else [original]
    if 1 < len(sentences) <= 3:
        intents = [deterministic_intent(s) for s in sentences if s.strip()]
        meaningful = [i for i in intents if i.category not in {"HELP", "GENERAL_CHAT"}]
        if len(meaningful) == 1:
            return meaningful[0]
        if len(meaningful) == 2 and meaningful[0].category in {"FIND_JOBS", "FILTER_JOBS"} and meaningful[1].follow_up == "filter":
            follow = meaningful[1]
            updates = {k: getattr(follow, k) for k in ("location", "days") if getattr(follow, k) is not None}
            if follow.remote:
                updates["remote"] = True
            return meaningful[0].model_copy(update=updates)
        return Intent(category="FOLLOW_UP", follow_up="clarify")
    if not value:
        return Intent(category="HELP")
    if re.search(r"\b(?:forget|reset|clear|start over)\b.*(?:selection|conversation|context|search|again)|^/reset$", value):
        return Intent(category="RESET_CONTEXT")
    if re.search(r"\b(?:approve|approval|confirm)\b", value):
        return Intent(category="APPROVAL_REQUEST")
    if re.search(r"\bresume\b", value) and re.search(r"\b(?:check|status|latest|sync|review|updated)\b", value):
        return Intent(category="RESUME_STATUS")
    if re.search(r"\b(?:profile|skills|experience|locations|notice period|salary preferences)\b", value) and re.match(r"(?:show|check|what|tell|list)", value) and "project" not in value and "experience with" not in value:
        return Intent(category="PROFILE_QUERY", subject=value[:200])
    project_rank = re.search(r"\b(first|second|third|most important|best|top|[1-9]|[12][0-9]|30) project\b", value)
    if project_rank or "project" in value or re.match(r"(?:explain|describe|tell me about) .+ architecture", value):
        rank = {"first": 1, "second": 2, "third": 3, "most important": 1, "best": 1, "top": 1}.get(project_rank[1]) if project_rank else None
        if project_rank and rank is None:
            rank = int(project_rank[1])
        subject = re.sub(r"^(?:tell me about|explain|describe|use|show) (?:my |the )?", "", original, flags=re.I)
        return Intent(category="PROJECT_QUERY", subject=subject[:200], project_rank=rank,
            follow_up="answer" if re.match(r"use .*project", value) else None)
    if re.search(r"\b(?:connected|connection|connections)\b", value):
        target = next((name for name in ["gmail", "telegram", "supabase", "chrome", "agy", "naukri", "wellfound", "instahyre", "internshala", "yc"] if re.search(r"\b" + name + r"\b", value)), None)
        return Intent(category="CONNECTION_STATUS", connection=target)
    if re.search(r"\b(?:compare|prioritize|prioritise|best job|which job|rank .*jobs)\b", value):
        return Intent(category="JOB_COMPARISON")
    if "https://" in value or "http://" in value:
        return _legacy_intent(original)
    if re.search(r"why (?:should .*hire|i want to join)|experience with|challenging engineering problem|scalable system", value):
        return Intent(category="ANSWER_PREPARATION", subject=original[:200])
    if re.match(r"(?:only |just |what about |how about |and |make (?:them|it) )", value):
        location = re.search(r"\bin ([\w .-]+)", original, re.I)
        return Intent(category="FOLLOW_UP", follow_up="filter", remote="remote" in value,
            location=location[1] if location else None, days=1 if "today" in value else None)
    if re.search(r"\b(?:that|this|it|selected|previous)\b", value) and re.search(r"\b(?:job|one|application|prepare|details|show|apply)\b", value):
        return Intent(category="FOLLOW_UP", follow_up="prepare" if re.search(r"prepare|apply", value) else "selected")
    legacy = _legacy_intent(original)
    if legacy.category != "UNKNOWN":
        return legacy
    # Questions about today's/new jobs and natural leading phrases share the same
    # bounded filter parser as commands; this is not an exact phrase dictionary.
    if re.search(r"\bjobs?\b", value):
        normalized = re.sub(r"^(?:are there |do (?:you|we) have |any |what are the |look for |search for |find me |show me )", "find ", original, flags=re.I)
        normalized = re.sub(r"\bnew\s+", "", normalized, flags=re.I)
        normalized = re.sub(r"\b(?:available|open)\s+", "", normalized, flags=re.I)
        today = bool(re.search(r"\btoday\b", normalized, re.I))
        normalized = re.sub(r"\s+today\b", "", normalized, flags=re.I)
        if "have not applied" in value and "companies" in value:
            return Intent(category="FILTER_JOBS", not_applied=True)
        parsed = _legacy_intent(normalized)
        if parsed.category != "UNKNOWN":
            return parsed.model_copy(update={"days": 1}) if today else parsed
    if "companies" in value and re.search(r"(?:not|haven't) applied", value):
        return Intent(category="FILTER_JOBS", not_applied=True)
    if value in {"thanks", "thank you", "good morning", "good evening"}:
        return Intent(category="GENERAL_CHAT")
    return Intent(category="UNKNOWN")


async def extract_intent(text, classifier: Classifier | None = None):
    intent = deterministic_intent(text)
    if intent.category != "UNKNOWN" or classifier is None:
        return intent
    # The caller must separately authorize quota and provide a tool-free provider.
    # No provider is enabled implicitly for incoming Telegram messages.
    if not isinstance(text, str) or len(text) > 2048 or unsafe_request(text):
        return intent
    try:
        async with asyncio.timeout(5):
            raw = await classifier.classify(text)
        if not isinstance(raw, str) or len(raw.encode()) > 4096:
            return intent
        return Intent.model_validate_json(raw)
    except (ValueError, TypeError, TimeoutError):
        return intent
