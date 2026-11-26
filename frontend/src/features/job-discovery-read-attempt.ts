"use client";
import { api, ApiError } from "@/lib/api";
import type { JobDiscoveryRun } from "./job-discovery";
import {
  discoveryComplete,
  readDiscoveryAttempt,
  validateDiscoveryRun,
  withDiscoveryAttemptLock,
  type DiscoveryAttempt,
} from "./job-discovery-attempt";
export type DiscoveryReadAttempt = { requestId: string; readId: string };
export type DiscoveryReadResult = {
  request_id: string;
  read_request_id: string;
  source: string;
  recorded_state: string;
  status: string;
  finding_retained: boolean;
  local_merge_available: boolean;
  read_round_limit: number;
  read_admissions: number;
  round: number;
  http_attempts: number;
  http_responses: number;
  http_counts_are_minimum: boolean;
  errors?: string[];
  admitted_at?: string;
  expires_at?: string;
  provider_status?: string | null;
  billing_final: boolean;
  provider_start_authorized: boolean;
  provider_abort_authorized: boolean;
  replay_authorized: boolean;
  application_dispatch: boolean;
  live_verified: boolean;
  reservation: {
    reserved_usd: string;
    accounting: string;
    billing_final: boolean;
  };
};
export type DiscoveryReadState = {
  run: JobDiscoveryRun;
  read: DiscoveryReadResult | null;
  attempt: DiscoveryReadAttempt | null;
};
const storageKey = "job-discovery-read:v1";
const baseKey = "job-discovery-attempt:v1";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const nonzero = (id: unknown): id is string =>
  typeof id === "string" &&
  uuid.test(id) &&
  id !== "00000000-0000-0000-0000-000000000000";
export const paidDiscoverySource = (source: unknown): boolean =>
  typeof source === "string" &&
  [
    "naukri",
    "instahyre",
    "wellfound",
    "work_at_a_startup",
    "cutshort",
    "hirist",
    "foundit",
    "indeed",
    "glassdoor",
  ].includes(source);
const review = () =>
  new Error(
    "Review the original discovery and its saved read before preparing another read.",
  );
const base = (id: string) => `discovery/runs/${id}`;
const path = (attempt: DiscoveryReadAttempt) =>
  `${base(attempt.requestId)}/reads/${attempt.readId}`;
