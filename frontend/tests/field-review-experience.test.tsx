import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApplicationDetail,
  getFieldReviewStatus,
} from "@/features/applications";
import { api, patch, post, type Schema } from "@/lib/api";

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

const mockFieldBase: Schema<"PacketField"> = {
  id: "aaaaaaaa-1111-4111-8111-111111111111",
  question: "How many years of Python experience do you have?",
  category: "experience",
  field_type: "text",
  required: true,
  max_characters: 500,
  max_words: null,
  writing_style: "professional",
  validation_status: "draft_ready",
  review_status: "pending",
  proposed_answer: "5 years",
  effective_answer: "5 years",
  answer_revision: 1,
  requires_review: true,
  provenance: {
    origin: "user_provided",
    source: "candidate_profile",
    resolver: "deterministic",
  },
};

const mockPacket: Schema<"PacketRead"> = {
  id: "11111111-2222-3333-4444-555555555555",
  platform: "greenhouse",
  lifecycle_state: "ready_for_review",
  tracking_state: "not_applied",
  revision: 2,
  approved_revision: null,
  review_status: "pending",
  submission_mode: "manual_handoff",
  created_at: "2026-10-25T10:00:00Z",
  updated_at: "2026-10-26T12:00:00Z",
  job_id: "22222222-3333-4444-5555-666666666666",
  candidate_profile_version: 3,
  snapshot: {
    preparation_supported: true,
    job_title: "Senior Backend Engineer",
    company_name: "Acme Corp",
    source_platform: "greenhouse",
    original_job_url: "https://careers.acme.example/jobs/1",
    context_digest: "digest-1",
    destination: {
      application_url: "https://careers.acme.example/apply/1",
      kind: "employer_external",
      valid: true,
      source_confidence: "source_consistent",
      warnings: [],
    },
    resume: {
      selected: {
        resource_id: "res-1",
        label: "Backend Resume 2026",
        url: "https://storage.example.org/resumes/backend.pdf",
        confirmed: true,
        primary: true,
        resource_version: "v1",
      },
      alternatives: [],
      reason: "Confirmed primary resume",
      upload_status: "manual_resume_upload_required",
    },
    warnings: [],
  },
  readiness: {
    state: "needs_review",
    blockers: [],
    manual_steps: [],
    warnings: [],
    stale: false,
  },
  fields: [
    mockFieldBase,
    {
      ...mockFieldBase,
      id: "aaaaaaaa-2222-4222-8222-222222222222",
      question: "Upload your resume",
      category: "resume_upload",
      field_type: "file",
      validation_status: "file_upload_required",
      effective_answer: null,
    },
    {
      ...mockFieldBase,
      id: "aaaaaaaa-3333-4333-8333-333333333333",
      question: "Notice period",
      category: "notice_period",
      field_type: "text",
      validation_status: "needs_input",
      effective_answer: null,
    },
  ],
};

function renderDetail(id: string = mockPacket.id) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ApplicationDetail id={id} />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

describe("Field Review Status Logic (getFieldReviewStatus)", () => {
  it("identifies Failed Validation when answers exceed character limits", () => {
    const result = getFieldReviewStatus({
      field: mockFieldBase,
      isReviewed: false,
      exceedsLimit: true,
    });
    expect(result.status).toBe("Failed Validation");
    expect(result.tone).toBe("red");
    expect(result.nextAction).toMatch(/Shorten answer/i);
  });

  it("identifies Challenge Required for a security challenge field", () => {
    const result = getFieldReviewStatus({
      field: {
        ...mockFieldBase,
        category: "captcha" as Schema<"PacketField">["category"],
      },
      isReviewed: false,
    });
    expect(result.status).toBe("Challenge Required");
    expect(result.tone).toBe("red");
    expect(result.nextAction).toMatch(/security challenge/i);
  });

  it("identifies Manual Only for file uploads and resume uploads", () => {
    const result = getFieldReviewStatus({
      field: {
        ...mockFieldBase,
        field_type: "file",
        category: "resume_upload",
        validation_status: "file_upload_required",
      },
      isReviewed: false,
    });
    expect(result.status).toBe("Manual Only");
    expect(result.tone).toBe("neutral");
    expect(result.nextAction).toMatch(/Download approved resume PDF/i);
  });

  it("identifies Needs Answer when required fields lack an effective answer", () => {
    const result = getFieldReviewStatus({
      field: {
        ...mockFieldBase,
        effective_answer: null,
        validation_status: "needs_input",
      },
      isReviewed: false,
    });
    expect(result.status).toBe("Needs Answer");
    expect(result.tone).toBe("amber");
    expect(result.nextAction).toMatch(
      /Provide an answer below or resolve it in Needs Input/i,
    );
  });

  it("identifies Ready when answer is valid and reviewed", () => {
    const result = getFieldReviewStatus({
      field: mockFieldBase,
      isReviewed: true,
      isDirty: false,
    });
    expect(result.status).toBe("Ready");
    expect(result.tone).toBe("green");
    expect(result.nextAction).toMatch(/Ready for manual handoff/i);
  });

  it("identifies Pending Review when answer is valid but awaiting owner review", () => {
    const result = getFieldReviewStatus({
      field: mockFieldBase,
      isReviewed: false,
    });
    expect(result.status).toBe("Pending Review");
    expect(result.tone).toBe("amber");
    expect(result.nextAction).toMatch(
      /Review proposed answer and mark reviewed/i,
    );
  });
});

