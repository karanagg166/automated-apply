import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import {
  prepareNewResearch,
  readResearchAttempt,
  recoverResearch,
  type ResearchResult,
} from "@/features/people-research-attempt";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const company = "10000000-0000-0000-0000-000000000001";
const request = "20000000-0000-0000-0000-000000000002";
const newer = "30000000-0000-0000-0000-000000000003";
const key = `people-research-attempt:${company}`;
const path = `rust-agent/research/people/requests/${request}`;
const input = {
  company_name: "PRIVATE_FICTIONAL_COMPANY_CANARY",
  source: "public_search",
  allow_paid: true,
};
const complete = (): ResearchResult => ({
  request_id: request,
  company_id: company,
  status: "success",
  recorded_state: "completed",
  persistence_status: "imported",
  people: [],
});
const pointer = (id = request) =>
  localStorage.setItem(
    key,
    JSON.stringify({ companyId: company, requestId: id }),
  );
beforeEach(() => {
  vi.mocked(api).mockReset();
  localStorage.clear();
  vi.spyOn(crypto, "randomUUID").mockReturnValue(request);
  let pending: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: vi.fn((_name: string, work: () => Promise<unknown>) => {
        const result = pending.then(work);
        pending = result.then(
          () => undefined,
          () => undefined,
        );
        return result;
      }),
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "locks");
});
describe("durable professional research", () => {
  it("saves only UUIDs before the first approved native PUT and never uses the legacy paid POST", async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => {
      expect(readResearchAttempt(company)?.requestId).toBe(request);
      expect(options?.method).toBe("PUT");
      return complete();
    });
    expect(await recoverResearch(company, input, true)).toEqual(complete());
    expect(api).toHaveBeenCalledExactlyOnceWith(path, {
      method: "PUT",
      body: JSON.stringify(input),
    });
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual({
      companyId: company,
      requestId: request,
    });
    expect(localStorage.getItem(key)).not.toContain(
      "PRIVATE_FICTIONAL_COMPANY_CANARY",
    );
  });
  it("keeps the original pointer after response loss and reads its result without a second PUT", async () => {
    vi.mocked(api).mockRejectedValueOnce(new ApiError(504, "Response lost"));
    await expect(recoverResearch(company, input, true)).rejects.toThrow();
    vi.mocked(api).mockResolvedValueOnce(complete());
    expect(await recoverResearch(company, input)).toEqual(complete());
    expect(
      vi.mocked(api).mock.calls.map(([, options]) => options?.method || "GET"),
    ).toEqual(["PUT", "GET"]);
    expect(readResearchAttempt(company)?.requestId).toBe(request);
  });
  it("requires fresh explicit approval when a retained pointer has no durable server admission", async () => {
    pointer();
    vi.mocked(api).mockRejectedValueOnce(new ApiError(404, "Not admitted"));
    await expect(recoverResearch(company, input)).rejects.toThrow("authorize");
    expect(api).toHaveBeenCalledTimes(1);
    vi.mocked(api)
      .mockRejectedValueOnce(new ApiError(404, "Not admitted"))
      .mockResolvedValueOnce(complete());
    expect(await recoverResearch(company, input, true)).toEqual(complete());
    expect(vi.mocked(api).mock.calls[2]).toEqual([
      path,
      { method: "PUT", body: JSON.stringify(input) },
    ]);
    expect(readResearchAttempt(company)?.requestId).toBe(request);
  });
  it("may finish a retained finding locally with the same request while preserving a conflicting input", async () => {
    pointer();
    const finding = {
      ...complete(),
      recorded_state: "finding_retained",
      provider_status: "success",
      persistence_status: "not_imported",
    };
    vi.mocked(api)
      .mockResolvedValueOnce(finding)
      .mockResolvedValueOnce(complete());
    expect(await recoverResearch(company, input)).toEqual(complete());
    expect(vi.mocked(api).mock.calls[1][1]?.method).toBe("PUT");
    vi.mocked(api)
      .mockResolvedValueOnce(finding)
      .mockRejectedValueOnce(new ApiError(409, "Original input changed"));
    await expect(
      recoverResearch(company, { ...input, company_name: "Changed" }),
    ).rejects.toThrow();
    expect(readResearchAttempt(company)?.requestId).toBe(request);
  });
  it("retains unknown and held requests without another PUT or pointer removal", async () => {
    pointer();
    for (const [status, state] of [
      ["outcome_unknown", "dispatch_admitted"],
      ["needs_review", "held"],
    ]) {
      const held = {
        ...complete(),
        status,
        recorded_state: state,
        persistence_status: "held",
      };
      vi.mocked(api).mockResolvedValueOnce(held);
      expect(await recoverResearch(company, input)).toEqual(held);
      vi.mocked(api).mockResolvedValueOnce(held);
      await expect(prepareNewResearch(company, request)).rejects.toThrow();
    }
    expect(
      vi.mocked(api).mock.calls.every(([, options]) => options == null),
    ).toBe(true);
    expect(readResearchAttempt(company)?.requestId).toBe(request);
  });
  it("does no network work when storage, approval or browser coordination is unavailable", async () => {
    await expect(recoverResearch(company, input)).rejects.toThrow();
    expect(api).not.toHaveBeenCalled();
    const set = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("Storage unavailable");
      });
    await expect(recoverResearch(company, input, true)).rejects.toThrow(
      "Storage",
    );
    expect(api).not.toHaveBeenCalled();
    set.mockRestore();
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: undefined,
    });
    await expect(recoverResearch(company, input, true)).rejects.toThrow(
      "browser",
    );
    expect(api).not.toHaveBeenCalled();
  });
  it("rejects malformed local state and mismatched result or company identities", async () => {
    localStorage.setItem(
      key,
      JSON.stringify({
        companyId: company,
        requestId: request,
        private: "unexpected",
      }),
    );
    await expect(recoverResearch(company, input, true)).rejects.toThrow();
    expect(api).not.toHaveBeenCalled();
    pointer();
    vi.mocked(api).mockResolvedValueOnce({ ...complete(), request_id: newer });
    await expect(recoverResearch(company, input)).rejects.toThrow();
    vi.mocked(api).mockResolvedValueOnce({ ...complete(), company_id: newer });
    await expect(recoverResearch(company, input)).rejects.toThrow();
    expect(readResearchAttempt(company)?.requestId).toBe(request);
  });
  it("serializes cooperating tabs so concurrent recovery cannot create different fresh requests", async () => {
    vi.mocked(api).mockResolvedValue(complete());
    const [a, b] = await Promise.all([
      recoverResearch(company, input, true),
      recoverResearch(company, input, true),
    ]);
    expect(a).toEqual(b);
    expect(
      vi.mocked(api).mock.calls.map(([, options]) => options?.method || "GET"),
    ).toEqual(["PUT", "GET"]);
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
  });
  it("requires an independent terminal read and exact pointer before preparing a new search", async () => {
    pointer();
    await expect(prepareNewResearch(company, newer)).rejects.toThrow();
    expect(api).not.toHaveBeenCalled();
    vi.mocked(api).mockImplementationOnce(async () => {
      pointer(newer);
      return complete();
    });
    await expect(prepareNewResearch(company, request)).rejects.toThrow();
    expect(readResearchAttempt(company)?.requestId).toBe(newer);
    pointer();
    vi.mocked(api).mockResolvedValueOnce(complete());
    await prepareNewResearch(company, request);
    expect(readResearchAttempt(company)).toBeNull();
    expect(
      vi
        .mocked(api)
        .mock.calls.every(([, options]) => options?.method !== "DELETE"),
    ).toBe(true);
    await expect(recoverResearch(company, input)).rejects.toThrow();
  });
  it("preserves history and locally reserved cost when reviewing a known provider failure", async () => {
    pointer();
    vi.mocked(api).mockResolvedValueOnce({
      ...complete(),
      recorded_state: "finding_retained",
      status: "rate_limited",
      provider_status: "rate_limited",
      provider_response_retained: true,
    });
    await prepareNewResearch(company, request);
    expect(readResearchAttempt(company)).toBeNull();
    expect(api).toHaveBeenCalledExactlyOnceWith(path);
  });
});
