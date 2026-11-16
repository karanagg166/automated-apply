import { beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import {
  prepareReviewedDraftReplacement,
  readDraftAttempt,
  recoverLocalDraft,
  type LocalDraftResult,
} from "@/features/outreach-draft-attempt";
vi.mock("@/lib/api", () => ({ api: vi.fn() }));
const contact = "11111111-1111-4111-8111-111111111111",
  id = "22222222-2222-4222-8222-222222222222",
  other = "33333333-3333-4333-8333-333333333333";
const saved: LocalDraftResult = {
  id,
  contact_id: contact,
  draft_revision: 1,
  delivery_status: "not_attempted",
  send_attempt_id: null,
  sent_at: null,
};
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(saved);
});
it("stores one local request key before POST and recovers a lost response with identical scope", async () => {
  vi.mocked(api).mockImplementationOnce(async () => {
    expect(readDraftAttempt(contact)?.requestId).toMatch(/^[a-f0-9-]{36}$/);
    throw new Error("Fictional response loss");
  });
  await expect(recoverLocalDraft(contact)).rejects.toThrow("response loss");
  const first = JSON.parse(vi.mocked(api).mock.calls[0][1]?.body as string);
  await recoverLocalDraft(contact);
  const second = JSON.parse(vi.mocked(api).mock.calls[1][1]?.body as string);
  expect(second).toEqual(first);
  expect(second).toMatchObject({
    contact_id: contact,
    use_llm: false,
    purpose: "exploratory",
    writing_style: "concise",
  });
  expect(readDraftAttempt(contact)?.draftId).toBe(id);
  expect(Object.keys(readDraftAttempt(contact)!).sort()).toEqual([
    "contactId",
    "draftId",
    "requestId",
  ]);
});
it("uses only GET once the saved draft ID is known", async () => {
  await recoverLocalDraft(contact);
  await recoverLocalDraft(contact);
  expect(vi.mocked(api).mock.calls[1]).toEqual([`outreach/drafts/${id}`]);
});
it("keeps a needs-input request without inventing an ID and retries the same reviewed local scope", async () => {
  vi.mocked(api).mockResolvedValueOnce({
    status: "needs_input",
    missing_information: ["verified_project_contribution_required"],
  });
  await expect(recoverLocalDraft(contact)).rejects.toThrow(
    "saved draft was not confirmed",
  );
  const retained = readDraftAttempt(contact);
  expect(retained?.draftId).toBeUndefined();
  await recoverLocalDraft(contact);
  expect(
    JSON.parse(vi.mocked(api).mock.calls[1][1]?.body as string).idempotency_key,
  ).toBe(retained?.requestId);
});
it("stops before network when durable request storage fails", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Fictional storage failure");
  });
  await expect(recoverLocalDraft(contact)).rejects.toThrow("storage failure");
  expect(api).not.toHaveBeenCalled();
});
it("retains the original request key when saving the known draft ID fails", async () => {
  const set = Storage.prototype.setItem;
  let writes = 0;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    k,
    v,
  ) {
    writes += 1;
    if (writes > 1) throw new Error("Fictional later storage failure");
    set.call(this, k, v);
  });
  await recoverLocalDraft(contact);
  const retained = readDraftAttempt(contact);
  expect(retained?.draftId).toBeUndefined();
  await recoverLocalDraft(contact);
  expect(
    JSON.parse(vi.mocked(api).mock.calls[1][1]?.body as string).idempotency_key,
  ).toBe(retained?.requestId);
});
it("refuses malformed, foreign or private-field recovery metadata before a request", async () => {
  for (const raw of [
    "invalid",
    "null",
    JSON.stringify({ requestId: id, contactId: other }),
    JSON.stringify({ requestId: id, contactId: contact, draftId: "bad" }),
    JSON.stringify({ requestId: id, contactId: contact, body: "Private body" }),
  ]) {
    localStorage.setItem(`outreach-draft-attempt:${contact}`, raw);
    await expect(recoverLocalDraft(contact)).rejects.toThrow(
      "Review the saved draft request",
    );
  }
  expect(api).not.toHaveBeenCalled();
});
it("refuses unbound responses or a changed GET identity without replacing the retained pointer", async () => {
  vi.mocked(api).mockResolvedValueOnce({ ...saved, contact_id: other });
  await expect(recoverLocalDraft(contact)).rejects.toThrow(
    "saved draft was not confirmed",
  );
  expect(readDraftAttempt(contact)?.draftId).toBeUndefined();
  await recoverLocalDraft(contact);
  vi.mocked(api).mockResolvedValueOnce({ ...saved, id: other });
  await expect(recoverLocalDraft(contact)).rejects.toThrow(
    "saved draft was not confirmed",
  );
  expect(readDraftAttempt(contact)?.draftId).toBe(id);
});
it("only replaces a reviewed matching local pointer and preserves uncertain or sent history", async () => {
  await recoverLocalDraft(contact);
  const original = readDraftAttempt(contact);
  for (const current of [
    { ...saved, id: other },
    { ...saved, send_attempt_id: other },
    { ...saved, sent_at: "2026-11-17T00:00:00Z" },
    { ...saved, delivery_status: "outcome_unknown" },
    { ...saved, delivery_status: "failed_before_send" },
  ]) {
    expect(() => prepareReviewedDraftReplacement(current)).toThrow(
      "Review the saved draft request",
    );
    expect(readDraftAttempt(contact)).toEqual(original);
  }
  prepareReviewedDraftReplacement(saved);
  expect(readDraftAttempt(contact)).toBeNull();
  await recoverLocalDraft(contact);
  expect(readDraftAttempt(contact)?.requestId).not.toBe(original?.requestId);
});
