import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Schema } from "@/lib/api";
import { CandidateKnowledge } from "@/features/candidate-knowledge";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));

const fictionalProfile: Schema<"CandidateProfileRead"> = {
  id: "profile-1001",
  singleton_key: "primary",
  version: 4,
  full_name: "Kavya Sharma",
  email: "kavya.sharma@example.org",
  phone: "+91 98765 43210",
  summary:
    "Backend engineer with 5 years experience scaling Python and FastAPI microservices.",
  github_url: "https://github.com/kavyasharma-example",
  linkedin_url: "https://linkedin.com/in/kavyasharma-example",
  portfolio_url: "https://kavyasharma.example.dev",
  personal_website: null,
  verified_experience_years: 5,
  verified_skills: ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
  verified_roles: [
    {
      company: "TechScale",
      role: "Backend Engineer",
      start_date: "2021-01-01",
      end_date: "2023-01-01",
    },
    {
      company: "CloudWorks",
      role: "Senior Software Engineer",
      start_date: "2023-01-01",
      end_date: null,
    },
  ],
  education: [],
  certifications: [],
  projects: [
    {
      name: "High-Throughput Order Ingestion",
      description:
        "Distributed queuing engine handling 10k RPS with idempotent processing.",
      contribution: "Designed database models and Redis lock coordinator.",
      technologies: ["Python", "FastAPI", "Redis", "PostgreSQL"],
      measurable_results:
        "Reduced latency p99 by 40% and eliminated duplicate charges.",
      url: "https://github.com/kavyasharma-example/order-engine",
    },
  ],
  preferences: {
    current_location: "Bengaluru, Karnataka, India",
    notice_period_days: 30,
    remote_preference: "remote",
    current_compensation: {
      amount: "2800000",
      currency: "INR",
      period: "year",
      kind: "ctc",
    },
    expected_compensation: {
      amount: "3600000",
      currency: "INR",
      period: "year",
      kind: "ctc",
    },
    work_authorizations: [
      {
        country_code: "IN",
        country_name: "India",
        authorized_to_work: true,
        requires_sponsorship_now_or_future: false,
      },
    ],
  },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-02-15T12:00:00Z",
};

const fictionalResources: Schema<"ResourceList"> = {
  resources: [
    {
      id: "res-1",
      candidate_profile_id: "profile-1001",
      label: "Official GitHub Profile",
      url: "https://github.com/kavyasharma-example",
      resource_type: "portfolio",
      source_type: "portfolio",
      is_primary: false,
      user_confirmed: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  resolved_links: [],
  offset: 0,
  limit: 10,
};

const fictionalDrafts: { drafts: Schema<"DraftRead">[] } = {
  drafts: [
    {
      id: "draft-1",
      candidate_profile_id: "profile-1001",
      job_id: null,
      question: "Describe a complex backend system you designed and scaled.",
      question_category: "technical_experience",
      writing_style: "technical",
      provider: "anthropic",
      model: "claude-3-sonnet",
      answer:
        "I designed a distributed queuing pipeline with Redis and FastAPI handling 10k RPS.",
      review_status: "reviewed",
      candidate_profile_version: 4,
      stale: false,
      evidence_references: [
        {
          source_type: "verified_project",
          source_id: "proj-1",
        },
      ],
      created_at: "2026-02-01T00:00:00Z",
      updated_at: "2026-02-01T00:00:00Z",
    },
    {
      id: "draft-2",
      candidate_profile_id: "profile-1001",
      job_id: null,
      question: "What is your current notice period?",
      question_category: "short_text",
      writing_style: "concise",
      provider: "anthropic",
      model: "claude-3-sonnet",
      answer: "My official notice period is 30 days.",
      review_status: "reviewed",
      candidate_profile_version: 3,
      stale: true,
      evidence_references: [],
      created_at: "2026-01-10T00:00:00Z",
      updated_at: "2026-01-10T00:00:00Z",
    },
  ],
};

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <CandidateKnowledge />
    </QueryClientProvider>,
  );
}

