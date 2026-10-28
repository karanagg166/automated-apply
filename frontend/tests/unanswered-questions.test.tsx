import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, patch, post } from "@/lib/api";
import {
  UnansweredQuestionsQueue,
  type MissingInputItem,
  type MissingHistoryEntry,
} from "@/features/unanswered-questions";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}));

const fictionalProfile = {
  id: "profile-1001",
  version: 3,
  full_name: "Aarav Patel",
  email: "aarav.patel@example.org",
};

const fictionalMissingItems: MissingInputItem[] = [
  {
    id: "missing-101",
    candidate_profile_id: "profile-1001",
    question:
      "Have you led Kubernetes cluster migrations across multi-cloud environments?",
    question_category: "technical_experience",
    job_id: "job-501",
    company_name: "ScaleMatrix India",
    packet_id: "packet-801",
    missing_information: [
      "Specific cloud providers involved",
      "Migration strategy or downtime metrics",
    ],
    reason:
      "Candidate profile lists Kubernetes but lacks evidence of multi-cloud migration experience.",
    required_input_type: "evidence",
    created_at: "2026-03-01T12:00:00Z",
    status: "needs_input",
    effective_status: "needs_input",
    job_description: null,
    draft_id: null,
    stale: false,
    ever_approved: false,
    version: 1,
    profile_version: 3,
    context_digest: "scale-matrix-k8s-migration",
    answer: null,
    evidence_note: "",
    href: "/needs-input/missing-101",
  },
  {
    id: "missing-102",
    candidate_profile_id: "profile-1001",
    question: "What is your expected CTC in INR for this onsite role in Pune?",
    question_category: "compensation",
    job_id: "job-502",
    company_name: "FinPulse Labs",
    packet_id: "packet-802",
    missing_information: ["Pune onsite expected compensation"],
    reason:
      "Compensation fact exists only for remote preference; onsite adjustment required.",
    required_input_type: "number",
    created_at: "2026-03-02T09:30:00Z",
    status: "draft",
    effective_status: "draft",
    job_description: null,
    draft_id: null,
    stale: false,
    ever_approved: false,
    version: 2,
    profile_version: 3,
    context_digest: "finpulse-pune-ctc",
    answer: "My expected CTC for onsite in Pune is 34 LPA.",
    evidence_note: "Aligned with current market rates for 6 YOE.",
    href: "/needs-input/missing-102",
  },
  {
    id: "missing-103",
    candidate_profile_id: "profile-1001",
    question: "What is your required notice period?",
    question_category: "short_text",
    job_id: "job-503",
    company_name: "CloudVibe",
    packet_id: "packet-803",
    missing_information: [],
    reason: "Profile notice period was updated from 30 days to 15 days.",
    required_input_type: "text",
    created_at: "2026-02-20T10:00:00Z",
    status: "approved",
    effective_status: "review_required",
    job_description: null,
    draft_id: null,
    version: 3,
    profile_version: 2,
    context_digest: "cloudvibe-notice-period",
    answer: "My notice period is 30 days.",
    evidence_note: "Previous employer contract",
    stale: true,
    ever_approved: true,
    href: "/needs-input/missing-103",
  },
];

const fictionalHistory: MissingHistoryEntry[] = [
  {
    request_id: "missing-101",
    candidate_profile_id: "profile-1001",
    operation: "edited",
    version: 2,
    previous: {},
    recorded_at: "2026-03-01T12:00:00Z",
  },
  {
    request_id: "missing-101",
    candidate_profile_id: "profile-1001",
    operation: "approved_exact_context",
    version: 3,
    previous: { answer: null },
    recorded_at: "2026-03-01T14:30:00Z",
  },
];

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <UnansweredQuestionsQueue />
    </QueryClientProvider>,
  );
}

