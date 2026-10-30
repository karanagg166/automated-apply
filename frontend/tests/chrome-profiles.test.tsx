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
it.each(["focus_lost", "active_tab_changed"])(
  "queues exact bound Prepare after %s without a resume or fill",
  async (reason) => {
    const get = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, options) =>
      String(path).includes("extension-tasks")
        ? {
            id: "c1111111-1111-4111-8111-111111111111",
            version: 7,
            application_id: packet.id,
            profile_binding_id: a,
            packet_revision: 4,
            state: "PAUSED",
            reason,
          }
        : get(path, options),
    );
    mount();
    const prepare = screen.getByRole("button", {
      name: "Inspect and prepare answers",
    });
    await waitFor(() => expect(prepare).toBeEnabled());
    await userEvent.click(prepare);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "browser/chrome-profiles/commands",
        expect.objectContaining({
          action: "prepare",
          profile_binding_id: a,
          application_id: packet.id,
          packet_revision: 4,
          task_id: "c1111111-1111-4111-8111-111111111111",
          expected_task_version: 7,
          selection_version: 3,
          expected_profile_version: 2,
        }),
      ),
    );
    expect(post).toHaveBeenCalledTimes(1);
  },
);
it("keeps owner-paused Prepare disabled", async () => {
  const get = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    String(path).includes("extension-tasks")
      ? {
          id: "c1111111-1111-4111-8111-111111111111",
          version: 7,
          profile_binding_id: a,
          packet_revision: 4,
          state: "PAUSED",
          reason: "owner_pause",
        }
      : get(path, options),
  );
  mount();
  await screen.findByText("Personal Chrome");
  expect(
    screen.getByRole("button", { name: "Inspect and prepare answers" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
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

it("reads the authoritative task version immediately before command admission", async () => {
  const get = vi.mocked(api).getMockImplementation()!;
  let version = 7;
  vi.mocked(api).mockImplementation(async (path, options) =>
    String(path).includes("extension-tasks")
      ? {
          id: "c1111111-1111-4111-8111-111111111111",
          application_id: packet.id,
          version,
          profile_binding_id: a,
          packet_revision: 4,
          state: "PAUSED",
          reason: "focus_lost",
        }
      : get(path, options),
  );
  mount();
  const prepare = screen.getByRole("button", {
    name: "Inspect and prepare answers",
  });
  await waitFor(() => expect(prepare).toBeEnabled());
  version = 8;
  await userEvent.click(prepare);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "browser/chrome-profiles/commands",
      expect.objectContaining({ expected_task_version: 8 }),
    ),
  );
  expect(post).toHaveBeenCalledTimes(1);
});

it("refuses a changed selected profile at admission without posting", async () => {
  mount();
  await screen.findByText("Personal Chrome");
  state = {
    ...state,
    selection: { version: 4, profile_binding_id: b },
    profiles: state.profiles.map((profile) => ({
      ...profile,
      selected: profile.id === b,
    })),
  };
  await userEvent.click(
    screen.getByRole("button", { name: "Open in selected Chrome profile" }),
  );
  await screen.findByText(
    "Chrome context changed. Review the current task before continuing.",
  );
  expect(post).not.toHaveBeenCalled();
});
