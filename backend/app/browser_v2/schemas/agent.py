"""Phase 6A control agent and event bus contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Phase 6A: control agent, event bus, read-only recruiter replies ----------------------
class AgentChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000, description="Owner message, e.g. 'pause Internshala for 3 hours'")


class AgentChatRead(BaseModel):
    reply: str
    tool: str | None = None
    source: str | None = Field(default=None, description="deterministic | llm")
    verdict: str | None = Field(default=None, description="ok | rejected | confirm | help")
    ok: bool


class EventBusStatusRead(BaseModel):
    backend: Literal["postgres", "cloudamqp", "upstash_redis", "in_process"]
    requested_backend: str
    fell_back: bool
    healthy: bool
    published: int = 0
    handler_errors: int = 0
    topics: list[str]
    remote: dict[str, Any] | None = None
    process_note: str = "The worker process owns the live bus; this shows the configured backend."
