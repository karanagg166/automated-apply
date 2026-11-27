import type { HitlItem, WorkerTelemetry } from "@/lib/ops-types";

export function telemetry(
  overrides: Partial<WorkerTelemetry> = {},
): WorkerTelemetry {
  return {
    generated_at: "2026-11-28T09:00:00Z",
    status: "DRY_RUN",
    worker: {
      desired_state: "RUNNING",
      dry_run: true,
      run_once_requested_at: null,
      observed_state: "RUNNING",
      heartbeat_at: "2026-11-28T08:59:50Z",
      heartbeat_age_sec: 10,
      stale: false,
      current_platform: "greenhouse",
      last_cycle_at: null,
      last_error: null,
      revision: 3,
    } as WorkerTelemetry["worker"],
    active_job: {
      application_id: "11111111-1111-4111-8111-111111111111",
      platform: "greenhouse",
      company: "Stripe",
      title: "Backend Engineer",
      step: "Filling form",
      started_at: null,
      elapsed_sec: 14,
    },
    brave: { healthy: true, detail: null },
    portals: [
      {
        platform: "greenhouse",
        enabled: true,
        auto_apply_enabled: true,
        paused_until: null,
        auth_status: "OK",
        breaker_state: "open",
        breaker_open_until: "2026-11-28T10:00:00Z",
        breaker_reason: "DOM_CHANGED:ats_submit_control_2",
        applied_today: 3,
        daily_cap: 10,
        applied_this_hour: 1,
        hourly_cap: 4,
        last_sweep_at: "2026-11-28T08:55:00Z",
        health: "red",
      },
    ],
    first_mover: { p50_seconds: 420, p95_seconds: 1800, samples: 12 },
    telegram: {
      configured: true,
      muted_until: null,
      quiet_hours_active: false,
      quiet_hours: "23:30-08:00",
      push_budget_remaining: 5,
      push_budget_per_hour: 6,
    },
    kpis: {
      applied_today: 3,
      verified_receipts_today: 2,
      pending_hitl: 4,
      cache_hit_rate: 0.62,
      active_watchers: 27,
      needs_reconciliation: 1,
    },
    ...overrides,
  };
}

export function hitl(overrides: Partial<HitlItem> = {}): HitlItem {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    ref: "333333",
    application_id: "44444444-4444-4444-8444-444444444444",
    platform: "greenhouse",
    kind: "QUESTION",
    status: "OPEN",
    question: "Are you willing to relocate to Pune?",
    options: ["Yes", "No"],
    resolver_reason: "llm_unconfigured",
    company: "Acme",
    title: "Python Developer",
    job_url: "https://example.com/job",
    application_state: "WAITING_FOR_USER",
    telegram_msg_id: 101,
    answer_text: null,
    resolved_via: null,
    created_at: "2026-11-28T08:00:00Z",
    resolved_at: null,
    consumed_at: null,
    ...overrides,
  };
}
