import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { StartupDiscovery } from "@/features/startup-discovery";
import { api, post } from "@/lib/api";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const id = "10000000-0000-0000-0000-000000000001",
  child = "20000000-0000-0000-0000-000000000002";
const sources = [
  {
    provider: "hacker_news",
    modes: ["job_led"],
    availability: "available",
    configured: true,
    authorized: true,
    pricing: "free",
    native_execution_implemented: true,
  },
  {
    provider: "himalayas",
    modes: ["job_led"],
    availability: "available",
    configured: true,
    authorized: true,
    pricing: "free",
    native_execution_implemented: false,
  },
  {
    provider: "wellfound",
    modes: ["job_led"],
    availability: "available",
    configured: true,
    authorized: true,
    pricing: "paid",
    native_execution_implemented: true,
    native_execution: {
      ready: true,
      run_cap_usd: "0.100001",
      monthly_limit_usd: "2.000001",
    },
  },
];
const pending = {
  id,
  source: "startup_hacker_news",
  status: "recovery_required",
  counts: { companies_observed: 0 },
  errors: [],
  finished_at: null,
  rankings: [],
  local_intake_complete: false,
  application_dispatch: false,
  live_verified: false,
  usage: { finding_retained: false },
  child_run: {
    id: child,
    status: "recovery_required",
    local_intake_complete: false,
    rankings_complete: false,
  },
};
const completed = {
  ...pending,
  status: "success",
  finished_at: "2026-11-17T00:01:00Z",
  local_intake_complete: true,
  counts: { companies_observed: 1, companies_matching: 1 },
  child_run: {
    ...pending.child_run,
    status: "success",
    local_intake_complete: true,
    rankings_complete: true,
  },
};
const preview = {
  source: sources[0],
  query: { keywords: [], locations: [] },
  provider_calls: 0,
  writes: 0,
  job_led_available: true,
  message: "Fictional preview only",
};
let reply: (path: string, options?: RequestInit) => Promise<unknown>;
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <StartupDiscovery onReviewChild={vi.fn()} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.spyOn(crypto, "randomUUID").mockReturnValue(id);
  let tail = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_key: string, work: () => Promise<unknown>) => {
        const next = tail.then(work);
        tail = next.then(
          () => undefined,
          () => undefined,
        );
        return next;
      },
    },
  });
  reply = async () => completed;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "startups/sources" ? { sources } : reply(path, options),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "locks");
});
it("offers implemented sources only and requires reviewed preview before original startup PUT", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValueOnce(preview);
  mount();
  expect(
    await screen.findByRole("option", { name: /himalayas/i }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "Preview startup discovery" }),
  );
  expect(
    await screen.findByRole("button", {
      name: "Run approved startup discovery",
    }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", { name: "Run this bounded startup search" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Run approved startup discovery" }),
  );
  await screen.findByText(/^run result: success$/i);
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(([, options]) => options?.method === "PUT"),
  ).toHaveLength(1);
  expect(
    JSON.parse(localStorage.getItem("startup-discovery-attempt:v1")!),
  ).toEqual({ requestId: id, source: "hacker_news" });
});
it("reloads an uncertain startup through GET only and locks criteria and new searches", async () => {
  localStorage.setItem(
    "startup-discovery-attempt:v1",
    JSON.stringify({ requestId: id, source: "hacker_news" }),
  );
  reply = async () => pending;
  mount();
  await screen.findByText(/^run result: recovery required$/i);
  expect(
    screen.getByRole("textbox", { name: "Startup role keywords" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", {
      name: "Review result and prepare new startup search",
    }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("requires paid startup opt-in and ready cost preview without calling job application routes", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValueOnce({
    ...preview,
    source: sources[2],
    paid_execution: {
      ready: false,
      run_cap_usd: "0.100001",
      monthly_limit_usd: "2.000001",
      estimated_usd: null,
      blocker: "apify_reviewed_execution_route_required",
    },
  });
  mount();
  await user.selectOptions(
    await screen.findByRole("combobox", { name: "Startup source" }),
    "wellfound",
  );
  expect(
    screen.getByRole("button", { name: "Preview startup discovery" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", { name: "Allow paid startup discovery" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Preview startup discovery" }),
  );
  await user.click(
    await screen.findByRole("checkbox", {
      name: "Run this bounded startup search",
    }),
  );
  expect(
    screen.getByRole("button", { name: "Run approved startup discovery" }),
  ).toBeDisabled();
  expect(vi.mocked(post).mock.calls[0][1]).toMatchObject({
    allow_paid: true,
    source: "wellfound",
  });
  expect(
    vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});
it("recovers retained startup observations with empty local complete and clears pointer only after terminal review", async () => {
  localStorage.setItem(
    "startup-discovery-attempt:v1",
    JSON.stringify({ requestId: id, source: "hacker_news" }),
  );
  let finished = false;
  reply = async (_path, options) => {
    if (options?.method === "POST") {
      expect(options.body).toBe("{}");
      finished = true;
      return completed;
    }
    return finished
      ? completed
      : { ...pending, usage: { finding_retained: true } };
  };
  const user = userEvent.setup();
  mount();
  await user.click(
    await screen.findByRole("button", {
      name: "Complete saved startup search",
    }),
  );
  await screen.findByText(/^run result: success$/i);
  expect(localStorage.getItem("startup-discovery-attempt:v1")).not.toBeNull();
  await user.click(
    screen.getByRole("button", {
      name: "Review result and prepare new startup search",
    }),
  );
  await waitFor(() =>
    expect(localStorage.getItem("startup-discovery-attempt:v1")).toBeNull(),
  );
  expect(
    vi.mocked(api).mock.calls.some(([, options]) => options?.method === "PUT"),
  ).toBe(false);
});
