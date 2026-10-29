import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
import { BrowserAssistant } from "@/features/browser-assistant";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const packet = {
  id: "11111111-1111-4111-8111-111111111111",
  job_id: "21111111-1111-4111-8111-111111111111",
  revision: 4,
  lifecycle_state: "created",
  snapshot: {
    destination: { application_url: "https://jobs.lever.co/fictional/1/apply" },
  },
} as Schema<"PacketRead">;
const a = "a1111111-1111-4111-8111-111111111111",
  b = "b1111111-1111-4111-8111-111111111111";
const base = {
  selection: { version: 3, profile_binding_id: a },
  channel_available: true,
  commands: [],
  profiles: [
    {
      id: a,
      label: "Personal Chrome",
      version: 2,
      connected: true,
      selected: true,
      status: "CONNECTED",
      last_heartbeat: "2026-10-29T10:00:00Z",
      commands_enabled: true,
    },
    {
      id: b,
      label: "Job applications",
      version: 1,
      connected: true,
      selected: false,
      status: "CONNECTED",
      last_heartbeat: "2026-10-29T09:59:00Z",
      commands_enabled: false,
    },
  ],
};
let state: typeof base;
function mount(unsaved = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BrowserAssistant packet={packet} hasUnsavedAnswers={unsaved} />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  state = structuredClone(base);
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "browser/chrome-profiles") return state;
    if (String(path).includes("extension-tasks")) return null;
    if (path === "browser-applications/policy")
      return { origins: [], digest: "a".repeat(64) };
    return null;
  });
  vi.mocked(post).mockResolvedValue({});
});
it("defaults to selected normal Chrome and queues an exact packet without opening isolated browser", async () => {
  mount();
  await screen.findByText("Personal Chrome");
  expect(screen.getByLabelText("Application browser")).toHaveValue("extension");
  expect(
    screen.queryByRole("button", { name: "Open dedicated browser" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Open in selected Chrome profile" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "browser/chrome-profiles/commands",
      expect.objectContaining({
        action: "open",
        profile_binding_id: a,
        packet_revision: 4,
        selection_version: 3,
        expected_profile_version: 2,
      }),
    ),
  );
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) =>
        String(path).startsWith("browser-applications"),
      ),
  ).toBe(false);
});
it("shows both bindings and requires an explicit versioned switch", async () => {
  mount();
  await screen.findByText("Job applications");
  expect(screen.getByText(`Binding: ${b}`)).toBeVisible();
  expect(screen.getByText("2026-10-29T09:59:00Z")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Use Job applications" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("browser/chrome-profiles/select", {
      profile_binding_id: b,
      expected_version: 3,
    }),
  );
  expect(vi.mocked(post).mock.calls).toHaveLength(1);
});
it("offline selected profile blocks commands and never chooses the other connected profile", async () => {
  state.profiles[0].status = "PROFILE_OFFLINE";
  mount();
  await screen.findByText("PROFILE_OFFLINE");
  expect(
    screen.getByRole("button", { name: "Open in selected Chrome profile" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Use Job applications" }),
  ).toBeEnabled();
  expect(post).not.toHaveBeenCalled();
});
it("protects unsaved answers and disabled commands", async () => {
  mount(true);
  await screen.findByText("Personal Chrome");
  expect(
    screen.getByRole("button", { name: "Open in selected Chrome profile" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Inspect and prepare answers" }),
  ).toBeDisabled();
});
it("disconnects the exact binding with its version and does not launch a replacement", async () => {
  mount();
  await screen.findByText("Personal Chrome");
  await userEvent.click(
    screen.getByRole("button", { name: "Disconnect Personal Chrome" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `browser/chrome-profiles/${a}/disconnect`,
      { expected_version: 2 },
    ),
  );
});
