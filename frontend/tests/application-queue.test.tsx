import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ApplicationQueue,
  ProfileReconciliation,
  QueuePolicyForm,
  type QueueConfiguration,
} from "@/features/application-queue";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue({});
  vi.mocked(post).mockResolvedValue({});
});
const configuration: QueueConfiguration = {
  state: "STOPPED",
  revision: 7,
  policy: {
    global_limits: {
      daily_cap: 80,
      max_job_age_days: 2,
      applicant_limit: 10000,
      unknown_applicants: "needs_review",
      minimum_match_score: 80,
    },
    platforms: {
      naukri: {
        enabled: false,
        mode: "PREPARE_ONLY",
        owner_submission_authorized: false,
        cap_mode: "global",
        age_mode: "global",
        applicants_mode: "global",
        preferences_mode: "global",
        limits: {
          daily_cap: 80,
          max_job_age_days: 2,
          applicant_limit: 10000,
          unknown_applicants: "needs_review",
          minimum_match_score: 80,
        },
        preferences: {
          roles: [],
          locations: [],
          experience_min: null,
          experience_max: null,
          minimum_salary: null,
          maximum_salary: null,
          salary_currency: "INR",
          salary_period: "year",
          excluded_companies: [],
        },
        discovery_interval_seconds: 300,
        supervised_submission_cap: 1,
      },
    },
    day_timezone: "Asia/Kolkata",
    concurrency: 1,
    max_pending: 200,
    background_only: true,
    notify_submitted: true,
  },
};
const saved = async () => {};

