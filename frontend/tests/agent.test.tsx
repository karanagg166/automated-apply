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
function mount(nativeRuntime = false) {
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
      <Agent nativeRuntime={nativeRuntime} />
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

it("opens the native workflow and displays retained campaigns without legacy write controls", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "agent/status")
      return { native_worker_online: true, native_worker_mode: "STOPPED" };
    if (path === "agent/campaigns")
      return [
        {
          id: "fixture",
          message: "Fictional saved campaign",
          state: "awaiting_approval",
          plan: {},
          reply: "Saved review.",
        },
      ];
    return [];
  });
  mount(true);
  expect(
    await screen.findByRole("link", { name: "Open agent workflow" }),
  ).toHaveAttribute("href", "/workflow");
  expect(
    await screen.findByText("Workflow worker online · stopped"),
  ).toBeVisible();
  expect(
    await screen.findByRole("heading", { name: "Fictional saved campaign" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", {
      name: /approve|cancel campaign|send command/i,
    }),
  ).toBeNull();
  expect(post).not.toHaveBeenCalled();
});

it("runs a native command with stable retry identity and links the draft for review", async () => {
  const packet = "20000000-0000-4000-8000-000000000005";
  vi.mocked(post)
    .mockRejectedValueOnce(new ApiError(504, "Response lost"))
    .mockResolvedValueOnce({
      data: { reply: "Application prepared for review.", packet_id: packet },
    })
    .mockResolvedValueOnce({ data: { reply: "Selection cleared." } });
  mount(true);
  const owner = userEvent.setup();
  const text = screen.getByLabelText("Command");
  const run = screen.getByRole("button", { name: "Run local command" });
  await owner.type(text, "Prepare selected job");
  await owner.click(run);
  await screen.findByText("Response lost");
  await owner.click(run);
  const review = await screen.findByRole("link", {
    name: "Review application draft",
  });
  expect(review).toHaveAttribute("href", `/applications/${packet}`);
  expect(screen.getByText("Application prepared for review.")).toBeVisible();
  const attempts = vi.mocked(post).mock.calls;
  expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[0][0]).toBe("agent/commands");
  await owner.type(text, "/reset");
  await owner.click(run);
  expect(await screen.findByText("Selection cleared.")).toBeVisible();
  expect(attempts[2][1]).not.toEqual(attempts[0][1]);
  expect(
    screen.queryByRole("link", { name: "Review application draft" }),
  ).toBeNull();
});
