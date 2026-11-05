import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  Applications,
  ApplicationDetail,
  pipelineColumn,
} from "@/features/applications";
import { api, patch, post, externalUrl, type Schema } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/applications",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

const mockPacket: Schema<"PacketRead"> = {
  id: "00000000-1111-2222-3333-444444444444",
  platform: "direct_employer",
  lifecycle_state: "ready_for_review",
  tracking_state: "not_applied",
  revision: 2,
  approved_revision: null,
  review_status: "pending",
  created_at: "2026-10-25T10:00:00Z",
  updated_at: "2026-10-26T12:00:00Z",
  job_id: "job-uuid-1111",
  submission_mode: "manual_handoff",
  snapshot: {
    preparation_supported: true,
    platform: "direct_employer",
    job_title: "Senior Backend Engineer",
    company_name: "Acme Distributed Systems",
    source_platform: "arbeitnow",
    original_job_url: "https://arbeitnow.example.org/jobs/acme-backend",
    source_observation_urls: [
      "https://arbeitnow.example.org/jobs/acme-backend",
    ],
    destination: {
      application_url: "https://careers.acme.example.com/apply/123",
      kind: "employer_external",
      valid: true,
      source_confidence: "source_consistent",
      warnings: [],
    },
    context_digest: "digest123",
    warnings: [],
    resume: {
      selected: {
        resource_id: "res-uuid-1111",
        label: "Backend Core Resume 2026",
        url: "https://storage.example.org/resumes/backend.pdf",
        confirmed: true,
        primary: true,
        resource_version: "v2",
        download_path: "/api/backend/dashboard/resumes/res-uuid-1111",
      },
      alternatives: [
        {
          resource_id: "res-uuid-1111",
          label: "Backend Core Resume 2026",
          url: "https://storage.example.org/resumes/backend.pdf",
          confirmed: true,
          primary: true,
          resource_version: "v2",
          download_path: "/api/backend/dashboard/resumes/res-uuid-1111",
        },
        {
          resource_id: "res-uuid-2222",
          label: "Fullstack Resume (Unconfirmed)",
          url: null,
          confirmed: false,
          primary: false,
          resource_version: "v1",
        },
      ],
      reason: "Selected based on backend role relevance.",
      upload_status: "manual_resume_upload_required",
    },
  },
  fields: [
    {
      id: "field-1",
      question: "Why do you want to work at Acme?",
      category: "motivation",
      field_type: "textarea",
      required: true,
      max_characters: 500,
      validation_status: "draft_ready",
      review_status: "pending",
      effective_answer:
        "I am passionate about high-throughput distributed systems.",
      writing_style: "professional",
      answer_revision: 1,
      requires_review: false,
      missing_information: [],
      provenance: {
        origin: "user_provided",
        source: "candidate_profile",
        resolver: "deterministic",
        evidence_references: [],
      },
    },
    {
      id: "field-2",
      question: "Describe your hardest technical challenge.",
      category: "project_explanation",
      field_type: "textarea",
      required: false,
      max_characters: 1000,
      validation_status: "needs_input",
      review_status: "pending",
      effective_answer: "",
      writing_style: "professional",
      answer_revision: 1,
      requires_review: false,
      missing_information: ["Specific benchmark metrics for distributed cache"],
      provenance: {
        origin: "user_provided",
        source: "missing",
        resolver: "needs_input",
        evidence_references: [],
        error_code: "missing_candidate_facts",
      },
    },
  ],
  readiness: {
    state: "needs_review",
    blockers: [],
    manual_steps: [
      "Download verified resume PDF",
      "Paste reviewed answers into official application page",
      "Upload resume manually and submit",
    ],
    warnings: [],
    stale: false,
  },
};

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("Applications Pipeline & Detail Views", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("pipelineColumn lifecycle states", () => {
    it("maps all lifecycle states accurately without false 'Applied' assertions", () => {
      expect(
        pipelineColumn({
          lifecycle_state: "created",
          tracking_state: "not_applied",
        }),
      ).toBe("Preparing");
      expect(
        pipelineColumn({
          lifecycle_state: "preparing",
          tracking_state: "not_applied",
        }),
      ).toBe("Preparing");
      expect(
        pipelineColumn({
          lifecycle_state: "needs_input",
          tracking_state: "not_applied",
        }),
      ).toBe("Needs Input");
      expect(
        pipelineColumn({
          lifecycle_state: "ready_for_review",
          tracking_state: "not_applied",
        }),
      ).toBe("Ready for Review");
      expect(
        pipelineColumn({
          lifecycle_state: "approved_for_manual_handoff",
          tracking_state: "not_applied",
        }),
      ).toBe("Approved / Manual Handoff");
      expect(
        pipelineColumn({
          lifecycle_state: "external_application_opened",
          tracking_state: "not_applied",
        }),
      ).toBe("External Application Opened");
      expect(
        pipelineColumn({
          lifecycle_state: "submission_unknown",
          tracking_state: "not_applied",
        }),
      ).toBe("Submission Unknown");
      expect(
        pipelineColumn({
          lifecycle_state: "user_reported_submitted",
          tracking_state: "applied_manually",
        }),
      ).toBe("Applied — User Reported");
      expect(
        pipelineColumn({
          lifecycle_state: "provider_confirmed_submitted",
          tracking_state: "applied_verified",
        }),
      ).toBe("Applied — Provider Confirmed");
      expect(
        pipelineColumn({
          lifecycle_state: "ready_for_review",
          tracking_state: "interview_scheduled",
        }),
      ).toBe("Interview");
      expect(
        pipelineColumn({
          lifecycle_state: "user_reported_submitted",
          tracking_state: "offer_received",
        }),
      ).toBe("Offer");
      expect(
        pipelineColumn({
          lifecycle_state: "user_reported_submitted",
          tracking_state: "application_rejected",
        }),
      ).toBe("Rejected");
      expect(
        pipelineColumn({
          lifecycle_state: "abandoned",
          tracking_state: "archived",
        }),
      ).toBe("Archived");
    });
  });

  describe("Applications dashboard view", () => {
    it("renders empty state with CTA when no packets exist", async () => {
      vi.mocked(api).mockResolvedValueOnce({
        packets: [],
        offset: 0,
        limit: 100,
      });
      renderWithClient(<Applications />);

      expect(
        await screen.findByText(
          "Your next chapter, one application at a time.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: /Explore saved jobs/i }),
      ).toBeVisible();
    });

    it("renders board view with all pipeline columns and packet cards", async () => {
      vi.mocked(api).mockResolvedValueOnce({
        packets: [mockPacket],
        offset: 0,
        limit: 100,
      });
      renderWithClient(<Applications />);

      expect(
        await screen.findByText("Senior Backend Engineer"),
      ).toBeInTheDocument();
      expect(screen.getByText("Acme Distributed Systems")).toBeInTheDocument();
      expect(screen.getByText("Ready for Review")).toBeInTheDocument();
      expect(screen.getByText("Needs Input")).toBeInTheDocument();
      expect(screen.getByText("Approved / Manual Handoff")).toBeInTheDocument();
      expect(
        screen.getByText("External Application Opened"),
      ).toBeInTheDocument();
    });

    it("switches to table view and displays tabular data", async () => {
      vi.mocked(api).mockResolvedValueOnce({
        packets: [mockPacket],
        offset: 0,
        limit: 100,
      });
      renderWithClient(<Applications />);

      await screen.findByText("Senior Backend Engineer");
      const tableButton = screen.getByRole("button", { name: /Table/i });
      await userEvent.click(tableButton);

      expect(screen.getByRole("table")).toBeInTheDocument();
      expect(screen.getByText("JOB / COMPANY")).toBeInTheDocument();
      expect(screen.getByText("PROGRESS")).toBeInTheDocument();
    });
  });

  describe("ApplicationDetail view", () => {
    beforeEach(() => {
      vi.mocked(api).mockImplementation((path: string) => {
        if (path === `application-packets/${mockPacket.id}`) {
          return Promise.resolve(mockPacket);
        }
        if (path === `application-packets/${mockPacket.id}/events`) {
          return Promise.resolve([]);
        }
        if (path === "browser-applications/policy") {
          return Promise.resolve({ origins: [], digest: "test-digest" });
        }
        return Promise.reject(new Error(`Unhandled GET path: ${path}`));
      });
    });

    it("displays company, title, destination URL, and confirmed resume status", async () => {
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Senior Backend Engineer",
        }),
      ).toBeInTheDocument();
      expect(
        screen.getAllByText("Acme Distributed Systems").length,
      ).toBeGreaterThanOrEqual(1);
      expect(
        screen.getAllByText("Backend Core Resume 2026").length,
      ).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Confirmed").length).toBeGreaterThanOrEqual(1);
      expect(
        screen.getAllByText("https://careers.acme.example.com/apply/123")
          .length,
      ).toBeGreaterThanOrEqual(1);
      expect(
        screen.getByText(
          /Isolated testing can attach an approved canonical PDF after upload checks/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Chrome extension attachments remain manual/),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/unless explicitly reviewed for overwrite/),
      ).not.toBeInTheDocument();
    });

    it("displays live character and word counters and warns when limit is exceeded", async () => {
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      await screen.findByRole("heading", {
        level: 1,
        name: "Senior Backend Engineer",
      });
      const counters = screen.getAllByText(/characters · \d+ words/i);
      expect(counters.length).toBeGreaterThanOrEqual(1);
      expect(counters[0]).toHaveTextContent("58 / 500 characters · 7 words");
    });

    it("shows missing candidate facts truthfully without inventing qualifications", async () => {
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      expect(
        await screen.findByText(
          /Missing candidate facts: Specific benchmark metrics for distributed cache/i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /Required candidate facts were not found in your profile\. Real qualifications cannot be invented\./i,
        ),
      ).toBeInTheDocument();
    });

    it("enforces a supplied word limit before saving or reviewing an answer", async () => {
      const boundedPacket = {
        ...mockPacket,
        fields: [
          {
            ...mockPacket.fields[0],
            max_words: 3,
            effective_answer: "I build",
          },
        ],
      };
      vi.mocked(api).mockImplementation((path: string) =>
        Promise.resolve(
          path === `application-packets/${mockPacket.id}`
            ? boundedPacket
            : path.endsWith("/events")
              ? []
              : { origins: [], digest: "test-digest" },
        ),
      );
      vi.mocked(patch).mockResolvedValue({});
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);
      const question = await screen.findByText(mockPacket.fields[0].question, {
        exact: false,
      });
      const field = within(question.closest(".evidence-item") as HTMLElement);
      const answer = field.getByLabelText("Reviewable answer");
      await userEvent.clear(answer);
      await userEvent.type(answer, "I build reliable APIs");
      expect(field.getByText(/4 \/ 3 words/)).toHaveTextContent(
        "(exceeds word limit)",
      );
      expect(field.getByRole("button", { name: "Save answer" })).toBeDisabled();
      expect(
        field.getByLabelText("I reviewed this exact answer"),
      ).toBeDisabled();
      expect(patch).not.toHaveBeenCalled();
      await userEvent.clear(answer);
      await userEvent.type(answer, "I build APIs");
      await userEvent.click(field.getByRole("button", { name: "Save answer" }));
      await waitFor(() => {
        expect(patch).toHaveBeenCalledWith(
          `application-packets/${mockPacket.id}/questions/${mockPacket.fields[0].id}`,
          { expected_revision: mockPacket.revision, answer: "I build APIs" },
        );
      });
    });

    it("offers configured generation for supported technical experience questions", async () => {
      vi.mocked(api).mockImplementation((path: string) =>
        Promise.resolve(
          path === `application-packets/${mockPacket.id}`
            ? {
                ...mockPacket,
                fields: [{ ...mockPacket.fields[0], category: "experience" }],
              }
            : path.endsWith("/events")
              ? []
              : { origins: [], digest: "test-digest" },
        ),
      );
      vi.mocked(post).mockResolvedValue({});
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);
      await userEvent.click(
        await screen.findByRole("button", {
          name: "Generate with configured AI",
        }),
      );
      await waitFor(() => {
        expect(post).toHaveBeenCalledWith(
          `application-packets/${mockPacket.id}/questions/${mockPacket.fields[0].id}/generate`,
          { expected_revision: mockPacket.revision, rewrite: true },
        );
      });
    });

    it("saves edited answers and resets dirty state", async () => {
      vi.mocked(patch).mockResolvedValue({});
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      await screen.findByRole("heading", {
        level: 1,
        name: "Senior Backend Engineer",
      });
      const textarea = screen.getAllByRole("textbox")[0];
      await userEvent.clear(textarea);
      await userEvent.type(textarea, "Updated motivation answer.");

      const saveButton = screen.getAllByRole("button", {
        name: "Save answer",
      })[0];
      expect(saveButton).toBeEnabled();
      await userEvent.click(saveButton);

      await waitFor(() => {
        expect(patch).toHaveBeenCalledWith(
          `application-packets/${mockPacket.id}/questions/${mockPacket.fields[0].id}`,
          {
            expected_revision: mockPacket.revision,
            answer: "Updated motivation answer.",
          },
        );
      });
    });

    it("requires resume and destination confirmation before enabling approval", async () => {
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      await screen.findByRole("heading", {
        level: 1,
        name: "Senior Backend Engineer",
      });
      const approveButton = screen.getByRole("button", {
        name: "Approve current packet",
      });
      expect(approveButton).toBeDisabled();

      const resumeCheck = screen.getByLabelText(
        "I reviewed the selected resume variant.",
      );
      const destinationCheck = screen.getByLabelText(
        "I verified this is the official application destination.",
      );

      await userEvent.click(resumeCheck);
      expect(approveButton).toBeDisabled();

      await userEvent.click(destinationCheck);
      expect(approveButton).toBeEnabled();
    });

    it("supports adding questions from standard narrative and factual templates", async () => {
      vi.mocked(post).mockResolvedValue({});
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      await screen.findByRole("heading", {
        level: 1,
        name: "Senior Backend Engineer",
      });
      const templateSelect = screen.getByLabelText(
        "Choose from common question templates",
      );
      await userEvent.selectOptions(
        templateSelect,
        "Why this role? (Narrative)",
      );

      expect(
        screen.getByDisplayValue("Why are you a good fit for this role?"),
      ).toBeInTheDocument();

      const addBtn = screen.getByRole("button", { name: "Add question" });
      await userEvent.click(addBtn);

      await waitFor(() => {
        expect(post).toHaveBeenCalledWith(
          `application-packets/${mockPacket.id}/questions`,
          expect.objectContaining({
            expected_revision: mockPacket.revision,
            questions: [
              expect.objectContaining({
                question: "Why are you a good fit for this role?",
                category: "motivation",
                field_type: "textarea",
                required: true,
              }),
            ],
          }),
        );
      });
    });

    it.each(["multiple_choice", "multi_select", "yes_no"] as const)(
      "adds a %s question only with the actual form options",
      async (fieldType) => {
        vi.mocked(post).mockResolvedValue({});
        renderWithClient(<ApplicationDetail id={mockPacket.id} />);
        await screen.findByRole("heading", {
          level: 1,
          name: "Senior Backend Engineer",
        });
        await userEvent.type(
          screen.getByLabelText("Question text"),
          "Which working arrangements are available to you?",
        );
        await userEvent.selectOptions(
          screen.getByLabelText("Field type"),
          fieldType,
        );
        const add = screen.getByRole("button", { name: "Add question" });
        expect(add).toBeDisabled();
        expect(post).not.toHaveBeenCalled();
        await userEvent.type(
          screen.getByLabelText("Actual form options (one per line)"),
          "Remote\nHybrid",
        );
        await userEvent.click(add);
        await waitFor(() => {
          expect(post).toHaveBeenCalledWith(
            `application-packets/${mockPacket.id}/questions`,
            expect.objectContaining({
              questions: [
                expect.objectContaining({
                  field_type: fieldType,
                  options: ["Remote", "Hybrid"],
                }),
              ],
            }),
          );
        });
      },
    );

    it("displays submission unknown state with explicit recovery instructions and disables reporting", async () => {
      const unknownPacket: Schema<"PacketRead"> = {
        ...mockPacket,
        lifecycle_state: "submission_unknown",
      };
      vi.mocked(api).mockImplementation((path: string) => {
        if (path === `application-packets/${unknownPacket.id}`) {
          return Promise.resolve(unknownPacket);
        }
        if (path === `application-packets/${unknownPacket.id}/events`) {
          return Promise.resolve([]);
        }
        if (path === "browser-applications/policy") {
          return Promise.resolve({ origins: [], digest: "test-digest" });
        }
        return Promise.reject(new Error(`Unhandled GET path: ${path}`));
      });

      renderWithClient(<ApplicationDetail id={unknownPacket.id} />);

      expect(
        await screen.findByText(
          /Submission outcome is unknown due to an ambiguous dispatch attempt\./i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /Manual completion reporting is disabled until the ambiguous dispatch attempt is reconciled\./i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Report manual completion" }),
      ).toBeDisabled();
    });

    it("enforces max_words limit and supports experience narrative generation", async () => {
      const narrativePacket: Schema<"PacketRead"> = {
        ...mockPacket,
        fields: [
          {
            id: "f-exp",
            question: "What was the hardest technical problem you solved?",
            category: "experience",
            field_type: "textarea",
            required: true,
            effective_answer: "One two three four five six",
            max_characters: 500,
            max_words: 5,
            validation_status: "needs_input",
            review_status: "pending",
            answer_revision: 1,
            requires_review: false,
            writing_style: "professional",
            missing_information: [],
          },
        ],
      };
      vi.mocked(api).mockImplementation((path: string) => {
        if (path === `application-packets/${narrativePacket.id}`) {
          return Promise.resolve(narrativePacket);
        }
        if (path === `application-packets/${narrativePacket.id}/events`) {
          return Promise.resolve([]);
        }
        if (path === "browser-applications/policy") {
          return Promise.resolve({ origins: [], digest: "test-digest" });
        }
        return Promise.reject(new Error(`Unhandled GET path: ${path}`));
      });

      renderWithClient(<ApplicationDetail id={narrativePacket.id} />);

      expect(
        await screen.findByText(/6 \/ 5 words \(exceeds word limit\)/i),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Generate with configured AI" }),
      ).toBeInTheDocument();
    });

    it("opens manual completion reporting modal requiring human confirmation", async () => {
      const approvedPacket: Schema<"PacketRead"> = {
        ...mockPacket,
        lifecycle_state: "approved_for_manual_handoff",
        approved_revision: 2,
      };
      vi.mocked(api).mockImplementation((path: string) => {
        if (path === `application-packets/${approvedPacket.id}`) {
          return Promise.resolve(approvedPacket);
        }
        if (path === `application-packets/${approvedPacket.id}/events`) {
          return Promise.resolve([]);
        }
        if (path === "browser-applications/policy") {
          return Promise.resolve({ origins: [], digest: "test-digest" });
        }
        return Promise.reject(new Error(`Unhandled GET path: ${path}`));
      });
      vi.mocked(post).mockResolvedValue({});

      renderWithClient(<ApplicationDetail id={approvedPacket.id} />);

      const reportBtn = await screen.findByRole("button", {
        name: "Report manual completion",
      });
      await userEvent.click(reportBtn);

      expect(screen.getByText("Record what you completed")).toBeInTheDocument();

      const submitReportBtn = screen.getByRole("button", {
        name: "Record user-reported submission",
      });
      expect(submitReportBtn).toBeDisabled();

      const receiptInput = screen.getByLabelText(
        "Receipt reference · optional",
      );
      await userEvent.type(receiptInput, "APP-REF-998877");

      const confirmCheckbox = screen.getByLabelText(
        "I submitted this application on the official website.",
      );
      await userEvent.click(confirmCheckbox);

      expect(submitReportBtn).toBeEnabled();
      await userEvent.click(submitReportBtn);

      await waitFor(() => {
        expect(post).toHaveBeenCalledWith(
          `application-packets/${approvedPacket.id}/report-submission`,
          expect.objectContaining({
            expected_revision: approvedPacket.revision,
            human_confirmed: true,
            receipt_reference: "APP-REF-998877",
          }),
        );
      });
    });

    it("distinguishes approved answer provenance badges clearly", async () => {
      const packetWithProvenance: typeof mockPacket = {
        ...mockPacket,
        fields: [
          {
            ...mockPacket.fields[0],
            id: "f-owner",
            question: "Owner approved question",
            provenance: {
              origin: "user_provided",
              source: "owner_answer" as any,
              resolver: "deterministic",
              evidence_references: [],
            },
          },
          {
            ...mockPacket.fields[0],
            id: "f-reused",
            question: "Reused question",
            provenance: {
              origin: "user_provided",
              source: "approved_answer",
              resolver: "deterministic",
              evidence_references: [],
            },
          },
          {
            ...mockPacket.fields[0],
            id: "f-profile",
            question: "Profile fact question",
            provenance: {
              origin: "user_provided",
              source: "profile_fact" as any,
              resolver: "deterministic",
              evidence_references: [],
            },
          },
          {
            ...mockPacket.fields[0],
            id: "f-project",
            question: "Project question",
            provenance: {
              origin: "user_provided",
              source: "approved_project" as any,
              resolver: "deterministic",
              evidence_references: [],
            },
          },
        ],
      };
      vi.mocked(api).mockImplementation((path: string) => {
        if (path === `application-packets/${mockPacket.id}`) {
          return Promise.resolve(packetWithProvenance);
        }
        if (path === `application-packets/${mockPacket.id}/events`) {
          return Promise.resolve([]);
        }
        if (path === "browser-applications/policy") {
          return Promise.resolve({ origins: [], digest: "test-digest" });
        }
        return Promise.reject(new Error(`Unhandled GET path: ${path}`));
      });
      renderWithClient(<ApplicationDetail id={mockPacket.id} />);

      expect(
        await screen.findByText("Human-approved (exact context)"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Reused from approved answers"),
      ).toBeInTheDocument();
      expect(screen.getByText("Verified profile fact")).toBeInTheDocument();
      expect(screen.getByText("Approved project evidence")).toBeInTheDocument();
    });
  });

  describe("Security and safe rendering", () => {
    it("sanitizes unsafe external URL schemes like javascript:", () => {
      expect(externalUrl("javascript:alert(1)")).toBeUndefined();
      expect(externalUrl("data:text/html,<script>")).toBeUndefined();
      expect(externalUrl("http://unencrypted.example.com")).toBeUndefined();
      const fictionalUserinfo = new URL("https://example.com");
      fictionalUserinfo.username = "fixture-user";
      fictionalUserinfo.password = "fixture-password"; // pragma: allowlist secret — fictional URL parser fixture only
      expect(externalUrl(fictionalUserinfo.href)).toBeUndefined();
      expect(externalUrl("https://safe.example.com/apply")).toBe(
        "https://safe.example.com/apply",
      );
    });
  });
});