it("requires explicit version-bound summary approval and exposes unsupported fields", async () => {
  let sync = {
    configuration: {
      revision: 0,
      policy: {
        enabled: false,
        auto_profile_sync: false,
        profile_version: null as number | null,
        approved_fields: [] as string[],
        interval_seconds: 3600,
      },
    },
    current_profile_version: 4,
    profile_confirmed: true,
    latest: {
      outcome: "COMPARED",
      observed_at: "2026-10-31T00:00:00Z",
      decisions: [
        { field: "email", state: "UNSUPPORTED", update_supported: false },
      ],
    },
    last_error: null,
  };
  const writes: unknown[] = [];
  vi.mocked(api).mockImplementation(async (_path, options) => {
    if (options?.method === "PUT") {
      const payload = JSON.parse(String(options.body));
      writes.push(payload);
      sync = {
        ...sync,
        configuration: {
          revision: sync.configuration.revision + 1,
          policy: payload.policy,
        },
      };
      return sync.configuration;
    }
    return sync;
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ProfileReconciliation />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Unsupported")).toBeVisible();
  const approval = screen.getByLabelText(/Approve automatic Profile summary/);
  expect(approval).toBeDisabled();
  await userEvent.click(screen.getByLabelText("Compare profile periodically"));
  await waitFor(() => expect(approval).toBeEnabled());
  await userEvent.click(approval);
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toMatchObject({
    expected_revision: 1,
    policy: {
      auto_profile_sync: true,
      approved_fields: ["summary"],
      profile_version: 4,
    },
  });
  client.clear();
});

it("saves a 30-minute profile check without granting portal writes", async () => {
  const view = {
    configuration: {
      revision: 3,
      policy: {
        enabled: true,
        auto_profile_sync: false,
        profile_version: 4,
        approved_fields: [],
        interval_seconds: 3600,
      },
    },
    current_profile_version: 4,
    profile_confirmed: true,
    latest: null,
    last_error: null,
  };
  const writes: unknown[] = [];
  vi.mocked(api).mockImplementation(async (_path, options) => {
    if (options?.method === "PUT")
      writes.push(JSON.parse(String(options.body)));
    return view;
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ProfileReconciliation />
    </QueryClientProvider>,
  );
  await userEvent.selectOptions(
    await screen.findByLabelText("Profile check interval"),
    "1800",
  );
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    expected_revision: 3,
    policy: {
      enabled: true,
      auto_profile_sync: false,
      interval_seconds: 1800,
      approved_fields: [],
      profile_version: 4,
    },
  });
  client.clear();
});

it("starts with 80/day, two-day postings and explicit unknown-applicant handling", () => {
  render(<QueuePolicyForm configuration={configuration} saved={saved} />);
  expect(
    screen.getByLabelText("Global maximum applications per day"),
  ).toHaveValue(80);
  expect(
    screen.getByLabelText("Global maximum posting age in days"),
  ).toHaveValue(2);
  expect(
    screen.getByLabelText("Global applicant threshold (skip at or above)"),
  ).toHaveValue(10000);
  expect(screen.getByLabelText("When applicant count is unknown")).toHaveValue(
    "needs_review",
  );
  expect(screen.getByRole("button", { name: "START QUEUE" })).toBeDisabled();
  expect(api).not.toHaveBeenCalled();
});

it("saves independent Naukri limits and multiple typed preferences without losing commas", async () => {
  render(<QueuePolicyForm configuration={configuration} saved={saved} />);
  const user = userEvent.setup();
  await user.click(screen.getByLabelText("Enable Naukri automation"));
  await user.selectOptions(
    screen.getByLabelText("Naukri daily cap source"),
    "custom",
  );
  await user.clear(
    screen.getByLabelText("Naukri maximum applications per day"),
  );
  await user.type(
    screen.getByLabelText("Naukri maximum applications per day"),
    "95",
  );
  await user.selectOptions(
    screen.getByLabelText("Naukri posting age source"),
    "custom",
  );
  await user.selectOptions(
    screen.getByLabelText("Naukri applicant threshold source"),
    "custom",
  );
  await user.clear(
    screen.getByLabelText("Naukri applicant threshold (skip at or above)"),
  );
  await user.type(
    screen.getByLabelText("Naukri applicant threshold (skip at or above)"),
    "500",
  );
  await user.selectOptions(
    screen.getByLabelText("Naukri job preferences"),
    "custom",
  );
  await user.type(
    screen.getByLabelText("Naukri job titles"),
    "Backend Developer, Software Engineer",
  );
  await user.type(screen.getByLabelText("Naukri locations"), "Pune, Hyderabad");
  await user.click(screen.getByRole("button", { name: "Save queue policy" }));
  await waitFor(() => expect(api).toHaveBeenCalled());
  const [path, options] = vi.mocked(api).mock.calls[0];
  expect(path).toBe("execution/queue/policy");
  const payload = JSON.parse(String(options?.body));
  expect(payload.expected_revision).toBe(7);
  expect(payload.policy.global_limits.daily_cap).toBe(80);
  expect(payload.policy.platforms.naukri.limits.daily_cap).toBe(95);
  expect(payload.policy.platforms.naukri.limits.applicant_limit).toBe(500);
  expect(payload.policy.platforms.naukri.preferences.roles).toEqual([
    "Backend Developer",
    "Software Engineer",
  ]);
  expect(payload.policy.platforms.naukri.preferences.locations).toEqual([
    "Pune",
    "Hyderabad",
  ]);
  expect(payload.policy.platforms.naukri.owner_submission_authorized).toBe(
    false,
  );
});

it("saves the owner's match threshold of 50 while retaining the other global limits", async () => {
  render(<QueuePolicyForm configuration={configuration} saved={saved} />);
  const user = userEvent.setup();
  const score = screen.getByLabelText("Global minimum match score");
  expect(score).toHaveAttribute("min", "50");
  await user.clear(score);
  await user.type(score, "50");
  await user.click(screen.getByRole("button", { name: "Save queue policy" }));
  await waitFor(() => expect(api).toHaveBeenCalled());
  const [, options] = vi.mocked(api).mock.calls[0];
  const payload = JSON.parse(String(options?.body));
  expect(payload.policy.global_limits).toEqual({
    ...configuration.policy.global_limits,
    minimum_match_score: 50,
  });
  expect(payload.policy.platforms).toEqual(configuration.policy.platforms);
});

it("retains dirty edits and prevents overwriting a newer server policy", async () => {
  const { rerender } = render(
    <QueuePolicyForm configuration={configuration} saved={saved} />,
  );
  const input = screen.getByLabelText("Global maximum applications per day");
  await userEvent.clear(input);
  await userEvent.type(input, "90");
  rerender(
    <QueuePolicyForm
      configuration={{ ...configuration, revision: 8 }}
      saved={saved}
    />,
  );
  expect(input).toHaveValue(90);
  expect(
    screen.getByRole("button", { name: "Save queue policy" }),
  ).toBeDisabled();
  expect(screen.getByText(/Settings changed in another session/)).toBeVisible();
});

it("issues revision-fenced pause and stop through only the intended gateway routes", async () => {
  render(<QueuePolicyForm configuration={configuration} saved={saved} />);
  await userEvent.click(screen.getByRole("button", { name: "PAUSE QUEUE" }));
  await userEvent.click(screen.getByRole("button", { name: "STOP QUEUE" }));
  expect(post).toHaveBeenCalledWith("execution/queue/control", {
    action: "pause",
    expected_revision: 7,
  });
  expect(post).toHaveBeenCalledWith("execution/queue/control", {
    action: "stop",
    expected_revision: 7,
  });
  expect(permittedRoute("execution/queue", "GET")).toBe(true);
  expect(permittedRoute("execution/queue/policy", "PUT")).toBe(true);
  expect(permittedRoute("execution/queue/control", "POST")).toBe(true);
  expect(permittedRoute("execution/queue/claim", "POST")).toBe(false);
});

it("filters the ledger without inventing unknown applicant counts", async () => {
  vi.mocked(api).mockResolvedValue({
    configuration,
    total: 1,
    counts: {
      NEEDS_INPUT: 1,
      DISCOVERED: 17,
      SKIPPED: 350,
      SUBMITTED_RECORDED: 1,
    },
    items: [
      {
        id: "fictional",
        platform: "naukri",
        requisition: "291026123456",
        title: "Fictional Developer",
        company: "Fictional employer",
        location: "Pune",
        stage: "NEEDS_INPUT",
        status: "waiting",
        reason: "applicant_count_requires_review",
        match_score: 90,
        posted_at: null,
        posted_date: "2026-10-31",
        applicants_min: null,
        applicants_max: null,
        created_at: "2026-10-31T00:00:00Z",
      },
    ],
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ApplicationQueue />
    </QueryClientProvider>,
  );
  const progress = await screen.findByRole("region", {
    name: "Discovery and application progress",
  });
  expect(progress).toHaveTextContent("17 jobs awaiting listing checks");
  expect(progress).toHaveTextContent("0 eligible jobs awaiting preparation");
  expect(progress).toHaveTextContent("0 new submissions confirmed");
  expect(progress).toHaveTextContent("1 previously recorded applications");
  expect(await screen.findByText("Fictional Developer")).toBeVisible();
  expect(screen.getByText("2026-10-31 (time unknown)")).toBeVisible();
  await userEvent.selectOptions(
    screen.getByLabelText("Queue status filter"),
    "NEEDS_INPUT",
  );
  await userEvent.type(
    screen.getByLabelText("Search role, employer or requisition"),
    "Fictional employer",
  );
  await userEvent.click(screen.getByRole("button", { name: "Filter jobs" }));
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.some(
          ([path]) =>
            path.includes("stage=NEEDS_INPUT") &&
            path.includes("search=Fictional+employer"),
        ),
    ).toBe(true),
  );
  expect(screen.getByText("applicant count requires review")).toBeVisible();
});