describe("Candidate Knowledge & Approved Facts UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "profile") {
        return fictionalProfile as any;
      }
      if (path === "candidate/resources") {
        return fictionalResources as any;
      }
      if (path === "application-answers/drafts") {
        return fictionalDrafts.drafts as any;
      }
      return {} as any;
    });
  });

  it("renders current approved profile facts truthfully without guessing missing data", async () => {
    mount();

    expect(await screen.findByText("Kavya Sharma")).toBeInTheDocument();
    expect(screen.getByText("kavya.sharma@example.org")).toBeInTheDocument();
    expect(screen.getByText("Bengaluru, Karnataka, India")).toBeInTheDocument();
    expect(screen.getByText("5 years")).toBeInTheDocument();
    expect(screen.getByText("30 days")).toBeInTheDocument();
    expect(screen.getByText("Approved Version 4")).toBeInTheDocument();

    // Verified skills
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    expect(screen.getByText("Docker")).toBeInTheDocument();

    // Compensation facts
    expect(
      screen.getByText(/2800000 INR \/ year \(ctc\)/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/3600000 INR \/ year \(ctc\)/i),
    ).toBeInTheDocument();
  });

  it("displays honest unknown labels when optional candidate attributes are not provided", async () => {
    const minimalProfile: Schema<"CandidateProfileRead"> = {
      ...fictionalProfile,
      phone: null,
      summary: null,
      preferences: {
        current_location: null,
        notice_period_days: null,
        remote_preference: "any",
        current_compensation: null,
        expected_compensation: null,
        work_authorizations: [],
      },
    };
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "profile") return minimalProfile as any;
      if (path === "candidate/resources") return { resources: [] } as any;
      if (path === "application-answers/drafts") return [] as any;
      return {} as any;
    });

    mount();

    expect(await screen.findByText("Kavya Sharma")).toBeInTheDocument();
    expect(
      screen.getAllByText("Unknown / not provided").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Unknown / not established")).toBeInTheDocument();
    expect(screen.getAllByText("Unknown / not disclosed").length).toBe(2);
    expect(screen.getByText("No summary recorded")).toBeInTheDocument();
  });

  it("navigates to edit facts and validates factual confirmation before saving", async () => {
    mount();

    expect(await screen.findByText("Kavya Sharma")).toBeInTheDocument();

    // Switch to Edit facts tab
    const editTab = screen.getByRole("tab", {
      name: "Edit personal & career facts",
    });
    await userEvent.click(editTab);

    expect(
      screen.getByRole("heading", { name: "Edit Candidate Facts" }),
    ).toBeInTheDocument();

    // Save button must be disabled when confirmation checkbox is unchecked
    const saveButton = screen.getByRole("button", {
      name: /Save and approve version 5/i,
    });
    expect(saveButton).toBeDisabled();

    // Check the truthful confirmation checkbox
    const confirmationCheckbox = screen.getByLabelText(
      /I confirm these facts are truthful, verified, and represent my actual candidate background/i,
    );
    await userEvent.click(confirmationCheckbox);

    // Save button becomes enabled
    expect(saveButton).toBeEnabled();
  });

  it("sends If-Match precondition header and successfully updates approved facts version", async () => {
    const updatedProfile: Schema<"CandidateProfileRead"> = {
      ...fictionalProfile,
      version: 5,
      preferences: {
        ...fictionalProfile.preferences,
        notice_period_days: 15,
      },
    };

    vi.mocked(api).mockImplementation(async (path: string, options?: any) => {
      if (path === "profile" && options?.method === "PUT") {
        expect(options.headers["If-Match"]).toBe('"4"');
        const parsed = JSON.parse(options.body);
        expect(parsed.preferences.notice_period_days).toBe(15);
        return updatedProfile as any;
      }
      if (path === "profile") return fictionalProfile as any;
      if (path === "candidate/resources") return fictionalResources as any;
      if (path === "application-answers/drafts")
        return fictionalDrafts.drafts as any;
      return {} as any;
    });

    mount();

    await screen.findByText("Kavya Sharma");

    // Switch to edit tab
    await userEvent.click(
      screen.getByRole("tab", { name: "Edit personal & career facts" }),
    );

    // Change notice period
    const noticeInput = screen.getByLabelText(/Notice period \(days\)/i);
    await userEvent.clear(noticeInput);
    await userEvent.type(noticeInput, "15");

    // Check truthfulness confirmation
    await userEvent.click(
      screen.getByLabelText(
        /I confirm these facts are truthful, verified, and represent my actual candidate background/i,
      ),
    );

    // Click save
    await userEvent.click(
      screen.getByRole("button", { name: /Save and approve version 5/i }),
    );

    // Success notice and navigation back to approved overview
    expect(
      await screen.findByText(
        "Candidate facts saved successfully as approved version 5.",
      ),
    ).toBeInTheDocument();
  });

  it.each([409, 412])(
    "handles %s version conflicts gracefully with alert and reload action",
    async (status) => {
      const conflictError = new Error("Precondition Failed");
      (conflictError as any).status = status;

      vi.mocked(api).mockImplementation(async (path: string, options?: any) => {
        if (path === "profile" && options?.method === "PUT") {
          throw conflictError;
        }
        if (path === "profile") return fictionalProfile as any;
        if (path === "candidate/resources") return fictionalResources as any;
        if (path === "application-answers/drafts")
          return fictionalDrafts.drafts as any;
        return {} as any;
      });

      mount();

      await screen.findByText("Kavya Sharma");

      // Switch to edit tab
      await userEvent.click(
        screen.getByRole("tab", { name: "Edit personal & career facts" }),
      );

      // Confirm and save
      await userEvent.click(
        screen.getByLabelText(
          /I confirm these facts are truthful, verified, and represent my actual candidate background/i,
        ),
      );
      await userEvent.click(
        screen.getByRole("button", { name: /Save and approve version 5/i }),
      );

      // Conflict error alert is displayed
      expect(
        await screen.findByText(/Profile version conflict/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /Stale revision conflict: This profile was updated elsewhere/i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Reload latest approved version" }),
      ).toBeInTheDocument();
    },
  );

  it("displays verified projects and supports adding new project with measurable evidence", async () => {
    mount();

    await screen.findByText("Kavya Sharma");

    // Switch to Projects tab
    await userEvent.click(
      screen.getByRole("tab", { name: /Projects & achievements/i }),
    );

    // Existing project is listed
    expect(
      screen.getByText("High-Throughput Order Ingestion"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Distributed queuing engine handling 10k RPS/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Reduced latency p99 by 40%/i)).toBeInTheDocument();

    // Click Add Project button on page
    await userEvent.click(screen.getByRole("button", { name: "Add project" }));

    // Modal opens
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      within(dialog).getByRole("heading", { name: "Add Project" }),
    ).toBeInTheDocument();

    // Fill in new project instantly with change events
    fireEvent.change(within(dialog).getByLabelText(/Project title/i), {
      target: { value: "Observability Mesh" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Project description/i), {
      target: {
        value: "Telemetry aggregation using OpenTelemetry and Prometheus.",
      },
    });
    fireEvent.change(within(dialog).getByLabelText(/Your role/i), {
      target: { value: "Architect" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Technologies used/i), {
      target: { value: "Go, Prometheus, OpenTelemetry" },
    });
    fireEvent.change(
      within(dialog).getByLabelText(/Measurable impact \/ Achievements/i),
      { target: { value: "Reduced MTTR by 35%" } },
    );

    // Save project in modal
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Add project" }),
    );

    // New project appears in list
    expect(await screen.findByText("Observability Mesh")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Telemetry aggregation using OpenTelemetry and Prometheus.",
      ),
    ).toBeInTheDocument();
  }, 15000);

  it("displays approved reusable answers and flags stale dependent answers when profile changes", async () => {
    mount();

    await screen.findByText("Kavya Sharma");

    // Switch to Reusable answers tab
    await userEvent.click(screen.getByRole("tab", { name: /Saved answers/i }));

    // Active approved answer
    expect(
      screen.getByText(
        "Describe a complex backend system you designed and scaled.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Recorded for Profile v4")).toBeInTheDocument();

    // Stale answer with warning badge
    expect(
      screen.getByText("What is your current notice period?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Profile facts updated · Review required"),
    ).toBeInTheDocument();
    expect(screen.getByText("Recorded for Profile v3")).toBeInTheDocument();
  });
});

it("requires explicit project confirmation and can persist removal of the last project", async () => {
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === "profile" && options?.method === "PUT")
      return { ...fictionalProfile, projects: [], version: 5 } as any;
    if (path === "profile") return fictionalProfile as any;
    if (path === "application-answers/drafts") return [] as any;
    if (path === "application-answers/reuse-approvals")
      return { enabled: false, approvals: {} } as any;
    return fictionalResources as any;
  });
  mount();
  await screen.findByText("Kavya Sharma");
  await userEvent.click(
    screen.getByRole("tab", { name: /Projects & achievements/ }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  const save = screen.getByRole("button", {
    name: "Save project changes to profile",
  });
  expect(save).toBeDisabled();
  await userEvent.click(
    screen.getByLabelText(/I confirm these project changes are truthful/),
  );
  await userEvent.click(save);
  expect(api).toHaveBeenCalledWith(
    "profile",
    expect.objectContaining({
      method: "PUT",
      body: expect.stringContaining('"projects":[]'),
    }),
  );
});