it.each(["pending", "sent", "delivery_unknown"])(
  "saves the displayed %s packet question revision without an implicit resume",
  async (state) => {
    const current = { ...mockPacket, revision: 7 };
    const question = {
      id: "q-1",
      packet_id: current.id,
      packet_revision: 7,
      execution_id: "execution-1",
      question: "Willing to relocate?",
      state,
      answer: null,
      employer: "Acme",
      role: "Engineer",
      answer_type: "choice",
      options: ["Yes", "No"],
      expires_at: "2099-01-01T00:00:00Z",
    };
    let answered = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === `application-packets/${current.id}`) return current;
      if (path.endsWith("/events")) return [];
      if (path === "execution/questions") return answered ? [] : [question];
      if (path === "browser-applications/policy")
        return { origins: [], digest: "test" };
      throw Error(path);
    });
    vi.mocked(post).mockImplementation(async () => {
      answered = true;
      return {};
    });
    renderWithClient(<ApplicationDetail id={current.id} />);
    await screen.findByText("Willing to relocate?");
    await userEvent.selectOptions(
      screen.getByLabelText("Your verified answer"),
      "Yes",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Submit Answer from Dashboard" }),
    );
    expect(
      await screen.findByText(
        "Answer saved. Review and approve the updated packet before filling.",
      ),
    ).toBeVisible();
    expect(post).toHaveBeenCalledWith("execution/questions/q-1/answer", {
      answer: "Yes",
      expected_revision: 7,
    });
    expect(
      vi.mocked(post).mock.calls.some(([path]) => path.endsWith("/control")),
    ).toBe(false);
    expect(patch).not.toHaveBeenCalled();
  },
);