describe("Unanswered Questions Queue ('Needs your input')", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "profile") {
        return fictionalProfile as any;
      }
      if (path === "application-answers/missing") {
        return {
          requests: fictionalMissingItems,
          offset: 0,
          limit: 50,
        } as any;
      }
      if (path.includes("/history")) {
        return { history: fictionalHistory } as any;
      }
      return {} as any;
    });
  });

  it("lists questions needing input with company name, missing facts, and stop reasons", async () => {
    mount();

    expect(
      await screen.findByText(
        "Have you led Kubernetes cluster migrations across multi-cloud environments?",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/ScaleMatrix India/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Candidate profile lists Kubernetes but lacks evidence/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Specific cloud providers involved"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Migration strategy or downtime metrics"),
    ).toBeInTheDocument();

    // Summary counts
    expect(screen.getByText("NEEDS INPUT")).toBeInTheDocument();
    expect(screen.getByText("DRAFTS IN PROGRESS")).toBeInTheDocument();
    expect(screen.getByText("REVIEW REQUIRED")).toBeInTheDocument();
  });

  it("filters questions by status tabs correctly", async () => {
    mount();

    await screen.findByText(
      "Have you led Kubernetes cluster migrations across multi-cloud environments?",
    );

    // Switch to 'Drafts' tab
    const draftTab = screen.getByRole("tab", { name: /Drafts \(1\)/i });
    await userEvent.click(draftTab);

    // Only missing-102 should be visible
    expect(
      screen.getByText(
        "What is your expected CTC in INR for this onsite role in Pune?",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Have you led Kubernetes cluster migrations across multi-cloud environments?",
      ),
    ).toBeNull();
  });

  it("opens question in resolution modal and saves answer draft", async () => {
    const updatedDraft: MissingInputItem = {
      ...fictionalMissingItems[0],
      status: "draft",
      answer:
        "Migrated 12 microservices from AWS EKS to GCP GKE with zero downtime using DNS blue/green.",
      evidence_note: "Documented in 2024 architecture case study.",
      version: 2,
    };
    vi.mocked(patch).mockResolvedValue(updatedDraft);

    mount();

    await screen.findByText(
      "Have you led Kubernetes cluster migrations across multi-cloud environments?",
    );

    // Click Supply truthful answer on first item
    const actionBtns = screen.getAllByRole("button", {
      name: /Supply truthful answer/i,
    });
    await userEvent.click(actionBtns[0]);

    // Modal opens
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      within(dialog).getByRole("heading", {
        name: /Have you led Kubernetes cluster migrations/i,
      }),
    ).toBeInTheDocument();

    // Fill in answer and evidence note
    const answerInput = within(dialog).getByLabelText(/Your Truthful Answer/i);
    await userEvent.type(
      answerInput,
      "Migrated 12 microservices from AWS EKS to GCP GKE with zero downtime using DNS blue/green.",
    );

    const evidenceInput = within(dialog).getByLabelText(
      /Supporting Evidence \/ Project Context/i,
    );
    await userEvent.type(
      evidenceInput,
      "Documented in 2024 architecture case study.",
    );

    // Save as draft
    const saveDraftBtn = within(dialog).getByRole("button", {
      name: /Save as draft/i,
    });
    await userEvent.click(saveDraftBtn);

    expect(patch).toHaveBeenCalledWith(
      "application-answers/missing/missing-101",
      {
        expected_version: 1,
        answer:
          "Migrated 12 microservices from AWS EKS to GCP GKE with zero downtime using DNS blue/green.",
        evidence_note: "Documented in 2024 architecture case study.",
      },
    );

    // Success notice is displayed
    expect(await screen.findByText(/Draft answer saved/i)).toBeInTheDocument();
  });

  it("requires explicit factual confirmation before allowing answer approval", async () => {
    const approvedItem: MissingInputItem = {
      ...fictionalMissingItems[1],
      status: "approved",
      version: 3,
    };
    vi.mocked(post).mockResolvedValue(approvedItem);

    mount();

    await screen.findByText(
      "What is your expected CTC in INR for this onsite role in Pune?",
    );

    // Click Supply truthful answer on the draft item (item 102)
    const actionBtns = screen.getAllByRole("button", {
      name: /Supply truthful answer/i,
    });
    await userEvent.click(actionBtns[1]);

    const dialog = await screen.findByRole("dialog");

    // Approval button should be disabled initially (factualConfirmation is false)
    const approveBtn = within(dialog).getByRole("button", {
      name: /Approve answer for this context/i,
    });
    expect(approveBtn).toBeDisabled();

    // Check factual confirmation checkbox
    const confirmationCheckbox = within(dialog).getByLabelText(
      /I confirm this answer is completely truthful, accurate, and supported by personal knowledge and evidence/i,
    );
    await userEvent.click(confirmationCheckbox);

    // Approval button is now enabled
    expect(approveBtn).toBeEnabled();

    // Click approve
    await userEvent.click(approveBtn);

    expect(post).toHaveBeenCalledWith(
      "application-answers/missing/missing-102/approve",
      {
        expected_version: 2,
        expected_profile_version: 3,
        factual_confirmation: true,
      },
    );

    expect(
      await screen.findByText(
        /Saved answer approved for this exact question and context/i,
      ),
    ).toBeInTheDocument();
  });

  it("allows inspecting revision history for an answered item", async () => {
    mount();

    await screen.findByText(
      "Have you led Kubernetes cluster migrations across multi-cloud environments?",
    );

    // Open item
    const actionBtns = screen.getAllByRole("button", {
      name: /Supply truthful answer/i,
    });
    await userEvent.click(actionBtns[0]);

    const dialog = await screen.findByRole("dialog");

    // Click View revision history
    const historyBtn = within(dialog).getByRole("button", {
      name: /View revision history/i,
    });
    await userEvent.click(historyBtn);

    // Revision history entries are shown
    expect(
      await within(dialog).findByText(/v2 \(edited\)/i),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/v3 \(approved exact context\)/i),
    ).toBeInTheDocument();
  });

  it("displays prominent stale answer warning when candidate profile facts changed", async () => {
    mount();

    // Item 103 has stale=true and review_required status
    expect(
      await screen.findByText("Review Required (Stale Profile)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Your candidate profile facts have changed since this answer was approved/i,
      ),
    ).toBeInTheDocument();
  });

  it("displays an honest unavailable state when Codex backend contract is pending (404)", async () => {
    const error404 = new Error("Not Found");
    (error404 as any).status = 404;

    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "profile") return fictionalProfile as any;
      if (path === "application-answers/missing") throw error404;
      return {} as any;
    });

    mount();

    expect(
      await screen.findByText("Question queue unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The saved question queue is unavailable/i),
    ).toBeInTheDocument();
  });

  it("blocks approval of unsaved edits even after a factual checkbox was checked", async () => {
    vi.mocked(api).mockImplementation(
      async (path) =>
        (path === "profile"
          ? fictionalProfile
          : {
              requests: [fictionalMissingItems[1]],
              offset: 0,
              limit: 25,
            }) as any,
    );
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Supply truthful answer" }),
    );
    const dialog = await screen.findByRole("dialog");
    const confirmation = within(dialog).getByRole("checkbox");
    const approve = within(dialog).getByRole("button", {
      name: "Approve answer for this context",
    });
    await userEvent.click(confirmation);
    expect(approve).toBeEnabled();
    await userEvent.type(
      within(dialog).getByLabelText("Your Truthful Answer"),
      " Unsaved correction.",
    );
    expect(confirmation).not.toBeChecked();
    await userEvent.click(confirmation);
    expect(approve).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("uses effective_status to move stale approvals out of the approved filter", async () => {
    vi.mocked(api).mockImplementation(
      async (path) =>
        (path === "profile"
          ? fictionalProfile
          : {
              requests: [
                {
                  ...fictionalMissingItems[0],
                  stale: true,
                  effective_status: "needs_input",
                },
                {
                  ...fictionalMissingItems[1],
                  status: "approved",
                  effective_status: "review_required",
                  stale: true,
                  ever_approved: true,
                },
              ],
              offset: 0,
              limit: 25,
            }) as any,
    );
    mount();
    await screen.findByText(fictionalMissingItems[1].question);
    await userEvent.click(screen.getByRole("tab", { name: "Approved (0)" }));
    expect(
      screen.queryByRole("heading", {
        name: fictionalMissingItems[1].question,
      }),
    ).toBeNull();
    await userEvent.click(
      screen.getByRole("tab", { name: "Review required (1)" }),
    );
    expect(
      screen.getByRole("heading", { name: fictionalMissingItems[1].question }),
    ).toBeInTheDocument();
  });

  it("filters questions by search query and company filter", async () => {
    mount();
    await screen.findByText(fictionalMissingItems[0].question);

    // Search by keyword
    const searchInput = screen.getByLabelText("Search questions");
    await userEvent.type(searchInput, "Kubernetes");
    expect(
      screen.getByText(fictionalMissingItems[0].question),
    ).toBeInTheDocument();
    expect(screen.queryByText(fictionalMissingItems[1].question)).toBeNull();

    // Clear search and filter by company
    await userEvent.clear(searchInput);
    fireEvent.change(searchInput, { target: { value: "" } });
    const companyInput = screen.getByLabelText("Filter by company");
    fireEvent.change(companyInput, { target: { value: "FinPulse Labs" } });
    expect(
      screen.getByText(fictionalMissingItems[1].question),
    ).toBeInTheDocument();
    expect(screen.queryByText(fictionalMissingItems[0].question)).toBeNull();
  });

  it("displays duplicate question badge when the same question appears across applications", async () => {
    const duplicateItem: MissingInputItem = {
      ...fictionalMissingItems[0],
      id: "missing-104",
      company_name: "FinPulse Labs",
    };
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "profile") return fictionalProfile as any;
      if (path === "application-answers/missing")
        return {
          requests: [fictionalMissingItems[0], duplicateItem],
          offset: 0,
          limit: 25,
        } as any;
      return {} as any;
    });
    mount();
    const badges = await screen.findAllByText(/Seen in 2 applications/i);
    expect(badges.length).toBe(2);
  });

  it("prompts user before closing modal when unsaved changes exist", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    mount();
    await userEvent.click(
      (
        await screen.findAllByRole("button", {
          name: /Supply truthful answer/i,
        })
      )[0],
    );
    const dialog = await screen.findByRole("dialog");

    // Type unsaved draft text
    const answerInput = within(dialog).getByLabelText(/Your Truthful Answer/i);
    await userEvent.type(answerInput, "Some draft text");

    // Attempt to close
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close" }),
    );

    // Confirmation was requested and since it returned false, modal stays open
    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("unsaved draft changes"),
    );
    expect(dialog).toBeInTheDocument();

    // Now allow closing
    confirmSpy.mockReturnValue(true);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    confirmSpy.mockRestore();
  });

  it("provides retry button when saving draft fails", async () => {
    vi.mocked(patch).mockRejectedValueOnce(
      new Error("Network timeout saving draft"),
    );
    mount();
    await userEvent.click(
      (
        await screen.findAllByRole("button", {
          name: /Supply truthful answer/i,
        })
      )[0],
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(
      within(dialog).getByLabelText(/Your Truthful Answer/i),
      "A valid answer",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: /Save as draft/i }),
    );

    // Error is shown with Retry button
    const retryBtn = await within(dialog).findByRole("button", {
      name: /Retry saving draft/i,
    });
    expect(retryBtn).toBeInTheDocument();

    // Clicking retry re-triggers the mutation
    vi.mocked(patch).mockResolvedValueOnce({
      ...fictionalMissingItems[0],
      answer: "A valid answer",
      status: "draft",
    });
    await userEvent.click(retryBtn);
    expect(patch).toHaveBeenCalledTimes(2);
  });
});
