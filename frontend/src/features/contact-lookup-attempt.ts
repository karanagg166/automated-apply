"use client";
import { api } from "@/lib/api";
export type LookupResult = {
  id: string;
  state: string;
  errors?: string[];
  [key: string]: unknown;
};
export type LookupAttempt = {
  id: string;
  provider: "apollo" | "signalhire";
  runId?: string;
};
const key = (company: string) => `contact-lookup-attempt:${company}`;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export function readLookupAttempt(company: string): LookupAttempt | null {
  const raw = localStorage.getItem(key(company));
  if (!raw) return null;
  let value: LookupAttempt;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error(
      "The retained lookup needs manual history review before another request.",
    );
  }
  if (
    !value ||
    !uuid.test(value.id) ||
    !["apollo", "signalhire"].includes(value.provider) ||
    (value.runId != null && !uuid.test(value.runId))
  ) {
    throw new Error(
      "The retained lookup needs manual history review before another request.",
    );
  }
  return value;
}
export async function runLookupAttempt(
  company: string,
  provider: string,
): Promise<LookupResult> {
  let attempt = readLookupAttempt(company);
  if (!attempt) {
    if (provider !== "apollo" && provider !== "signalhire")
      throw new Error("Choose a supported lookup provider.");
    attempt = { id: crypto.randomUUID(), provider };
    // Storage must succeed before any potentially billable request.
    localStorage.setItem(key(company), JSON.stringify(attempt));
  }
  if (attempt.provider !== provider)
    throw new Error(
      "Review the retained lookup before choosing a different provider.",
    );
  const result = attempt.runId
    ? await api<LookupResult>(`contact-enrichment/runs/${attempt.runId}`)
    : await api<LookupResult>(`companies/${company}/contacts/enrich`, {
        method: "POST",
        body: JSON.stringify({
          providers: [attempt.provider],
          max_people: 1,
          target_roles: ["founder", "cto"],
          allow_paid: true,
          allow_fallback: false,
          include_candidates: false,
          idempotency_key: attempt.id,
        }),
      });
  if (!uuid.test(result.id))
    throw new Error(
      "The lookup response could not be linked to saved history. Recover the retained request before another attempt.",
    );
  // If this write fails, the original durable idempotency key still recovers history.
  try {
    localStorage.setItem(
      key(company),
      JSON.stringify({ ...attempt, runId: result.id }),
    );
  } catch {}
  return result;
}
export function clearReviewedLookupAttempt(
  company: string,
  result: LookupResult,
) {
  const attempt = readLookupAttempt(company);
  if (
    !attempt ||
    attempt.runId !== result.id ||
    ["billing_uncertain", "queued", "running"].includes(result.state)
  ) {
    throw new Error(
      "Reconcile the retained lookup before preparing another request.",
    );
  }
  localStorage.removeItem(key(company));
}
