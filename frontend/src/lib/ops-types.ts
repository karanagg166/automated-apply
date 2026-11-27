// Milestone 2 ops command-center contract (backend /api/v1/v2/*). Kept local so the UI compiles
// independently of api.d.ts regeneration; field names mirror the Pydantic response models.
import type { Schema } from "@/lib/api";

export type WorkerControl = Schema<"WorkerControlRead">;
export type HitlRead = Schema<"HitlRead">;
export type ApplicationRead = Schema<"ApplicationRead">;
export type PortalRulesRead = Schema<"PortalRulesRead">;

export type OpsStatus = "RUNNING" | "PAUSED" | "DRY_RUN" | "OFFLINE";
export type Health = "green" | "amber" | "red";
export type BreakerState = "closed" | "open" | "half_open";

export type ActiveJob = {
  application_id: string | null;
  platform: string;
  company: string | null;
  title: string | null;
  step: string | null;
  started_at: string | null;
  elapsed_sec: number | null;
};

export type PortalTelemetry = {
  platform: string;
  enabled: boolean;
  auto_apply_enabled: boolean;
  paused_until: string | null;
  auth_status: string;
  breaker_state: BreakerState;
  breaker_open_until: string | null;
  breaker_reason: string | null;
  applied_today: number;
  daily_cap: number;
  applied_this_hour: number;
  hourly_cap: number;
  last_sweep_at: string | null;
  health: Health;
};

export type TelegramTelemetry = {
  configured: boolean;
  muted_until: string | null;
  quiet_hours_active: boolean;
  quiet_hours: string | null;
  push_budget_remaining: number | null;
  push_budget_per_hour: number | null;
};

export type OpsKpis = {
  applied_today: number;
  verified_receipts_today: number;
  pending_hitl: number;
  cache_hit_rate: number | null;
  active_watchers: number;
  needs_reconciliation: number;
};

export type WorkerTelemetry = {
  generated_at: string;
  status: OpsStatus;
  worker: WorkerControl;
  active_job: ActiveJob | null;
  brave: { healthy: boolean | null; detail: string | null };
  portals: PortalTelemetry[];
  first_mover: {
    p50_seconds: number | null;
    p95_seconds: number | null;
    samples: number;
  };
  telegram: TelegramTelemetry;
  kpis: OpsKpis;
};

export type DryRunInput = { dry_run: boolean; confirm?: "LIVE" };
export type MuteInput = { minutes: number | null };
export type MuteRead = { muted_until: string | null };

export type RulesExplainInput = {
  platform?: string;
  url?: string;
  title?: string;
  company?: string;
  description?: string;
  location?: string;
  posted_age_days?: number;
  applicants?: number;
  experience_text?: string;
  salary_text?: string;
  work_mode?: string;
};
export type RulesExplainRead = {
  decision: string;
  passed: boolean;
  reasons: string[];
  checks: { name: string; passed: boolean; detail: string | null }[];
  score: { total: number | null; breakdown: Record<string, number> };
};

export type StampProfileRead = {
  stamped: number;
  profile_hash: string;
  stale_remaining: number;
};

export type WatcherPlatform =
  "greenhouse" | "lever" | "ashby" | "smartrecruiters";
export type WatcherRow = {
  platform: string;
  slug: string;
  active: boolean;
  board_url: string | null;
  last_polled_at: string | null;
  last_status: string | null;
  jobs_found: number | null;
};
export type WatcherInput = {
  platform: WatcherPlatform;
  slug: string;
  active: boolean;
};
export type WatcherProbeRead = {
  platform: string;
  slug: string;
  board_url: string;
  job_count: number;
  matched_count: number;
  sample: {
    title: string;
    location: string | null;
    url: string | null;
    passes: boolean;
    reasons: string[];
  }[];
  already_watched: boolean;
};

export type TierLabel = string; // "Tier 1 Fact" | "Tier 2 Exact" | "Tier 3 Semantic 0.96" | "Tier 4 LLM" | "HITL Human" | ...
export type ProofAnswer = {
  question: string;
  answer: string;
  source: string | null;
  tier_label: TierLabel;
  similarity: number | null;
  cache_entry_id: string | null;
};
export type ProofTiming = {
  posted_at: string | null;
  discovered_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  submitted_at: string | null;
  first_mover_lag_seconds: number | null;
};
export type ApplicationProof = {
  application: ApplicationRead;
  timing: ProofTiming;
  answers: ProofAnswer[];
  resume_variant_used: string | null;
  screenshot: string | null;
  mail_events: {
    kind: string;
    subject: string | null;
    sender: string | null;
    received_at: string | null;
  }[];
  outreach_draft: {
    id: string;
    status: string;
    recipient_email: string | null;
    created_at: string | null;
  } | null;
  email_verified: boolean;
  confirmed_at: string | null;
  needs_reconciliation: boolean;
};
export type ReconcileInput = {
  action: "confirm_applied" | "release_not_submitted";
  confirm: string;
};

/** HITL rows plus optional context fields the backend may attach (rendered only when present). */
export type HitlItem = HitlRead & {
  priority?: number | null;
  fit_score?: number | null;
  posted_age_days?: number | null;
  screenshot?: string | null;
  suggested_answer?: string | null;
  judge_score?: number | null;
  field_kind?: string | null;
  input_kind?: string | null;
  intent?: string | null;
  cache_policy?: string | null;
};

// --- live stream ----------------------------------------------------------------------------
export const LIVE_EVENT_TYPES = [
  "worker.state",
  "job.discovered",
  "job.queued",
  "job.applying_step",
  "job.applied",
  "job.failed",
  "hitl.created",
  "hitl.resolved",
  "portal.breaker_changed",
  "cache.decision",
  "mail.reconciled",
  "resync",
] as const;
export type LiveEventType = (typeof LIVE_EVENT_TYPES)[number];
export type LiveEvent = {
  id: string | null;
  type: LiveEventType;
  at: string;
  payload: Record<string, unknown>;
};
export type LiveConnection = "connecting" | "live" | "reconnecting" | "polling";

export const TELEMETRY_KEY = ["v2-worker-telemetry"] as const;
export const TELEMETRY_PATH = "v2/worker/telemetry";
