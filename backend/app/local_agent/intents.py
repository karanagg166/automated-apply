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
]


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
    connection: Literal["gmail", "telegram", "supabase", "chrome", "agy"] | None = None

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


def deterministic_intent(text):
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


async def extract_intent(text, classifier: Classifier | None = None):
    intent = deterministic_intent(text)
    if intent.category != "UNKNOWN" or classifier is None:
        return intent
    # The caller must separately authorize quota and provide a tool-free provider.
    # No provider is enabled implicitly for incoming Telegram messages.
    if not isinstance(text, str) or len(text) > 2048:
        return intent
    try:
        async with asyncio.timeout(5):
            raw = await classifier.classify(text)
        if not isinstance(raw, str) or len(raw.encode()) > 4096:
            return intent
        return Intent.model_validate_json(raw)
    except (ValueError, TypeError, TimeoutError):
        return intent
