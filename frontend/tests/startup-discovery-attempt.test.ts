import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import {
  inspectStartup,
  prepareStartup,
  recoverStartup,
  reviewStartupChild,
  startupAttempt,
  type StartupRun,
} from "@/features/startup-discovery-attempt";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const parent = "10000000-0000-0000-0000-000000000001",
  child = "20000000-0000-0000-0000-000000000002";
const path = `startups/discovery/runs/${parent}`,
  key = "startup-discovery-attempt:v1";
const input = {
  source: "arbeitnow",
  mode: "job_led",
  query: { keywords: ["PRIVATE_QUERY_CANARY"] },
};
const pointer = () =>
  localStorage.setItem(
    key,
    JSON.stringify({ requestId: parent, source: "arbeitnow" }),
  );
const pending = (): StartupRun => ({
  id: parent,
  source: "startup_arbeitnow",
  status: "running",
  counts: {},
  errors: [],
  rankings: [],
  finished_at: null,
  application_dispatch: false,
  live_verified: false,
  local_intake_complete: false,
  usage: { finding_retained: false },
  child_run: {
    id: child,
    status: "running",
    local_intake_complete: false,
    rankings_complete: false,
  },
});
const complete = (): StartupRun => ({
  ...pending(),
  status: "success",
  finished_at: "2026-11-17T00:02:00Z",
  local_intake_complete: true,
  child_run: {
    ...pending().child_run!,
    status: "success",
    local_intake_complete: true,
    rankings_complete: true,
  },
});
beforeEach(() => {
  localStorage.clear();
  vi.mocked(api).mockReset();
  vi.spyOn(crypto, "randomUUID").mockReturnValue(parent);
  const tails = new Map<string, Promise<unknown>>();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (key: string, work: () => Promise<unknown>) => {
        const next = (tails.get(key) ?? Promise.resolve()).then(work);
        tails.set(
          key,
          next.catch(() => undefined),
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
it("saves only original startup UUID/source before approved PUT and stores no query/profile facts", async () => {
  vi.mocked(api).mockImplementation(async () => {
    expect(startupAttempt()).toEqual({
      requestId: parent,
      source: "arbeitnow",
    });
    expect(localStorage.getItem(key)).not.toContain("CANARY");
    return complete();
  });
  expect(await recoverStartup(input, true)).toEqual(complete());
  expect(api).toHaveBeenCalledExactlyOnceWith(path, {
    method: "PUT",
    body: JSON.stringify(input),
  });
});
it("does not admit without owner consent or when durable pointer storage fails", async () => {
  await expect(recoverStartup(input)).rejects.toThrow();
  expect(api).not.toHaveBeenCalled();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  await expect(recoverStartup(input, true)).rejects.toThrow(
    "Storage unavailable",
  );
  expect(api).not.toHaveBeenCalled();
});
it("response loss retains original pointer and reload inspection is saved GET only", async () => {
  vi.mocked(api).mockRejectedValueOnce(new ApiError(504, "Response lost"));
  await expect(recoverStartup(input, true)).rejects.toThrow();
  vi.mocked(api).mockResolvedValueOnce(complete());
  expect(await inspectStartup()).toEqual(complete());
  expect(api).toHaveBeenLastCalledWith(path);
  expect(startupAttempt()?.requestId).toBe(parent);
});
it("retained findings finish through empty local completion without a second PUT or changed request", async () => {
  pointer();
  vi.mocked(api)
    .mockResolvedValueOnce({ ...pending(), usage: { finding_retained: true } })
    .mockResolvedValueOnce(complete());
  expect(
    await recoverStartup({
      source: "instahyre",
      query: { keywords: ["changed"] },
    }),
  ).toEqual(complete());
  expect(api).toHaveBeenNthCalledWith(1, path);
  expect(api).toHaveBeenNthCalledWith(2, `${path}/complete`, {
    method: "POST",
    body: "{}",
  });
});
it("unknown child remains saved and cannot release pointer or dispatch a new source", async () => {
  pointer();
  vi.mocked(api).mockResolvedValue(pending());
  expect(await recoverStartup({ source: "wellfound" }, true)).toEqual(
    pending(),
  );
  await expect(prepareStartup(parent)).rejects.toThrow();
  expect(startupAttempt()?.source).toBe("arbeitnow");
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("404 needs explicit same-source consent and never generates another UUID", async () => {
  pointer();
  vi.mocked(api).mockRejectedValue(new ApiError(404, "Missing original"));
  await expect(recoverStartup(input)).rejects.toThrow();
  await expect(recoverStartup({ source: "wellfound" }, true)).rejects.toThrow();
  vi.mocked(api)
    .mockRejectedValueOnce(new ApiError(404, "Missing original"))
    .mockResolvedValueOnce(complete());
  expect(await recoverStartup(input, true)).toEqual(complete());
  expect(crypto.randomUUID).not.toHaveBeenCalled();
  expect(api).toHaveBeenLastCalledWith(path, {
    method: "PUT",
    body: JSON.stringify(input),
  });
});
it("only reviewed complete parent removes its local pointer while server history remains untouched", async () => {
  pointer();
  vi.mocked(api).mockResolvedValue(complete());
  await prepareStartup(parent);
  expect(startupAttempt()).toBeNull();
  expect(api).toHaveBeenCalledExactlyOnceWith(path);
});
it("corrupt identities/counts or paid accounting keep original pointer", async () => {
  pointer();
  for (const bad of [
    { ...complete(), id: child },
    { ...complete(), counts: { companies_matching: -1 } },
    { ...complete(), application_dispatch: true },
  ]) {
    vi.mocked(api).mockResolvedValue(bad);
    await expect(prepareStartup(parent)).rejects.toThrow();
    expect(startupAttempt()?.requestId).toBe(parent);
  }
  localStorage.setItem(
    key,
    JSON.stringify({ requestId: parent, source: "wellfound" }),
  );
  vi.mocked(api).mockResolvedValue({
    ...complete(),
    source: "startup_wellfound",
  });
  await expect(inspectStartup()).rejects.toThrow();
  expect(startupAttempt()?.source).toBe("wellfound");
});
it("serializes concurrent original recovery and grants only one PUT", async () => {
  let admitted = false;
  vi.mocked(api).mockImplementation(async (_path, options) => {
    if (options?.method === "PUT") {
      expect(admitted).toBe(false);
      admitted = true;
    }
    return complete();
  });
  await Promise.all([recoverStartup(input, true), recoverStartup(input, true)]);
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(([, options]) => options?.method === "PUT"),
  ).toHaveLength(1);
});
it("original child handoff validates saved owner data and never overwrites another job search", async () => {
  pointer();
  const run = {
    id: child,
    source: "arbeitnow",
    status: "running",
    counts: {},
    errors: [],
    started_at: "2026-11-17T00:00:00Z",
    finished_at: null,
    provider_run_id: null,
    usage: {},
    rankings: [],
    job_ids: [],
    local_intake_complete: false,
    rankings_complete: false,
  };
  vi.mocked(api).mockImplementation(async (target) =>
    target === path ? pending() : run,
  );
  expect(await reviewStartupChild(parent)).toBe(child);
  expect(JSON.parse(localStorage.getItem("job-discovery-attempt:v1")!)).toEqual(
    { requestId: child, source: "arbeitnow" },
  );
  localStorage.setItem(
    "job-discovery-attempt:v1",
    JSON.stringify({ requestId: parent, source: "naukri" }),
  );
  await expect(reviewStartupChild(parent)).rejects.toThrow(
    /other saved job discovery/,
  );
  expect(localStorage.getItem("job-discovery-attempt:v1")).toContain(parent);
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
