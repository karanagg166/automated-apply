"""Milestone 2 ops command-center contracts: worker telemetry, dry-run / mute toggles, rules explain,
breaker reset, profile-hash stamping and the semantic-cache admin responses (strict OpenAPI models)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.browser_v2.schemas.applications import WorkerControlRead

OpsStatusName = Literal["RUNNING", "PAUSED", "DRY_RUN", "OFFLINE"]
BreakerStateName = Literal["closed", "open", "half_open"]
HealthName = Literal["green", "amber", "red"]


class ActiveJobRead(BaseModel):
    application_id: str
    platform: str
    company: str | None = None
    title: str | None = None
    step: str
    started_at: datetime | None = None
    elapsed_sec: float | None = None


class BraveHealthRead(BaseModel):
    healthy: bool | None = None
    detail: str | None = None


class PortalTelemetryRead(BaseModel):
    platform: str
    enabled: bool
    auto_apply_enabled: bool
    paused_until: datetime | None = None
    auth_status: str
    auth_checked_at: datetime | None = None
    breaker_state: BreakerStateName
    breaker_open_until: datetime | None = None
    breaker_reason: str | None = None
    breaker_level: int = 0
    applied_today: int
    attempts_today: int
    daily_cap: int
    applied_this_hour: int
    hourly_cap: int
    portal_limit_hit_today: bool = False
    within_active_hours: bool = True
    last_sweep_at: datetime | None = None
    health: HealthName
    health_reason: str | None = None


class FirstMoverRead(BaseModel):
    p50_seconds: int | None = None
    p95_seconds: int | None = None
    samples: int = 0


class TelegramOpsRead(BaseModel):
    configured: bool
    muted_until: datetime | None = None
    quiet_hours_active: bool = False
    quiet_hours: str | None = None
    push_budget_remaining: int | None = None
    push_budget_per_hour: int | None = None
    polling_state: str | None = None


class OpsKpisRead(BaseModel):
    applied_today: int
    verified_receipts_today: int
    pending_hitl: int
    cache_hit_rate: float | None = None
    cache_hit_window_days: int = 7
    cache_lookups: int = 0
    active_watchers: int
    needs_reconciliation: int


class WorkerTelemetryRead(BaseModel):
    generated_at: datetime
    status: OpsStatusName
    worker: WorkerControlRead
    active_job: ActiveJobRead | None = None
    brave: BraveHealthRead
    portals: list[PortalTelemetryRead]
    first_mover: FirstMoverRead
    telegram: TelegramOpsRead
    kpis: OpsKpisRead


class DryRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    confirm: str | None = Field(default=None, max_length=20)


class TelegramMuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: int | None = Field(default=None, ge=0, le=10_080)


class TelegramMuteRead(BaseModel):
    muted_until: datetime | None = None


class RulesExplainInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    url: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=200)
    posted_age_days: int | None = Field(default=None, ge=0, le=3650)
    applicants: int | None = Field(default=None, ge=0, le=1_000_000)
    experience_text: str | None = Field(default=None, max_length=200)
    salary_text: str | None = Field(default=None, max_length=200)
    work_mode: str | None = Field(default=None, max_length=40)


class RuleCheckRead(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class RuleScoreRead(BaseModel):
    total: float | None = None
    breakdown: dict[str, float] = Field(default_factory=dict)
    priority: int | None = None
    priority_reason: str | None = None


class RulesExplainRead(BaseModel):
    platform: str
    decision: str
    passed: bool
    reasons: list[str]
    checks: list[RuleCheckRead]
    score: RuleScoreRead
    rules_revision: int | None = None


class StampProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "unstamped": only owner-verified rows with no hash yet (the post-006 one-off); "owner_verified":
    # also re-stamp owner-verified rows written under an older profile (owner confirms they still hold).
    scope: Literal["unstamped", "owner_verified"] = "unstamped"


class StampProfileRead(BaseModel):
    stamped: int
    profile_hash: str
    stale_remaining: int
    scope: str


# --- semantic-cache admin responses (previously untyped dicts) ---------------------------------
class CacheDecisionStats(BaseModel):
    since: str | None = None
    lookups: int = 0
    hits: int = 0
    hit_rate: float | None = None
    counters: dict[str, int] = Field(default_factory=dict)
    rejections: dict[str, int] = Field(default_factory=dict)


class SemanticCacheStatsRead(BaseModel):
    total_entries: int = 0
    total_hits: int = 0
    threshold: float | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_ready: bool = False
    backend: str | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    stale_entries: int | None = None  # active factual rows written under an older profile hash
    profile_hash: str | None = None
    decisions: CacheDecisionStats = Field(default_factory=CacheDecisionStats)


class SemanticCachePurgeRead(BaseModel):
    deleted: int


class SemanticCacheExplainHit(BaseModel):
    id: str
    match: str
    similarity: float
    answer: str | None = None


class SemanticCacheExplainCandidate(BaseModel):
    id: str
    question: str
    answer: str | None = None
    match: str
    similarity: float
    status: str
    decision: str  # "served" or the guard rejection (rejected_entity_mismatch, rejected_polarity_flip, ...)


class SemanticCacheExplainRead(BaseModel):
    decision: str = "miss"  # exact_hit | semantic_hit | never_cache | miss
    reason: str | None = None
    polarity: list[str] = Field(default_factory=list)
    negation: bool = False
    candidates: list[SemanticCacheExplainCandidate] = Field(default_factory=list)
    intent_bucket: str | None = None
    field_type: str | None = None
    cache_policy: str | None = None
    invalidation_scope: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    hit: SemanticCacheExplainHit | None = None
