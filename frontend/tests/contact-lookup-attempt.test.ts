import { beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import {
  clearReviewedLookupAttempt,
  readLookupAttempt,
  runLookupAttempt,
} from "@/features/contact-lookup-attempt";
vi.mock("@/lib/api", () => ({ api: vi.fn() }));
const company = "11111111-1111-4111-8111-111111111111",
  run = "22222222-2222-4222-8222-222222222222";
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue({ id: run, state: "completed", errors: [] });
});
it("persists one idempotency key before submission and recovers lost response with the same request", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("Fictional response loss"));
  await expect(runLookupAttempt(company, "apollo")).rejects.toThrow(
    "response loss",
  );
  const retained = readLookupAttempt(company);
  expect(retained?.id).toMatch(/^[a-f0-9-]{36}$/);
  await runLookupAttempt(company, "apollo");
  const first = JSON.parse(vi.mocked(api).mock.calls[0][1]?.body as string);
  const second = JSON.parse(vi.mocked(api).mock.calls[1][1]?.body as string);
  expect(first).toEqual(second);
  expect(first.idempotency_key).toBe(retained?.id);
  expect(first).toMatchObject({
    providers: ["apollo"],
    max_people: 1,
    allow_fallback: false,
    include_candidates: false,
  });
  expect(readLookupAttempt(company)?.runId).toBe(run);
});
it("uses GET-only saved run recovery once its ID is known", async () => {
  await runLookupAttempt(company, "apollo");
  await runLookupAttempt(company, "apollo");
  expect(vi.mocked(api).mock.calls[1]).toEqual([
    `contact-enrichment/runs/${run}`,
  ]);
});
it("refuses a provider switch or a malformed retained request before network work", async () => {
  await runLookupAttempt(company, "apollo");
  vi.mocked(api).mockClear();
  await expect(runLookupAttempt(company, "signalhire")).rejects.toThrow(
    /retained lookup/,
  );
  expect(api).not.toHaveBeenCalled();
  localStorage.setItem(`contact-lookup-attempt:${company}`, "invalid JSON");
  await expect(runLookupAttempt(company, "apollo")).rejects.toThrow(
    /manual history review/,
  );
  expect(api).not.toHaveBeenCalled();
});
it("cannot discard a running or uncertain lookup and only clears the reviewed matching saved run", async () => {
  await runLookupAttempt(company, "apollo");
  for (const state of ["running", "queued", "billing_uncertain"]) {
    expect(() =>
      clearReviewedLookupAttempt(company, { id: run, state }),
    ).toThrow(/Reconcile/);
  }
  expect(() =>
    clearReviewedLookupAttempt(company, {
      id: "33333333-3333-4333-8333-333333333333",
      state: "completed",
    }),
  ).toThrow(/Reconcile/);
  clearReviewedLookupAttempt(company, { id: run, state: "completed" });
  expect(readLookupAttempt(company)).toBeNull();
});
it("refuses to send if the request identity cannot be stored", async () => {
  const storage = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("Fictional storage failure");
    });
  try {
    await expect(runLookupAttempt(company, "apollo")).rejects.toThrow(
      "storage failure",
    );
    expect(api).not.toHaveBeenCalled();
  } finally {
    storage.mockRestore();
  }
});
it("rejects an unbound response and keeps the original key for recovery", async () => {
  vi.mocked(api).mockResolvedValueOnce({ state: "completed", id: "not-a-run" });
  await expect(runLookupAttempt(company, "apollo")).rejects.toThrow(
    /saved history/,
  );
  expect(readLookupAttempt(company)?.id).toBeTruthy();
  expect(readLookupAttempt(company)?.runId).toBeUndefined();
});
