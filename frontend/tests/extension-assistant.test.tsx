import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ExtensionAssistant,
  type ExtensionTask,
} from "@/features/extension-assistant";
import { api, post, type Schema } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const packet = {
  id: "11111111-1111-4111-8111-111111111111",
  job_id: "22222222-2222-4222-8222-222222222222",
  revision: 3,
  lifecycle_state: "ready_for_review",
} as Schema<"PacketRead">;

const savedTask: ExtensionTask = {
  id: "33333333-3333-4333-8333-333333333333",
  version: 7,
  application_id: packet.id,
  job_id: packet.job_id,
  company_name: "Fictional Employer",
  job_title: "Platform Engineer",
  packet_revision: 3,
  profile_version: 5,
  target_url: "https://fictional.example/apply/platform",
  current_url: "https://fictional.example/apply/platform/experience",
  tab_id: 12,
  tab_active: false,
  browser_connection: "connected",
  state: "FORM_INSPECTED",
  challenge_state: "NONE",
  step: "Employment history",
  plan_id: "44444444-4444-4444-8444-444444444444",
  authorization_id: null,
  field_answer_revisions: { f1: 2 },
  reason: null,
  next_action: "Review this step's proposed answers in Chrome.",
  mode: "ASSISTED_FILL",
  capabilities: {
    preview: true,
    assisted_fill: true,
    reviewed_submission: false,
    unattended_approved: false,
  },
  counts: {
    ready: 2,
    completed: 1,
    missing: 3,
    manual: 4,
    validation_errors: 0,
  },
  updated_at: "2026-10-29T09:00:00Z",
};

function mount(props: Partial<Parameters<typeof ExtensionAssistant>[0]> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ExtensionAssistant packet={packet} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(savedTask);
  vi.mocked(post).mockResolvedValue({
    ...savedTask,
    version: 8,
    state: "PAUSED",
  });
});

it("shows the exact packet, profile, current page, step and active tab status", async () => {
  mount();
  expect(
    await screen.findByText("Fictional Employer · Platform Engineer"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Packet revision 3 · Profile version 5"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Current step: Employment history"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Application tab: 12 · Another tab is active/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: savedTask.target_url }),
  ).toHaveAttribute("rel", "noopener noreferrer");
  expect(
    screen.getByRole("link", { name: savedTask.current_url }),
  ).toHaveAttribute("href", savedTask.current_url);
  expect(api).toHaveBeenCalledWith(
    `browser/extension-tasks/application/${packet.id}`,
    { signal: expect.any(AbortSignal) },
  );
});

it("keeps preview, retained field values and submission distinct", async () => {
  mount();
  const status = await screen.findByLabelText("Inspected field status");
  expect(
    within(status).getByText("Website retained value").nextElementSibling,
  ).toHaveTextContent("1");
  expect(
    within(status).getByText("Ready to fill").nextElementSibling,
  ).toHaveTextContent("2");
  expect(
    screen.getByText(
      /A verified fill receipt records retained field values; it does not confirm an application submission/,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Reviewed submission: disabled")).toBeInTheDocument();
  expect(screen.getByText("Unattended approved: disabled")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /submit|fill/i }),
  ).not.toBeInTheDocument();
});

it.each([
  [
    "WIDGET_PRESENT_UNVERIFIED",
    /Security widget present; completion is unverified/,
  ],
  ["CHALLENGE_BLOCKING", /Security challenge blocks filling/],
  [
    "MANUALLY_RESOLVED_AND_SITE_VERIFIED",
    /Manual completion verified using supported site signals/,
  ],
  ["UNKNOWN", /Security state could not be verified/],
] as const)(
  "explains %s without treating widget appearance as success",
  async (challenge_state, message) => {
    vi.mocked(api).mockResolvedValue({ ...savedTask, challenge_state });
    mount();
    expect(await screen.findByText(message)).toBeInTheDocument();
  },
);

it("pauses only the exact execution with optimistic version checking", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
  expect(post).toHaveBeenCalledExactlyOnceWith(
    `browser/extension-tasks/${savedTask.id}/control`,
    { action: "pause", expected_version: 7 },
  );
  expect(post).not.toHaveBeenCalledWith(
    expect.stringMatching(/authorize|submit|fill/),
    expect.anything(),
  );
});

it("blocks resume after a packet revision change while allowing cancellation", async () => {
  vi.mocked(api).mockResolvedValue({
    ...savedTask,
    state: "PAUSED",
    packet_revision: 2,
  });
  mount();
  expect(
    await screen.findByText(/The current revision is 3/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(post).toHaveBeenCalledExactlyOnceWith(
    `browser/extension-tasks/${savedTask.id}/control`,
    { action: "cancel", expected_version: 7 },
  );
});

it("requires unsaved field edits to be saved before resuming", async () => {
  vi.mocked(api).mockResolvedValue({ ...savedTask, state: "PAUSED" });
  mount({ hasUnsavedAnswers: true });
  expect(
    await screen.findByText(/Save your edited answers before resuming/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
});

it("does not show or control a task for a different job", async () => {
  vi.mocked(api).mockResolvedValue({
    ...savedTask,
    job_id: "55555555-5555-4555-8555-555555555555",
  });
  mount();
  expect(
    await screen.findByText(/does not match this job and packet/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Fictional Employer · Platform Engineer"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Pause" }),
  ).not.toBeInTheDocument();
});

it("keeps unknown submission state terminal and supplies no retry or submission control", async () => {
  vi.mocked(api).mockResolvedValue({
    ...savedTask,
    state: "SUBMISSION_UNKNOWN",
  });
  mount();
  expect(await screen.findByText("SUBMISSION UNKNOWN")).toBeInTheDocument();
  for (const name of ["Pause", "Resume", "Cancel"])
    expect(screen.getByRole("button", { name })).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});

it("reports an unavailable connection without inventing an empty task or retrying an action", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Local backend offline"));
  mount();
  expect(await screen.findByText("Local backend offline")).toBeInTheDocument();
  expect(screen.getByText("Connection unverified")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Resume" }),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it("shows an unassociated task without claiming that the browser is connected", async () => {
  vi.mocked(api).mockResolvedValue(null);
  mount();
  expect(
    await screen.findByText(
      /No browser connection has been verified for this packet/,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("No tab associated")).toBeInTheDocument();
});

it("renders employer content as text and refuses non-HTTPS destination links", async () => {
  vi.mocked(api).mockResolvedValue({
    ...savedTask,
    company_name: '<img src=x onerror="alert(1)">',
    target_url: "javascript:alert(1)",
    current_url: "javascript:alert(1)",
  });
  mount();
  expect(
    await screen.findByText(
      '<img src=x onerror="alert(1)"> · Platform Engineer',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /javascript/ }),
  ).not.toBeInTheDocument();
});

it("refreshes a version conflict without silently retrying the owner control", async () => {
  vi.mocked(post).mockRejectedValue(new Error("extension_task_stale"));
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
  expect(await screen.findByText("extension_task_stale")).toBeInTheDocument();
  expect(post).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
});

it("explains that the observed network guard remains until manual browser takeover", async () => {
  vi.mocked(api).mockResolvedValue({
    ...savedTask,
    network_guard_active: true,
  });
  mount();
  expect(
    await screen.findByText(
      /New requests associated with this application tab are blocked/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      /Pre-existing streams and independent background activity are outside its verified scope/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Return browser control in the extension/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /release|network|takeover/i }),
  ).not.toBeInTheDocument();
});
