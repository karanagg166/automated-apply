import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { PortalRulesEditor } from "@/features/autopilot-rules";
import { ScreeningProfileEditor } from "@/features/autopilot-screening";
import { WorkerStatusPanel } from "@/features/autopilot-status";
import { ApplicationsLog } from "@/features/autopilot-log";
import { api, patch, post, ApiError } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

const naukri = {
  platform: "naukri",
  enabled: true,
  auto_apply_enabled: false,
  max_applies_per_day: 50,
  max_applies_per_hour: 10,
  max_job_age_days: 7,
  max_applicants: 300,
  unknown_applicants_policy: "allow_lower_bound" as const,
  min_delay_sec: 45,
  max_delay_sec: 150,
  active_hours_start: "08:00",
  active_hours_end: "23:30",
  timezone: "Asia/Kolkata",
  auth_status: "OK" as const,
  revision: 3,
};

const worker = {
  desired_state: "STOPPED" as const,
  dry_run: true,
  observed_state: "STOPPED",
  heartbeat_at: "2026-11-26T10:00:00Z",
  heartbeat_age_sec: 900,
  stale: true,
  current_platform: null,
  last_cycle_at: null,
  last_error: "Brave profile lock held",
  revision: 2,
};

const status = {
  generated_at: "2026-11-26T10:15:00Z",
  gmail_permission: "read_draft_only" as const,
  gmail_permission_label: "Read + Draft Only",
  waiting_for_user: 2,
  worker,
  portals: [
    {
      platform: "instahyre",
      enabled: true,
      auto_apply_enabled: true,
      auth_status: "AUTH_REQUIRED",
      portal_limit_hit_today: false,
      applied_today: 9,
      max_applies_per_day: 10,
      applied_this_hour: 1,
      max_applies_per_hour: 5,
      daily_limit_hit: false,
      hourly_limit_hit: false,
      within_active_hours: true,
      waiting_for_user: 2,
    },
  ],
};

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

let rulesRow = { ...naukri };
beforeEach(() => {
  vi.clearAllMocks();
  rulesRow = { ...naukri };
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/portal-rules") return [structuredClone(rulesRow)];
    if (path === "v2/status") return structuredClone(status);
    if (path.startsWith("v2/applications?"))
      return {
        items: [
          {
            id: "11111111-1111-4111-8111-111111111111",
            platform: "naukri",
            external_job_id: "NK-1",
            company_name: "Example Labs",
            role_title: "Backend Engineer",
            job_url: "https://example.com/jobs/1",
            state: "FILTERED_OUT",
            reason: "Posted 12 days ago (max 7)",
            attempts: 0,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      };
    if (path.endsWith("/events"))
      return [
        {
          from_state: "DISCOVERED",
          to_state: "FILTERED_OUT",
          event_type: "filter",
          payload: { rule: "max_job_age_days" },
          created_at: "2026-11-26T09:00:00Z",
        },
      ];
    throw new Error(path);
  });
});

it("saves only the changed portal rule fields with the current revision", async () => {
  const user = userEvent.setup();
  vi.mocked(patch).mockImplementation(async (_path, body) => {
    rulesRow = { ...rulesRow, max_applies_per_day: 40, revision: 4 };
    return { ...rulesRow, ...(body as object), revision: 4 };
  });
  mount(<PortalRulesEditor />);
  const daily = await screen.findByLabelText("Max applications per day");
  const save = screen.getByRole("button", { name: "Save naukri rules" });
  expect(save).toBeDisabled();
  await user.clear(daily);
  await user.type(daily, "40");
  await user.click(save);
  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith("v2/portal-rules/naukri", {
      revision: 3,
      max_applies_per_day: 40,
    }),
  );
  expect(
    await screen.findByText(/Saved naukri rules .*revision 4.*no restart/),
  ).toHaveAttribute("role", "status");
  expect(screen.getByLabelText("Max applications per day")).toHaveValue(40);
});

it("blocks invalid rules client-side and explains stale revisions", async () => {
  const user = userEvent.setup();
  vi.mocked(patch).mockRejectedValue(new ApiError(409, "stale revision"));
  mount(<PortalRulesEditor />);
  const hourly = await screen.findByLabelText("Max applications per hour");
  await user.clear(hourly);
  await user.type(hourly, "60");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Hourly cap cannot exceed the daily cap.",
  );
  expect(
    screen.getByRole("button", { name: "Save naukri rules" }),
  ).toBeDisabled();
  await user.clear(hourly);
  await user.type(hourly, "8");
  await user.click(screen.getByRole("button", { name: "Save naukri rules" }));
  expect(await screen.findByText(/changed elsewhere/)).toBeInTheDocument();
  await waitFor(() =>
    expect(
      vi.mocked(api).mock.calls.filter(([p]) => p === "v2/portal-rules"),
    ).toHaveLength(2),
  );
});