describe("ApplicationDetail field-by-field review experience UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === `application-packets/${mockPacket.id}`) {
        return Promise.resolve(mockPacket);
      }
      if (path === `application-packets/${mockPacket.id}/events`) {
        return Promise.resolve([
          {
            id: "evt-1",
            application_id: mockPacket.id,
            packet_revision: 2,
            event_type: "packet_prepared",
            created_at: "2026-10-25T10:00:00Z",
          },
        ]);
      }
      return Promise.reject(new Error(`Unhandled GET path: ${path}`));
    });
  });

  it("displays the structured review layout: Field -> Proposed Answer -> Evidence -> Status -> Next Action", async () => {
    renderDetail();

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Senior Backend Engineer",
      }),
    ).toBeInTheDocument();

    const fieldBlocks = screen.getAllByText("Field");
    expect(fieldBlocks.length).toBeGreaterThanOrEqual(1);

    const proposedAnswerBlocks = screen.getAllByText("Proposed Answer");
    expect(proposedAnswerBlocks.length).toBeGreaterThanOrEqual(1);

    const evidenceBlocks = screen.getAllByText("Evidence & Provenance");
    expect(evidenceBlocks.length).toBeGreaterThanOrEqual(1);

    const statusBlocks = screen.getAllByText("Status");
    expect(statusBlocks.length).toBeGreaterThanOrEqual(1);

    const nextActionBlocks = screen.getAllByText("Next Action");
    expect(nextActionBlocks.length).toBeGreaterThanOrEqual(1);
  });

  it("shows the required manual actions panel", async () => {
    renderDetail();

    const manualPanel = await screen.findByRole("region", {
      name: "Required Manual Actions",
    });
    expect(within(manualPanel).getByText(/Resume upload:/)).toBeInTheDocument();
    expect(
      within(manualPanel).getByText(/Security challenge \/ CAPTCHA:/),
    ).toBeInTheDocument();
    expect(
      within(manualPanel).getByText(/Manual-only fields:/),
    ).toBeInTheDocument();
    expect(
      within(manualPanel).getByText(/Portal submission:/),
    ).toBeInTheDocument();
  });

  it("displays the prominent next action callout banner at the top", async () => {
    renderDetail();

    const nextActionCallout = await screen.findByRole("region", {
      name: "Next Action Guidance",
    });
    expect(
      within(nextActionCallout).getByText("NEXT ACTION"),
    ).toBeInTheDocument();
    expect(
      within(nextActionCallout).getByText(
        "Answer the missing questions, then review the updated packet.",
      ),
    ).toBeInTheDocument();
  });

  it("lists packet events and the last successful activity in the history", async () => {
    renderDetail();

    await screen.findByRole("heading", {
      level: 1,
      name: "Senior Backend Engineer",
    });

    const history = await screen.findByText("packet prepared");
    expect(history).toBeInTheDocument();
    expect(screen.getByText(/Last successful activity:/)).toBeInTheDocument();
  });

  it("preserves a dirty answer across server answer and packet revision changes", async () => {
    const { client } = renderDetail();
    await screen.findByRole("heading", {
      level: 1,
      name: "Senior Backend Engineer",
    });
    const input = screen.getAllByRole("textbox")[0];
    await userEvent.clear(input);
    await userEvent.type(input, "Unsaved owner draft");
    await act(async () => {
      client.setQueryData(["packet", mockPacket.id], {
        ...mockPacket,
        revision: 3,
        fields: mockPacket.fields.map((field, index) =>
          index === 0
            ? {
                ...field,
                effective_answer: "Server changed answer",
                answer_revision: 2,
              }
            : field,
        ),
      });
    });
    expect(input).toHaveValue("Unsaved owner draft");
    expect(
      screen.getByRole("button", { name: "Approve current packet" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/You have unsaved answer edits/),
    ).toBeInTheDocument();
  });

  it("keeps edits typed while a save request is in flight", async () => {
    let resolveSave!: (value: unknown) => void;
    const pending = new Promise((resolve) => {
      resolveSave = resolve;
    });
    vi.mocked(patch).mockReturnValue(pending);
    renderDetail();
    await screen.findByRole("heading", {
      level: 1,
      name: "Senior Backend Engineer",
    });
    const input = screen.getAllByRole("textbox")[0];
    await userEvent.clear(input);
    await userEvent.type(input, "First saved draft");
    await userEvent.click(
      screen.getAllByRole("button", { name: "Save answer" })[0],
    );
    await waitFor(() => expect(patch).toHaveBeenCalled());
    await userEvent.type(input, " and later edits");
    const savedPacket = {
      ...mockPacket,
      revision: 3,
      fields: mockPacket.fields.map((field, index) =>
        index === 0
          ? {
              ...field,
              effective_answer: "First saved draft",
              answer_revision: 2,
            }
          : field,
      ),
    };
    const previousApi = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation((path, options) =>
      path === `application-packets/${mockPacket.id}`
        ? Promise.resolve(savedPacket)
        : previousApi(path, options),
    );
    await act(async () => {
      resolveSave(savedPacket);
      await pending;
    });
    await waitFor(() =>
      expect(screen.getByText(/· Revision 3$/)).toBeInTheDocument(),
    );
    expect(input).toHaveValue("First saved draft and later edits");
    expect(
      screen.getByText(/You have unsaved answer edits/),
    ).toBeInTheDocument();
  });
});
