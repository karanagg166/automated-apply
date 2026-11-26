"use client";
import { api, ApiError } from "@/lib/api";
import {
  readDiscoveryAttempt,
  validateDiscoveryRun,
  withDiscoveryAttemptLock,
} from "./job-discovery-attempt";
import { readDiscoveryReadAttempt } from "./job-discovery-read-attempt";
import type { JobDiscoveryRun } from "./job-discovery";
export type StartupAttempt = { requestId: string; source: string };
export type StartupRun = {
  id: string;
  source: string;
  status: string;
  counts: Record<string, number>;
  errors: string[];
  finished_at: string | null;
  local_intake_complete?: boolean;
  usage?: Record<string, unknown>;
  rankings?: unknown[];
  application_dispatch?: boolean;
  live_verified?: boolean;
  child_run?: {
    id: string;
    status: string;
    local_intake_complete: boolean;
    rankings_complete: boolean;
    provider_run_id?: string | null;
    reservation?: {
      reserved_usd: string;
      billing_final: boolean;
      accounting: string;
    };
    billing_final?: boolean;
    usage?: Record<string, unknown>;
  };
};
const key = "startup-discovery-attempt:v1";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const source = /^[a-z_]{2,50}$/;
const path = (id: string) => `startups/discovery/runs/${id}`;
const review = () =>
  new Error(
    "Recover and review the original startup search before preparing another search.",
  );
export function startupAttempt(): StartupAttempt | null {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  if (raw.length > 256) throw review();
  let v: StartupAttempt;
  try {
    v = JSON.parse(raw);
  } catch {
    throw review();
  }
  if (
    !v ||
    Array.isArray(v) ||
    Object.keys(v).length !== 2 ||
    typeof v.requestId !== "string" ||
    !uuid.test(v.requestId) ||
    v.requestId === "00000000-0000-0000-0000-000000000000" ||
    typeof v.source !== "string" ||
    !source.test(v.source)
  )
    throw review();
  return v;
}
async function locked<T>(work: () => Promise<T>): Promise<T> {
  if (!navigator.locks?.request)
    throw new Error(
      "Use a current Brave, Edge or Safari browser to recover startup discovery safely.",
    );
  return navigator.locks.request(key, work);
}
export function startupComplete(run: StartupRun): boolean {
  return (
    run.local_intake_complete === true &&
    typeof run.finished_at === "string" &&
    run.finished_at.length > 0
  );
}
function validate(run: StartupRun, attempt: StartupAttempt): StartupRun {
  if (
    !run ||
    run.id !== attempt.requestId ||
    run.source !== `startup_${attempt.source}` ||
    typeof run.status !== "string" ||
    run.application_dispatch !== false ||
    run.live_verified !== false ||
    typeof run.local_intake_complete !== "boolean" ||
    !run.usage ||
    typeof run.usage !== "object" ||
    Array.isArray(run.usage) ||
    !run.counts ||
    Array.isArray(run.counts) ||
    typeof run.counts !== "object" ||
    !Array.isArray(run.errors) ||
    run.errors.length > 100 ||
    run.errors.some((s) => typeof s !== "string" || s.length > 200) ||
    !Array.isArray(run.rankings) ||
    run.rankings.length > 100
  )
    throw review();
  for (const n of Object.values(run.counts)) {
    if (!Number.isInteger(n) || n < 0 || n > 10_000_000) throw review();
  }
  if (
    !run.child_run ||
    !uuid.test(run.child_run.id) ||
    run.child_run.id === attempt.requestId ||
    run.child_run.id === "00000000-0000-0000-0000-000000000000" ||
    typeof run.child_run.status !== "string" ||
    typeof run.child_run.local_intake_complete !== "boolean" ||
    typeof run.child_run.rankings_complete !== "boolean" ||
    !run.usage ||
    typeof run.usage.finding_retained !== "boolean"
  )
    throw review();
  if (["wellfound", "work_at_a_startup"].includes(attempt.source)) {
    const budget = run.child_run.reservation;
    if (
      run.child_run.billing_final !== false ||
      !budget ||
      budget.billing_final !== false ||
      budget.accounting !== "full_cap_retained" ||
      typeof budget.reserved_usd !== "string" ||
      !/^\d{1,10}\.\d{6}$/.test(budget.reserved_usd) ||
      Number(budget.reserved_usd) <= 0 ||
      Number(budget.reserved_usd) > 100
    )
      throw review();
  }
  if (
    startupComplete(run) &&
    (!run.child_run.local_intake_complete || !run.child_run.rankings_complete)
  )
    throw review();
  if (startupComplete(run) && !Number.isFinite(Date.parse(run.finished_at!)))
    throw review();
  return run;
}
async function get(attempt: StartupAttempt) {
  return validate(await api<StartupRun>(path(attempt.requestId)), attempt);
}
export async function inspectStartup(): Promise<StartupRun> {
  return locked(async () => {
    const saved = startupAttempt();
    if (!saved) throw review();
    return get(saved);
  });
}
export async function recoverStartup(
  input: Record<string, unknown>,
  mayStart = false,
): Promise<StartupRun> {
  return locked(async () => {
    let attempt = startupAttempt();
    if (!attempt) {
      if (
        !mayStart ||
        typeof input.source !== "string" ||
        !source.test(input.source)
      )
        throw review();
      attempt = { requestId: crypto.randomUUID(), source: input.source };
      localStorage.setItem(key, JSON.stringify(attempt));
    } else {
      let saved: StartupRun | null = null;
      try {
        saved = await get(attempt);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404) throw e;
      }
      if (saved) return saved;
      if (!mayStart || input.source !== attempt.source) throw review();
    }
    return validate(
      await api<StartupRun>(path(attempt.requestId), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
      attempt,
    );
  });
}
export async function prepareStartup(id: string): Promise<void> {
  await locked(async () => {
    const saved = startupAttempt();
    if (
      !saved ||
      saved.requestId !== id ||
      !startupComplete(await get(saved)) ||
      startupAttempt()?.requestId !== id
    )
      throw review();
    localStorage.removeItem(key);
  });
}
/** Explicit handoff writes only an original child browser pointer after saved API validation; no provider IO. */
export async function reviewStartupChild(id: string): Promise<string> {
  return locked(async () => {
    const attempt = startupAttempt();
    if (!attempt || attempt.requestId !== id) throw review();
    const saved = await get(attempt);
    const child = saved.child_run;
    if (!child) throw review();
    return withDiscoveryAttemptLock(async () => {
      const existing = readDiscoveryAttempt();
      const read = readDiscoveryReadAttempt();
      if (
        (existing &&
          (existing.requestId !== child.id ||
            existing.source !== attempt.source)) ||
        (read && read.requestId !== child.id)
      )
        throw new Error(
          "Review the other saved job discovery before opening this startup child.",
        );
      const pointer = { requestId: child.id, source: attempt.source };
      const run = validateDiscoveryRun(
        await api<JobDiscoveryRun>(`discovery/runs/${child.id}`),
        pointer,
      );
      if (run.original_scope_available === false) throw review();
      localStorage.setItem("job-discovery-attempt:v1", JSON.stringify(pointer));
      return child.id;
    });
  });
}
