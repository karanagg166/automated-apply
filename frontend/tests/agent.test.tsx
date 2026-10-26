import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Agent } from "@/features/agent";
import { api, post, ApiError } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
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
      <Agent />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) =>
    path === "agent/campaigns"
      ? []
      : {
          worker_ready: false,
          state: "not_configured",
          local_requests_remaining: 29,
        },
  );
});
it("queues a command and reuses its identity after a lost response", async () => {
  mount();
  expect(await screen.findByText(/29 local requests remaining/)).toBeVisible();
  expect(
    screen.getByText(/Provider account quota is unverified/),
  ).toBeVisible();
  vi.mocked(post)
    .mockRejectedValueOnce(new ApiError(504, "Response lost"))
    .mockResolvedValueOnce({ id: "fixture" });
  await userEvent.type(
    screen.getByLabelText("Command"),
    "Find backend jobs in India",
  );
  await userEvent.click(screen.getByRole("button", { name: "Send command" }));
  await screen.findByText("Response lost");
  await userEvent.click(screen.getByRole("button", { name: "Send command" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(vi.mocked(post).mock.calls[0]).toEqual(vi.mocked(post).mock.calls[1]);
});
it("shows truthful pending state and exact draft-scope controls", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "agent/campaigns"
      ? [
          {
            id: "fixture",
            message: "Apply to first one",
            state: "awaiting_approval",
            revision: 1,
            approval_nonce: "nonce",
            plan: { selected_jobs: ["job"], filters: {}, actions: [] },
            reply: "Draft scope clarification required.",
            applications: {},
            results: [],
            history: [],
          },
        ]
      : {
          worker_ready: false,
          state: "not_configured",
          local_requests_remaining: 29,
        },
  );
  vi.mocked(post).mockResolvedValue({});
  mount();
  await userEvent.click(
    await screen.findByRole("button", { name: "Approve 1 local drafts only" }),
  );
  expect(post).toHaveBeenCalledWith(
    "agent/campaigns/fixture/approve",
    expect.objectContaining({
      scope: "prepare",
      nonce: "nonce",
      maximum_applications: 1,
    }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Cancel campaign" }),
  );
  expect(post).toHaveBeenCalledWith("agent/campaigns/fixture/cancel");
});
it("limits the gateway to fixed command operations", () => {
  expect(permittedRoute("agent/commands", "POST")).toBe(true);
  expect(permittedRoute("agent/status", "GET")).toBe(true);
  expect(permittedRoute("agent/execute", "POST")).toBe(false);
  expect(permittedRoute("agent/submit_application", "POST")).toBe(false);
});

it("distinguishes the available command worker from the unavailable Chrome worker", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "agent/status"
      ? {
          worker_ready: true,
          browser_worker_ready: false,
          state: "not_configured",
          local_requests_remaining: 29,
        }
      : [],
  );
  mount();
  expect(await screen.findByText("Command worker available")).toBeVisible();
  expect(screen.getByText("Chrome worker unavailable")).toBeVisible();
});