it("shows 422 validation detail from the backend", async () => {
  const user = userEvent.setup();
  vi.mocked(patch).mockRejectedValue(
    new ApiError(422, "timezone: Unknown IANA timezone"),
  );
  mount(<PortalRulesEditor />);
  const tz = await screen.findByLabelText("Timezone");
  await user.clear(tz);
  await user.type(tz, "Mars/Base");
  await user.click(screen.getByRole("button", { name: "Save naukri rules" }));
  expect(
    await screen.findByText("Not saved: timezone: Unknown IANA timezone"),
  ).toBeInTheDocument();
});

it("requires a deliberate confirmation before starting live applications", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValue({
    ...worker,
    desired_state: "RUNNING",
    dry_run: false,
  });
  mount(<WorkerStatusPanel />);
  expect(
    await screen.findByText(/Worker process not running/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Brave profile lock held/)).toBeInTheDocument();
  const portal = screen.getByLabelText("instahyre status");
  expect(within(portal).getByText("Login required")).toBeInTheDocument();
  expect(within(portal).getByText(/login-setup/)).toBeInTheDocument();
  expect(
    within(portal).getByRole("progressbar", { name: "Applied today: 9 of 10" }),
  ).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Start live…" }));
  const dialog = await screen.findByRole("dialog");
  const confirm = within(dialog).getByRole("button", {
    name: "Start live applications",
  });
  expect(confirm).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
  await user.click(within(dialog).getByRole("checkbox"));
  await user.click(confirm);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/worker/start", { dry_run: false }),
  );

  await user.click(screen.getByRole("button", { name: "Start dry run" }));
  await waitFor(() =>
    expect(post).toHaveBeenLastCalledWith("v2/worker/start", {
      dry_run: true,
    }),
  );
  await user.click(screen.getByRole("button", { name: "Run one cycle" }));
  await waitFor(() =>
    expect(post).toHaveBeenLastCalledWith("v2/worker/run-once"),
  );
});

it("links to the profile page when no candidate profile exists", async () => {
  vi.mocked(api).mockResolvedValue({ version: 0, has_profile: false });
  mount(<ScreeningProfileEditor />);
  expect(
    await screen.findByRole("link", { name: "Create your profile" }),
  ).toHaveAttribute("href", "/profile");
  expect(screen.queryByLabelText("Current CTC (LPA)")).toBeNull();
});

it("patches only changed screening facts with the current version", async () => {
  const user = userEvent.setup();
  vi.mocked(api).mockResolvedValue({
    target_roles: ["Backend Engineer"],
    tech_stack: [],
    skill_years: {},
    willing_to_relocate: null,
    version: 5,
    has_profile: true,
  });
  vi.mocked(patch).mockResolvedValue({ version: 6, has_profile: true });
  mount(<ScreeningProfileEditor />);
  await user.type(await screen.findByLabelText("Expected CTC (LPA)"), "14");
  await user.selectOptions(screen.getByLabelText("Willing to relocate"), "yes");
  await user.type(screen.getByLabelText("Tech stack"), "Python, FastAPI");
  await user.click(screen.getByRole("button", { name: "Add skill" }));
  await user.type(screen.getByLabelText("Skill 1 name"), "Python");
  await user.type(screen.getByLabelText("Years of Python"), "2");
  await user.click(
    screen.getByRole("button", { name: "Save screening facts" }),
  );
  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith("v2/screening-profile", {
      version: 5,
      expected_ctc: 14,
      willing_to_relocate: true,
      tech_stack: ["Python", "FastAPI"],
      skill_years: { Python: 2 },
    }),
  );
});

it("shows application reasons and lazily loads state events", async () => {
  const user = userEvent.setup();
  mount(<ApplicationsLog platforms={["naukri"]} />);
  expect(
    await screen.findByText("Posted 12 days ago (max 7)"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("FILTERED OUT", { selector: ".badge" }),
  ).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([p]) => p.endsWith("/events"))).toBe(
    false,
  );
  await user.click(screen.getByRole("button", { name: "Show events" }));
  expect(
    await screen.findByText("DISCOVERED → FILTERED_OUT"),
  ).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("State"), "FAILED");
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("v2/applications?limit=50&state=FAILED"),
  );
});