export function readDiscoveryReadAttempt(): DiscoveryReadAttempt | null {
  const raw = localStorage.getItem(storageKey);
  if (!raw) return null;
  if (raw.length > 256) throw review();
  let value: DiscoveryReadAttempt;
  try {
    value = JSON.parse(raw);
  } catch {
    throw review();
  }
  if (
    !value ||
    Array.isArray(value) ||
    Object.keys(value).length !== 2 ||
    !nonzero(value.requestId) ||
    !nonzero(value.readId) ||
    value.requestId === value.readId
  )
    throw review();
  return value;
}
function save(attempt: DiscoveryReadAttempt) {
  localStorage.setItem(storageKey, JSON.stringify(attempt));
}
async function context(): Promise<{
  owner: DiscoveryAttempt;
  run: JobDiscoveryRun;
  attempt: DiscoveryReadAttempt | null;
}> {
  let owner = readDiscoveryAttempt();
  let attempt = readDiscoveryReadAttempt();
  let run: JobDiscoveryRun | undefined;
  if (!owner && attempt) {
    const candidate = await api<JobDiscoveryRun>(base(attempt.requestId));
    if (!paidDiscoverySource(candidate?.source)) throw review();
    owner = { requestId: attempt.requestId, source: candidate.source };
    run = validateDiscoveryRun(candidate, owner);
    if (run.original_scope_available !== true) throw review();
    localStorage.setItem(baseKey, JSON.stringify(owner));
  }
  if (!owner) throw review();
  if (attempt && attempt.requestId !== owner.requestId) throw review();
  run =
    run ??
    validateDiscoveryRun(
      await api<JobDiscoveryRun>(base(owner.requestId)),
      owner,
    );
  if (!paidDiscoverySource(run.source) || run.original_scope_available !== true)
    throw review();
  if (!attempt && nonzero(run.usage.last_read_request_id)) {
    attempt = {
      requestId: owner.requestId,
      readId: run.usage.last_read_request_id,
    };
    if (attempt.requestId === attempt.readId) throw review();
    save(attempt);
  }
  return { owner, run, attempt };
}
function validate(
  value: DiscoveryReadResult,
  attempt: DiscoveryReadAttempt,
  source: string,
): DiscoveryReadResult {
  if (
    !value ||
    value.request_id !== attempt.requestId ||
    value.read_request_id !== attempt.readId ||
    value.source !== source ||
    value.billing_final !== false ||
    value.provider_start_authorized !== false ||
    value.provider_abort_authorized !== false ||
    value.replay_authorized !== false ||
    value.application_dispatch !== false ||
    value.live_verified !== false ||
    typeof value.finding_retained !== "boolean" ||
    typeof value.local_merge_available !== "boolean" ||
    value.read_round_limit !== 3 ||
    typeof value.http_counts_are_minimum !== "boolean" ||
    ![
      "read_admitted",
      "operation_admitted",
      "response_retained",
      "finding_retained",
      "failed",
      "not_needed",
    ].includes(value.recorded_state) ||
    !["pending", "outcome_unknown", "finding_retained", "not_needed"].includes(
      value.status,
    )
  )
    throw review();
  const reservation = value.reservation;
  if (
    !reservation ||
    reservation.accounting !== "full_cap_retained" ||
    reservation.billing_final !== false ||
    typeof reservation.reserved_usd !== "string" ||
    !/^\d{1,10}\.\d{6}$/.test(reservation.reserved_usd) ||
    Number(reservation.reserved_usd) <= 0 ||
    Number(reservation.reserved_usd) > 100
  )
    throw review();
  for (const n of [
    value.http_attempts,
    value.http_responses,
    value.round,
    value.read_admissions,
  ]) {
    if (!Number.isInteger(n) || n < 0 || n > 4) throw review();
  }
  if (value.http_responses > value.http_attempts) throw review();
  if (value.recorded_state === "not_needed") {
    if (
      value.round !== 0 ||
      value.read_admissions !== 0 ||
      value.http_attempts !== 0 ||
      !value.finding_retained
    )
      throw review();
  } else {
    if (
      value.round < 1 ||
      value.round > 3 ||
      value.read_admissions !== 1 ||
      !value.admitted_at ||
      !value.expires_at ||
      !Number.isFinite(Date.parse(value.admitted_at)) ||
      Date.parse(value.expires_at) - Date.parse(value.admitted_at) !== 45_000
    )
      throw review();
    if (
      !Array.isArray(value.errors) ||
      value.errors.length > 30 ||
      value.errors.some((s) => typeof s !== "string" || s.length > 150)
    )
      throw review();
  }
  return value;
}
async function get(
  attempt: DiscoveryReadAttempt,
  source: string,
): Promise<DiscoveryReadResult | null> {
  try {
    return validate(
      await api<DiscoveryReadResult>(path(attempt)),
      attempt,
      source,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
async function readOriginal(owner: DiscoveryAttempt): Promise<JobDiscoveryRun> {
  return validateDiscoveryRun(
    await api<JobDiscoveryRun>(base(owner.requestId)),
    owner,
  );
}
/** Saved GETs and local pointer restoration only. Mount cannot dispatch or complete server work. */
export async function inspectDiscoveryRead(): Promise<DiscoveryReadState> {
  return withDiscoveryAttemptLock(async () => {
    const { run, attempt } = await context();
    return {
      run,
      attempt,
      read: attempt ? await get(attempt, run.source) : null,
    };
  });
}
/** One explicit read consent may admit a new bounded GET round; replay can only read saved work. */
export async function recoverDiscoveryRead(
  mayRead = false,
): Promise<DiscoveryReadState> {
  return withDiscoveryAttemptLock(async () => {
    let { owner, run, attempt } = await context();
    if (discoveryComplete(run) || run.usage.finding_retained === true) {
      return {
        run,
        attempt,
        read: attempt ? await get(attempt, run.source) : null,
      };
    }
    if (
      typeof run.provider_run_id !== "string" ||
      !/^[A-Za-z0-9_-]{1,100}$/.test(run.provider_run_id)
    ) {
      throw new Error(
        "The original paid start has no acknowledged run. Its reservation stays held; another start is not authorized.",
      );
    }
    let saved = attempt ? await get(attempt, run.source) : null;
    if (saved) {
      if (saved.finding_retained) run = await readOriginal(owner);
      return { run, attempt, read: saved };
    }
    if (!mayRead)
      throw new Error(
        "Review and authorize this saved read UUID before requesting provider status.",
      );
    if (!attempt) {
      const generated = crypto.randomUUID();
      if (!nonzero(generated) || generated === owner.requestId) throw review();
      attempt = { requestId: owner.requestId, readId: generated };
      save(attempt);
    }
    saved = validate(
      await api<DiscoveryReadResult>(path(attempt), {
        method: "PUT",
        body: "{}",
      }),
      attempt,
      run.source,
    );
    if (saved.finding_retained) run = await readOriginal(owner);
    return { run, attempt, read: saved };
  });
}
/** Review the expired prior result before allocating a new UUID. This never performs provider IO. */
export async function prepareNextDiscoveryRead(
  reviewedRead: string,
): Promise<DiscoveryReadAttempt> {
  return withDiscoveryAttemptLock(async () => {
    const { run, attempt } = await context();
    if (
      !attempt ||
      attempt.readId !== reviewedRead ||
      run.usage.finding_retained === true ||
      discoveryComplete(run)
    )
      throw review();
    const saved = await get(attempt, run.source);
    const next = run.usage.read_next_allowed_at;
    if (
      !saved ||
      saved.finding_retained ||
      saved.local_merge_available ||
      !saved.expires_at ||
      Date.parse(saved.expires_at) > Date.now() ||
      typeof next !== "string" ||
      !Number.isFinite(Date.parse(next)) ||
      Date.parse(next) > Date.now() ||
      typeof run.usage.read_rounds_admitted !== "number" ||
      !Number.isInteger(run.usage.read_rounds_admitted) ||
      run.usage.read_rounds_admitted < 1 ||
      run.usage.read_rounds_admitted >= 3 ||
      run.usage.read_rounds_admitted !== saved.round ||
      run.usage.last_read_request_id !== reviewedRead ||
      readDiscoveryReadAttempt()?.readId !== reviewedRead
    )
      throw review();
    const generated = crypto.randomUUID();
    if (
      !nonzero(generated) ||
      generated === attempt.requestId ||
      generated === attempt.readId
    )
      throw review();
    const fresh = { requestId: attempt.requestId, readId: generated };
    save(fresh);
    return fresh;
  });
}
