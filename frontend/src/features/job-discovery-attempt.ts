"use client";
import { api, ApiError } from "@/lib/api";
import type { JobDiscoveryRun } from "./job-discovery";
export type DiscoveryAttempt = { requestId: string; source: string };
const storageKey = "job-discovery-attempt:v1";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const source = /^[a-z_]{2,50}$/;
const path = (id: string) => `discovery/runs/${id}`;
const reviewError = () =>
  new Error(
    "Recover and review the saved discovery before preparing another search.",
  );
export function readDiscoveryAttempt(): DiscoveryAttempt | null {
  const raw = localStorage.getItem(storageKey);
  if (!raw) return null;
  if (raw.length > 256) throw reviewError();
  let value: DiscoveryAttempt;
  try {
    value = JSON.parse(raw);
  } catch {
    throw reviewError();
  }
  if (
    !value ||
    Array.isArray(value) ||
    Object.keys(value).some((k) => !["requestId", "source"].includes(k)) ||
    typeof value.requestId !== "string" ||
    !uuid.test(value.requestId) ||
    typeof value.source !== "string" ||
    !source.test(value.source)
  )
    throw reviewError();
  return value;
}
export async function withDiscoveryAttemptLock<T>(
  operation: () => Promise<T>,
): Promise<T> {
  if (!navigator.locks?.request)
    throw new Error(
      "Use a current Brave, Edge or Safari browser to recover discovery safely.",
    );
  return navigator.locks.request(storageKey, operation);
}
export function validateDiscoveryRun(
  value: JobDiscoveryRun,
  attempt: DiscoveryAttempt,
): JobDiscoveryRun {
  if (
    !value ||
    value.id !== attempt.requestId ||
    value.source !== attempt.source ||
    typeof value.status !== "string" ||
    !value.counts ||
    Array.isArray(value.counts) ||
    typeof value.counts !== "object" ||
    !value.usage ||
    Array.isArray(value.usage) ||
    typeof value.usage !== "object" ||
    !Array.isArray(value.job_ids) ||
    value.job_ids.length > 100 ||
    value.job_ids.some((id) => typeof id !== "string" || !uuid.test(id)) ||
    !Array.isArray(value.rankings) ||
    value.rankings.length > 100 ||
    !Array.isArray(value.errors) ||
    value.errors.length > 30 ||
    value.errors.some(
      (error) => typeof error !== "string" || error.length > 8000,
    )
  )
    throw reviewError();
  for (const count of Object.values(value.counts)) {
    if (
      typeof count !== "number" ||
      !Number.isInteger(count) ||
      count < 0 ||
      count > 10_000_000
    )
      throw reviewError();
  }
  if (
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
    ].includes(attempt.source) &&
    value.original_scope_available !== false
  ) {
    const reservation = value.reservation;
    if (
      value.original_scope_available !== true ||
      value.billing_final !== false ||
      !reservation ||
      Array.isArray(reservation) ||
      reservation.billing_final !== false ||
      reservation.accounting !== "full_cap_retained" ||
      typeof reservation.reserved_usd !== "string" ||
      !/^\d{1,10}\.\d{6}$/.test(reservation.reserved_usd) ||
      Number(reservation.reserved_usd) <= 0 ||
      Number(reservation.reserved_usd) > 100
    )
      throw reviewError();
  }
  if (
    discoveryComplete(value) &&
    ((value.counts.inserted ?? 0) + (value.counts.updated ?? 0) !==
      value.job_ids.length ||
      (value.counts.discovered ?? 0) !==
        value.job_ids.length + (value.counts.skipped ?? 0))
  )
    throw reviewError();
  return value;
}
export function discoveryComplete(value: JobDiscoveryRun): boolean {
  return (
    value.local_intake_complete === true &&
    value.rankings_complete === true &&
    typeof value.finished_at === "string" &&
    value.finished_at.length > 0
  );
}
async function get(attempt: DiscoveryAttempt): Promise<JobDiscoveryRun> {
  return validateDiscoveryRun(
    await api<JobDiscoveryRun>(path(attempt.requestId)),
    attempt,
  );
}
/** Explicit saved GET only; mounting/reloading a page cannot create provider or local completion work. */
export async function inspectDiscovery(): Promise<JobDiscoveryRun> {
  return withDiscoveryAttemptLock(async () => {
    const attempt = readDiscoveryAttempt();
    if (!attempt) throw reviewError();
    return get(attempt);
  });
}
/** Original PUT needs explicit consent. An existing saved run is only read back, never re-dispatched. */
export async function recoverDiscovery(
  input: Record<string, unknown>,
  mayStart = false,
): Promise<JobDiscoveryRun> {
  return withDiscoveryAttemptLock(async () => {
    let attempt = readDiscoveryAttempt();
    if (!attempt) {
      if (
        !mayStart ||
        typeof input.source !== "string" ||
        !source.test(input.source)
      )
        throw reviewError();
      attempt = { requestId: crypto.randomUUID(), source: input.source };
      // No search terms, candidate/profile facts or credentials are persisted in browser storage.
      localStorage.setItem(storageKey, JSON.stringify(attempt));
    } else {
      let saved: JobDiscoveryRun | null = null;
      try {
        saved = await get(attempt);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
      if (saved) return saved;
      if (!mayStart || input.source !== attempt.source)
        throw new Error(
          "The original search has no saved admission yet. Review and authorize that same source before retrying.",
        );
    }
    return validateDiscoveryRun(
      await api<JobDiscoveryRun>(path(attempt.requestId), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
      attempt,
    );
  });
}
export async function prepareNewDiscovery(
  reviewedRequest: string,
): Promise<void> {
  await withDiscoveryAttemptLock(async () => {
    const attempt = readDiscoveryAttempt();
    if (!attempt || attempt.requestId !== reviewedRequest) throw reviewError();
    const saved = await get(attempt);
    if (
      !discoveryComplete(saved) ||
      readDiscoveryAttempt()?.requestId !== attempt.requestId
    )
      throw reviewError();
    // Removes only the reviewed browser pointer. Database history and original source admission remain intact.
    const rawRead = localStorage.getItem("job-discovery-read:v1");
    if (rawRead) {
      let read: { requestId?: unknown; readId?: unknown };
      try {
        read = JSON.parse(rawRead);
      } catch {
        throw reviewError();
      }
      if (
        !read ||
        read.requestId !== attempt.requestId ||
        typeof read.readId !== "string" ||
        !uuid.test(read.readId)
      )
        throw reviewError();
      localStorage.removeItem("job-discovery-read:v1");
    }
    localStorage.removeItem(storageKey);
  });
}
