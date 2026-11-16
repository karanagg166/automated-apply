"use client";
import { api } from "@/lib/api";
export type LocalDraftResult = {
  id: string;
  contact_id: string;
  delivery_status: string;
  send_attempt_id?: string | null;
  sent_at?: string | null;
  draft_revision: number;
  [key: string]: unknown;
};
type Attempt = { requestId: string; contactId: string; draftId?: string };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const key = (contact: string) => `outreach-draft-attempt:${contact}`;
const reviewError = () =>
  new Error(
    "Review the saved draft request before preparing another local draft.",
  );
export function readDraftAttempt(contact: string): Attempt | null {
  if (!uuid.test(contact)) throw reviewError();
  const raw = localStorage.getItem(key(contact));
  if (!raw) return null;
  if (raw.length > 512) throw reviewError();
  let value: Attempt;
  try {
    value = JSON.parse(raw);
  } catch {
    throw reviewError();
  }
  if (
    !value ||
    Array.isArray(value) ||
    Object.keys(value).some(
      (k) => !["requestId", "contactId", "draftId"].includes(k),
    ) ||
    !uuid.test(value.requestId) ||
    value.contactId !== contact ||
    (value.draftId != null && !uuid.test(value.draftId))
  )
    throw reviewError();
  return value;
}
export async function recoverLocalDraft(
  contact: string,
): Promise<LocalDraftResult> {
  let attempt = readDraftAttempt(contact);
  if (!attempt) {
    attempt = { requestId: crypto.randomUUID(), contactId: contact };
    // A failed write stops the request. These UUIDs contain no message or personal facts.
    localStorage.setItem(key(contact), JSON.stringify(attempt));
  }
  const result = attempt.draftId
    ? await api<LocalDraftResult>(`outreach/drafts/${attempt.draftId}`)
    : await api<LocalDraftResult>("outreach/drafts", {
        method: "POST",
        body: JSON.stringify({
          contact_id: contact,
          purpose: "exploratory",
          writing_style: "concise",
          use_llm: false,
          idempotency_key: attempt.requestId,
        }),
      });
  if (
    !result ||
    !uuid.test(result.id) ||
    result.contact_id !== contact ||
    (attempt.draftId && result.id !== attempt.draftId) ||
    !Number.isInteger(result.draft_revision) ||
    result.draft_revision < 1
  ) {
    throw new Error(
      "A saved draft was not confirmed. Review the contact evidence and missing facts, then recover this same request.",
    );
  }
  try {
    localStorage.setItem(
      key(contact),
      JSON.stringify({ ...attempt, draftId: result.id }),
    );
  } catch {
    /* Original key still recovers the committed local draft. */
  }
  return result;
}
export function prepareReviewedDraftReplacement(draft: LocalDraftResult): void {
  const attempt = readDraftAttempt(draft.contact_id);
  if (
    !uuid.test(draft.id) ||
    (attempt && attempt.draftId !== draft.id) ||
    draft.delivery_status !== "not_attempted" ||
    draft.send_attempt_id ||
    draft.sent_at ||
    !Number.isInteger(draft.draft_revision) ||
    draft.draft_revision < 1
  )
    throw reviewError();
  // Preserve the old draft and its history. Only the small browser recovery pointer changes.
  localStorage.removeItem(key(draft.contact_id));
}
