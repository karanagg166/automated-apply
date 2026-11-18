import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import {
  inspectDiscoveryRead,
  recoverDiscoveryRead,
  prepareNextDiscoveryRead,
  readDiscoveryReadAttempt,
} from "@/features/job-discovery-read-attempt";
import type { DiscoveryReadResult } from "@/features/job-discovery-read-attempt";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const parent = "10000000-0000-0000-0000-000000000001",
  read = "20000000-0000-0000-0000-000000000002";
const base = `discovery/runs/${parent}`,
  path = `${base}/reads/${read}`;
const key = "job-discovery-read:v1";
const budget = {
  reserved_usd: "0.100001",
  accounting: "full_cap_retained",
  billing_final: false,
};
function owner() {
  return {
    id: parent,
    source: "naukri",
    status: "recovery_required",
    counts: { discovered: 0 },
    errors: [],
    started_at: "2026-11-17T00:00:00Z",
    finished_at: null,
    provider_run_id: "originalRun",
    rankings: [],
    job_ids: [],
    usage: { finding_retained: false },
    original_scope_available: true,
    billing_final: false,
    reservation: budget,
  };
}
function saved(): DiscoveryReadResult {
  return {
    request_id: parent,
    read_request_id: read,
    source: "naukri",
    recorded_state: "response_retained",
    status: "pending",
    finding_retained: false,
    local_merge_available: false,
    read_round_limit: 3,
    read_admissions: 1,
    round: 1,
    http_attempts: 1,
    http_responses: 1,
    http_counts_are_minimum: false,
    errors: [],
    admitted_at: "2026-11-17T00:00:00Z",
    expires_at: "2026-11-17T00:00:45Z",
    billing_final: false,
    provider_start_authorized: false,
    provider_abort_authorized: false,
    replay_authorized: false,
    application_dispatch: false,
    live_verified: false,
    reservation: budget,
  };
}
function pointer() {
  localStorage.setItem(
    key,
    JSON.stringify({ requestId: parent, readId: read }),
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.mocked(api).mockReset();
  localStorage.setItem(
    "job-discovery-attempt:v1",
    JSON.stringify({ requestId: parent, source: "naukri" }),
  );
  vi.spyOn(crypto, "randomUUID").mockReturnValue(read);
  let tail = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, operation: () => Promise<unknown>) => {
        const next = tail.then(operation);
        tail = next.then(
          () => undefined,
          () => undefined,
        );
        return next;
      },
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "locks");
});
it("does not create a read admission without explicit consent and keeps provider requests out of inspection", async () => {
  vi.mocked(api).mockResolvedValue(owner());
  await expect(recoverDiscoveryRead(false)).rejects.toThrow();
  expect(readDiscoveryReadAttempt()).toBeNull();
  expect(vi.mocked(api).mock.calls.every(([, opts]) => !opts?.method)).toBe(
    true,
  );
});
it("stores opaque read UUID before empty PUT and retains it on lost response", async () => {
  vi.mocked(api).mockImplementation(async (target, options) => {
    if (target === base) return owner();
    expect(target).toBe(path);
    expect(options).toMatchObject({ method: "PUT", body: "{}" });
    expect(readDiscoveryReadAttempt()).toEqual({
      requestId: parent,
      readId: read,
    });
    throw new ApiError(504, "Response lost");
  });
  await expect(recoverDiscoveryRead(true)).rejects.toThrow();
  expect(Object.keys(JSON.parse(localStorage.getItem(key)!)).sort()).toEqual([
    "readId",
    "requestId",
  ]);
  expect(localStorage.getItem(key)).not.toContain("originalRun");
});
it("unknown read outcome and same-key recovery return saved state without another PUT", async () => {
  pointer();
  const reply = {
    ...saved(),
    recorded_state: "operation_admitted",
    status: "outcome_unknown",
    http_counts_are_minimum: true,
    http_attempts: 0,
    http_responses: 0,
  };
  vi.mocked(api).mockImplementation(async (target) =>
    target === base ? owner() : reply,
  );
  const result = await recoverDiscoveryRead(true);
  expect(result.read).toEqual(reply);
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
  expect(readDiscoveryReadAttempt()?.readId).toBe(read);
});
it("complete pages recover locally then finish original discovery without another provider read", async () => {
  pointer();
  let merged = false;
  const complete = {
    ...owner(),
    status: "success",
    finished_at: "2026-11-17T00:02:00Z",
    local_intake_complete: true,
    rankings_complete: true,
  };
  vi.mocked(api).mockImplementation(async (target, options) => {
    if (target === base)
      return { ...owner(), usage: { finding_retained: merged } };
    if (target === path && !options)
      return { ...saved(), local_merge_available: true };
    if (target === `${path}/complete`) {
      merged = true;
      return { ...saved(), finding_retained: true };
    }
    if (target === `${base}/complete`) return complete;
    throw new Error("Unexpected request");
  });
  const result = await recoverDiscoveryRead(false);
  expect(result.run).toEqual(complete);
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(([, options]) => options?.method === "POST")
      .map(([p]) => p),
  ).toEqual([`${path}/complete`, `${base}/complete`]);
  expect(
    vi.mocked(api).mock.calls.some(([, options]) => options?.method === "PUT"),
  ).toBe(false);
});
it("unknown original paid start cannot be converted into a read or another start", async () => {
  vi.mocked(api).mockResolvedValue({ ...owner(), provider_run_id: null });
  await expect(recoverDiscoveryRead(true)).rejects.toThrow(
    /no acknowledged run/,
  );
  expect(readDiscoveryReadAttempt()).toBeNull();
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("missing browser read pointer adopts server last read UUID and inspection is saved GET only", async () => {
  vi.mocked(api).mockImplementation(async (target) =>
    target === base
      ? {
          ...owner(),
          usage: { last_read_request_id: read, read_rounds_admitted: 1 },
        }
      : saved(),
  );
  const result = await inspectDiscoveryRead();
  expect(result.attempt).toEqual({ requestId: parent, readId: read });
  expect(crypto.randomUUID).not.toHaveBeenCalled();
  expect(vi.mocked(api).mock.calls).toHaveLength(2);
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("expired review prepares a new UUID but does not dispatch or reset server lifetime allowance", async () => {
  pointer();
  const fresh = "30000000-0000-0000-0000-000000000003";
  vi.mocked(crypto.randomUUID).mockReturnValue(fresh);
  vi.mocked(api).mockImplementation(async (target) =>
    target === base
      ? {
          ...owner(),
          usage: {
            read_rounds_admitted: 1,
            last_read_request_id: read,
            read_next_allowed_at: "2026-11-17T00:05:00Z",
          },
        }
      : saved(),
  );
  expect(await prepareNextDiscoveryRead(read)).toEqual({
    requestId: parent,
    readId: fresh,
  });
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
  vi.mocked(api).mockImplementation(async (target) =>
    target === base
      ? owner()
      : Promise.reject(new ApiError(404, "No read admission")),
  );
  await expect(recoverDiscoveryRead(false)).rejects.toThrow(/authorize/);
  expect(readDiscoveryReadAttempt()?.readId).toBe(fresh);
});
it("corrupt response identity/accounting/counts cannot release its saved pointer", async () => {
  pointer();
  for (const corrupt of [
    { ...saved(), request_id: read },
    { ...saved(), source: "instahyre" },
    { ...saved(), billing_final: true },
    { ...saved(), http_attempts: 5 },
    { ...saved(), http_attempts: 0, http_responses: 1 },
  ]) {
    vi.mocked(api).mockImplementation(async (target) =>
      target === base ? owner() : corrupt,
    );
    await expect(inspectDiscoveryRead()).rejects.toThrow();
    expect(readDiscoveryReadAttempt()?.readId).toBe(read);
  }
});
it("restores a missing original pointer from a linked saved read using owner GET only", async () => {
  pointer();
  localStorage.removeItem("job-discovery-attempt:v1");
  vi.mocked(api).mockImplementation(async (target) =>
    target === base ? owner() : saved(),
  );
  const result = await inspectDiscoveryRead();
  expect(result.run.id).toBe(parent);
  expect(JSON.parse(localStorage.getItem("job-discovery-attempt:v1")!)).toEqual(
    { requestId: parent, source: "naukri" },
  );
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("serialized callers cannot turn a second call into a second read admission", async () => {
  let admitted = false;
  vi.mocked(api).mockImplementation(async (target, options) => {
    if (target === base) return owner();
    if (options?.method === "PUT") {
      expect(admitted).toBe(false);
      admitted = true;
      return saved();
    }
    return saved();
  });
  await Promise.all([recoverDiscoveryRead(true), recoverDiscoveryRead(true)]);
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(([, options]) => options?.method === "PUT"),
  ).toHaveLength(1);
});
