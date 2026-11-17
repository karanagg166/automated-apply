import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import {
  inspectDiscovery,
  prepareNewDiscovery,
  readDiscoveryAttempt,
  recoverDiscovery,
} from "@/features/job-discovery-attempt";
import type { JobDiscoveryRun } from "@/features/job-discovery";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const request = "20000000-0000-0000-0000-000000000002";
const path = `discovery/runs/${request}`;
const key = "job-discovery-attempt:v1";
const input = {
  source: "arbeitnow",
  query: { keywords: ["PRIVATE_SEARCH_CANARY"] },
  use_profile: true,
};
const completed = (): JobDiscoveryRun => ({
  id: request,
  source: "arbeitnow",
  status: "success",
  counts: { discovered: 0, inserted: 0 },
  errors: [],
  started_at: "2026-11-17T00:00:00Z",
  finished_at: "2026-11-17T00:00:01Z",
  provider_run_id: null,
  usage: { finding_retained: true },
  rankings: [],
  job_ids: [],
  local_intake_complete: true,
  rankings_complete: true,
});
const pending = (): JobDiscoveryRun => ({
  ...completed(),
  status: "recovery_required",
  finished_at: null,
  usage: { finding_retained: false },
  local_intake_complete: false,
  rankings_complete: false,
});
const pointer = () =>
  localStorage.setItem(
    key,
    JSON.stringify({ requestId: request, source: "arbeitnow" }),
  );
