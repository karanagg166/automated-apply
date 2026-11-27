import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Automation } from "@/features/automation";
import { api, post, ApiError } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const state = {
  state: "disabled",
  version: 1,
  configuration: {
    enabled: false,
    sources: [],
    interval_seconds: 21600,
    limit: 20,
    approved_profile_id: null,
    approved_profile_version: null,
  },
  blockers: ["operational_activation_required"],
  next_run_at: null,
  last_run_at: null,
  worker_ready: false,
  profile: null,
  matching: "awaiting_profile_approval",
};
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
      <Automation />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "dashboard/automation") return structuredClone(state);
    if (path.startsWith("dashboard/automation/history"))
      return { executions: [] };
    if (path === "dashboard/automation/matches") return { matches: [] };
    if (path === "dashboard/notification-preferences")
      return { in_app: true, paused: false };
    throw new Error(path);
  });
});
it("keeps activation blocked and previews without executing", async () => {
  mount();
  await screen.findByRole("heading", { name: "Discovery automation" });
  expect(
    screen.getByRole("button", { name: "Enable automation" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
  expect(screen.getByText(/No executions recorded/)).toBeVisible();
  vi.mocked(post).mockResolvedValue({
    provider_calls: 0,
    matching: "awaiting_profile_approval",
    blockers: ["operational_activation_required"],
    sources: [],
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Preview saved automation plan" }),
  );
  await screen.findByRole("heading", { name: "Saved automation plan" });
  expect(post).toHaveBeenCalledWith("dashboard/automation/preview");
  expect(post).not.toHaveBeenCalledWith(
    "dashboard/automation/run",
    expect.anything(),
  );
});
it("saves source configuration and exposes failure filters", async () => {
  mount();
  await screen.findByRole("heading", { name: "Discovery automation" });
  await userEvent.click(screen.getByRole("checkbox", { name: "arbeitnow" }));
  expect(
    screen.getByRole("button", { name: "Preview saved automation plan" }),
  ).toBeDisabled();
  await userEvent.click(
    screen.getByRole("button", { name: "Save automation configuration" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "dashboard/automation",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const call = vi
    .mocked(api)
    .mock.calls.find(([, options]) => options?.method === "PUT")!;
  expect(JSON.parse(String(call[1]?.body)).configuration.sources).toEqual([
    "arbeitnow",
  ]);
  await userEvent.selectOptions(
    screen.getByLabelText("Execution status filter"),
    "failed",
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "dashboard/automation/history?state=failed",
    ),
  );
});
it("reports a missing database honestly", async () => {
  vi.mocked(api).mockRejectedValue(new ApiError(503, "Database unavailable"));
  mount();
  expect(
    await screen.findByText(/Blocked by missing production database/),
  ).toBeVisible();
});
it("pauses existing notification preferences", async () => {
  mount();
  await screen.findByRole("heading", { name: "Discovery automation" });
  await userEvent.click(
    screen.getByRole("button", { name: "Pause notifications" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "dashboard/notification-preferences",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ in_app: true, paused: true }),
      }),
    ),
  );
});
it("allows only explicit automation methods through the owner BFF", () => {
  expect(permittedRoute("dashboard/automation", "PUT")).toBe(true);
  // Milestone 2: the dead v1 run queue is gone; Run Now asks the v2 worker for one cycle.
  expect(permittedRoute("dashboard/automation/run", "POST")).toBe(false);
  expect(permittedRoute("v2/worker/run-once", "POST")).toBe(true);
  expect(permittedRoute("dashboard/automation/run", "GET")).toBe(false);
  expect(permittedRoute("dashboard/automation/history", "DELETE")).toBe(false);
  expect(permittedRoute("dashboard/automation/activate-provider", "POST")).toBe(
    false,
  );
});

it("Run Now requests one v2 worker cycle", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "dashboard/automation"
      ? {
          ...structuredClone(state),
          state: "ready",
          blockers: [],
          configuration: {
            ...state.configuration,
            enabled: true,
            sources: ["arbeitnow"],
          },
        }
      : original(path, options),
  );
  vi.mocked(post).mockResolvedValue({ desired_state: "RUNNING" });
  mount();
  await screen.findByRole("heading", { name: "Discovery automation" });
  await userEvent.click(screen.getByRole("button", { name: "Run Now" }));
  await screen.findByText(/Run-once requested from the v2 worker/);
  const calls = vi.mocked(post).mock.calls;
  expect(calls[0][0]).toBe("v2/worker/run-once");
});
