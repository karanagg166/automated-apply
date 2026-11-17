"use client";
import { api, ApiError } from "@/lib/api";
export type ResearchAttempt = { companyId: string; requestId: string };
export type ResearchResult = {
  request_id: string;
  company_id?: string | null;
  status: string;
  recorded_state?: string;
  provider_status?: string;
  provider_response_retained?: boolean;
  provider_request_attempted?: boolean;
  persistence_status?: string;
  people: unknown[];
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const key = (company: string) => `people-research-attempt:${company}`;
const path = (request: string) =>
  `rust-agent/research/people/requests/${request}`;
const reviewError = () =>
  new Error(
    "Recover and review the saved research request before preparing another search.",
  );
export function readResearchAttempt(company: string): ResearchAttempt | null {
  if (!uuid.test(company)) throw reviewError();
  const raw = localStorage.getItem(key(company));
  if (!raw) return null;
  if (raw.length > 256) throw reviewError();
  let value: ResearchAttempt;
  try {
    value = JSON.parse(raw);
  } catch {
    throw reviewError();
  }
  if (
    !value ||
    Array.isArray(value) ||
    Object.keys(value).some((k) => !["companyId", "requestId"].includes(k)) ||
    value.companyId !== company ||
    typeof value.requestId !== "string" ||
    !uuid.test(value.requestId)
  )
    throw reviewError();
  return value;
}
async function locked<T>(
  company: string,
  operation: () => Promise<T>,
): Promise<T> {
  if (!uuid.test(company)) throw reviewError();
  if (!navigator.locks?.request)
    throw new Error(
      "This browser cannot safely recover research requests. Use a current Brave, Edge or Safari window.",
    );
  return navigator.locks.request(key(company), operation);
}
function validate(
  value: ResearchResult,
  attempt: ResearchAttempt,
): ResearchResult {
  if (
    !value ||
    value.request_id !== attempt.requestId ||
    (value.company_id != null && value.company_id !== attempt.companyId) ||
    typeof value.status !== "string" ||
    !Array.isArray(value.people) ||
    value.people.length > 20
  )
    throw reviewError();
  return value;
}
export async function recoverResearch(
  company: string,
  input: Record<string, unknown>,
  mayStartNewDispatch = false,
): Promise<ResearchResult> {
  return locked(company, async () => {
    let attempt = readResearchAttempt(company);
    if (!attempt) {
      if (!mayStartNewDispatch) throw reviewError();
      attempt = { companyId: company, requestId: crypto.randomUUID() };
      // Only UUIDs are persisted; a failed write prevents the request.
      localStorage.setItem(key(company), JSON.stringify(attempt));
    } else {
      let saved: ResearchResult | null = null;
      try {
        saved = validate(
          await api<ResearchResult>(path(attempt.requestId)),
          attempt,
        );
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
      if (
        saved &&
        (saved.recorded_state !== "finding_retained" ||
          !["success", "partial", "no_results"].includes(
            saved.provider_status || "",
          ))
      )
        return saved;
      if (!saved && !mayStartNewDispatch)
        throw new Error(
          "No saved search was found. Review and authorize this limited search before continuing.",
        );
      // A retained finding may complete locally. The server binds the exact original input.
    }
    return validate(
      await api<ResearchResult>(path(attempt.requestId), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
      attempt,
    );
  });
}
export async function prepareNewResearch(
  company: string,
  reviewedRequest: string,
): Promise<void> {
  await locked(company, async () => {
    const attempt = readResearchAttempt(company);
    if (!attempt || attempt.requestId !== reviewedRequest) throw reviewError();
    const result = validate(
      await api<ResearchResult>(path(attempt.requestId)),
      attempt,
    );
    const terminal =
      result.recorded_state === "completed" ||
      (result.recorded_state === "finding_retained" &&
        result.provider_response_retained === true &&
        ["authentication_required", "rate_limited", "upstream_error"].includes(
          result.provider_status || "",
        )) ||
      (result.status === "not_dispatched" &&
        result.provider_request_attempted === false);
    const current = readResearchAttempt(company);
    if (!terminal || current?.requestId !== attempt.requestId)
      throw reviewError();
    // Database history and its consumed allowance remain intact.
    localStorage.removeItem(key(company));
  });
}