beforeEach(() => {
  vi.mocked(api).mockReset();
  localStorage.clear();
  vi.spyOn(crypto, "randomUUID").mockReturnValue(request);
  let tail: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: vi.fn((_key: string, work: () => Promise<unknown>) => {
        const result = tail.then(work);
        tail = result.catch(() => undefined);
        return result;
      }),
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "locks");
});
describe("durable job discovery", () => {
  it("recovers a native paid result using saved GET and local completion without renewed paid opt-in or PUT", async () => {
    localStorage.setItem(
      key,
      JSON.stringify({ requestId: request, source: "naukri" }),
    );
    const paid = {
      ...completed(),
      source: "naukri",
      original_scope_available: true,
      billing_final: false,
      reservation: {
        reserved_usd: "0.100001",
        accounting: "full_cap_retained",
        billing_final: false,
      },
    };
    vi.mocked(api).mockResolvedValueOnce({
      ...paid,
      status: "running",
      finished_at: null,
      rankings_complete: false,
      local_intake_complete: false,
    });
    vi.mocked(api).mockResolvedValueOnce(paid);
    expect(
      await recoverDiscovery({ source: "naukri", allow_paid: false }),
    ).toEqual(paid);
    expect(api).toHaveBeenNthCalledWith(1, path);
    expect(api).toHaveBeenNthCalledWith(2, `${path}/complete`, {
      method: "POST",
      body: "{}",
    });
    expect(
      vi
        .mocked(api)
        .mock.calls.every(([, options]) => options?.method !== "PUT"),
    ).toBe(true);
    expect(readDiscoveryAttempt()?.source).toBe("naukri");
  });
  it("keeps an unknown paid start on GET only and preserves its pointer and full reservation", async () => {
    localStorage.setItem(
      key,
      JSON.stringify({ requestId: request, source: "naukri" }),
    );
    const paid = {
      ...pending(),
      source: "naukri",
      original_scope_available: true,
      billing_final: false,
      reservation: {
        reserved_usd: "0.100001",
        accounting: "full_cap_retained",
        billing_final: false,
      },
    };
    vi.mocked(api).mockResolvedValue(paid);
    expect(
      await recoverDiscovery({ source: "naukri", allow_paid: true }, true),
    ).toEqual(paid);
    expect(api).toHaveBeenCalledExactlyOnceWith(path);
    await expect(prepareNewDiscovery(request)).rejects.toThrow();
    expect(readDiscoveryAttempt()?.requestId).toBe(request);
  });
  it("refuses native paid results with missing, final, refunded or invalid reservations before pointer release", async () => {
    localStorage.setItem(
      key,
      JSON.stringify({ requestId: request, source: "naukri" }),
    );
    const base = {
      ...completed(),
      source: "naukri",
      original_scope_available: true,
      billing_final: false,
      reservation: {
        reserved_usd: "0.100001",
        accounting: "full_cap_retained",
        billing_final: false,
      },
    };
    for (const corrupt of [
      { ...base, reservation: undefined },
      { ...base, billing_final: true },
      { ...base, reservation: { ...base.reservation, accounting: "refunded" } },
      { ...base, reservation: { ...base.reservation, reserved_usd: "NaN" } },
      {
        ...base,
        reservation: { ...base.reservation, reserved_usd: "100.000001" },
      },
      {
        ...base,
        reservation: { ...base.reservation, reserved_usd: "0.000000" },
      },
    ]) {
      vi.mocked(api).mockResolvedValue(corrupt);
      await expect(prepareNewDiscovery(request)).rejects.toThrow();
      expect(readDiscoveryAttempt()?.source).toBe("naukri");
    }
  });
  it("persists only request UUID and source before original approved PUT", async () => {
    vi.mocked(api).mockImplementation(async () => {
      expect(readDiscoveryAttempt()).toEqual({
        requestId: request,
        source: "arbeitnow",
      });
      expect(localStorage.getItem(key)).not.toContain("CANARY");
      return completed();
    });
    expect(await recoverDiscovery(input, true)).toEqual(completed());
    expect(api).toHaveBeenCalledExactlyOnceWith(path, {
      method: "PUT",
      body: JSON.stringify(input),
    });
  });
  it("performs no request without original authorization or if durable storage fails", async () => {
    await expect(recoverDiscovery(input)).rejects.toThrow();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage denied");
    });
    await expect(recoverDiscovery(input, true)).rejects.toThrow(
      "Storage denied",
    );
    expect(api).not.toHaveBeenCalled();
  });
  it("retains response-loss pointer and recovers terminal GET without another PUT", async () => {
    vi.mocked(api).mockRejectedValueOnce(new ApiError(504, "Response lost"));
    await expect(recoverDiscovery(input, true)).rejects.toThrow();
    vi.mocked(api).mockResolvedValueOnce(completed());
    expect(await recoverDiscovery(input)).toEqual(completed());
    expect(
      vi.mocked(api).mock.calls.map(([, v]) => v?.method || "GET"),
    ).toEqual(["PUT", "GET"]);
    expect(readDiscoveryAttempt()?.requestId).toBe(request);
  });
  it("completes a retained finding using an empty local-only POST and the original UUID", async () => {
    pointer();
    vi.mocked(api)
      .mockResolvedValueOnce({
        ...pending(),
        usage: { finding_retained: true },
      })
      .mockResolvedValueOnce(completed());
    expect(
      await recoverDiscovery({
        source: "changed_source",
        query: { keywords: ["CHANGED_PRIVATE_CANARY"] },
      }),
    ).toEqual(completed());
    expect(api).toHaveBeenNthCalledWith(1, path);
    expect(api).toHaveBeenNthCalledWith(2, `${path}/complete`, {
      method: "POST",
      body: "{}",
    });
  });
  it("never turns unknown provider work into another GET batch or local completion", async () => {
    pointer();
    vi.mocked(api).mockResolvedValue(pending());
    expect(await recoverDiscovery(input, true)).toEqual(pending());
    expect(api).toHaveBeenCalledExactlyOnceWith(path);
    await expect(prepareNewDiscovery(request)).rejects.toThrow();
    expect(readDiscoveryAttempt()?.requestId).toBe(request);
  });
  it("saved inspection uses GET only even if observations await local completion", async () => {
    pointer();
    const finding = { ...pending(), usage: { finding_retained: true } };
    vi.mocked(api).mockResolvedValue(finding);
    expect(await inspectDiscovery()).toEqual(finding);
    expect(api).toHaveBeenCalledExactlyOnceWith(path);
  });
  it("404 recovery requires new explicit consent and keeps the same source and UUID", async () => {
    pointer();
    vi.mocked(api).mockRejectedValueOnce(new ApiError(404, "No row"));
    await expect(recoverDiscovery(input)).rejects.toThrow();
    expect(api).toHaveBeenCalledTimes(1);
    vi.mocked(api)
      .mockRejectedValueOnce(new ApiError(404, "No row"))
      .mockResolvedValueOnce(completed());
    expect(await recoverDiscovery(input, true)).toEqual(completed());
    expect(api).toHaveBeenLastCalledWith(path, {
      method: "PUT",
      body: JSON.stringify(input),
    });
  });
  it("cannot abandon a missing or uncertain run to switch sources", async () => {
    pointer();
    vi.mocked(api).mockRejectedValue(new ApiError(404, "No row"));
    await expect(
      recoverDiscovery({ source: "remotive" }, true),
    ).rejects.toThrow();
    await expect(prepareNewDiscovery(request)).rejects.toThrow();
    expect(vi.mocked(api).mock.calls.every(([, v]) => !v?.method)).toBe(true);
    expect(readDiscoveryAttempt()?.source).toBe("arbeitnow");
  });
  it("serializes concurrent tabs so only one original PUT is made", async () => {
    vi.mocked(api).mockResolvedValue(completed());
    const results = await Promise.all([
      recoverDiscovery(input, true),
      recoverDiscovery(input, true),
    ]);
    expect(results).toEqual([completed(), completed()]);
    expect(
      vi.mocked(api).mock.calls.map(([, v]) => v?.method || "GET"),
    ).toEqual(["PUT", "GET"]);
  });
  it("clears only a matching reviewed terminal pointer and never deletes database history", async () => {
    pointer();
    vi.mocked(api).mockResolvedValue(completed());
    await expect(
      prepareNewDiscovery("30000000-0000-0000-0000-000000000003"),
    ).rejects.toThrow();
    expect(api).not.toHaveBeenCalled();
    await prepareNewDiscovery(request);
    expect(readDiscoveryAttempt()).toBeNull();
    expect(api).toHaveBeenCalledExactlyOnceWith(path);
  });
  it("fails closed on malformed storage, result identity or unsupported browser locks", async () => {
    localStorage.setItem(
      key,
      JSON.stringify({
        requestId: request,
        source: "arbeitnow",
        private_extra: true,
      }),
    );
    await expect(recoverDiscovery(input, true)).rejects.toThrow();
    expect(api).not.toHaveBeenCalled();
    pointer();
    vi.mocked(api).mockResolvedValue({
      ...completed(),
      id: "30000000-0000-0000-0000-000000000003",
    });
    await expect(inspectDiscovery()).rejects.toThrow();
    Reflect.deleteProperty(navigator, "locks");
    await expect(recoverDiscovery(input, true)).rejects.toThrow("Brave");
    expect(api).toHaveBeenCalledTimes(1);
  });
});
