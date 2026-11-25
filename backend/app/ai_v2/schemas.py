"""API contracts for /api/v1/v2/ai/status and /api/v1/v2/semantic-cache."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.ai_v2.semantic_cache import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS

ProviderState = Literal["unconfigured", "healthy", "cooldown", "circuit_open"]


class ProviderStatusRead(BaseModel):
    provider: str
    label: str
    status: ProviderState
    model: str
    problem: str | None = None
    api_style: str
    requests_today: int
    requests_this_minute: int
    tokens_today: int
    rpm_limit: int
    rpd_limit: int
    tpd_limit: int | None = None
    circuit_open_until: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    key_envs: list[str]


class SemanticCacheStats(BaseModel):
    backend: str
    total_entries: int
    total_hits: int
    threshold: float
    embedding_model: str
    embedding_dimensions: int
    embedding_ready: bool


class AIStatusRead(BaseModel):
    providers: list[ProviderStatusRead]
    chains: dict[str, list[str]]
    semantic_cache: SemanticCacheStats
    local_generative_llm: Literal["disabled"] = "disabled"


class SemanticCacheEntryRead(BaseModel):
    id: str
    kind: str
    question_text: str
    answer_text: str
    source: Literal["user", "profile", "llm"]
    hits: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SemanticCachePage(BaseModel):
    items: list[SemanticCacheEntryRead]
    total: int
    limit: int
    offset: int


class SemanticCacheCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="screening_qa", pattern=r"^[a-z][a-z0-9_]{1,39}$")
    question_text: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)
    answer_text: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)

    @field_validator("question_text", "answer_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
