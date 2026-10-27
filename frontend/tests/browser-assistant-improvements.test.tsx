import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
import { BrowserAssistant } from "@/features/browser-assistant";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const fictionalPacket: Schema<"PacketRead"> = {
  id: "packet-1001",
  job_id: "job-2001",
  platform: "greenhouse",
  lifecycle_state: "ready_for_review",
  tracking_state: "not_applied",
  revision: 2,
  approved_revision: null,
  review_status: "pending",
  submission_mode: "manual_handoff",
  created_at: "2026-03-01T10:00:00Z",
  updated_at: "2026-03-01T10:00:00Z",
  fields: [],
  readiness: {
    state: "needs_review",
    blockers: [],
    manual_steps: [],
    warnings: [],
    stale: false,
  },
  snapshot: {
    preparation_supported: true,
    job_title: "Staff Platform Engineer",
    company_name: "FinPulse Labs",
    original_job_url: "https://finpulse.example/jobs/platform",
    source_platform: "greenhouse",
    destination: {
      application_url: "https://boards.greenhouse.io/finpulse/jobs/987654",
      kind: "employer_external",
      valid: true,
      source_confidence: "source_consistent",
    },
    resume: {
      reason: "Matched",
      upload_status: "manual_resume_upload_required",
      selected: {
        resource_id: "resume-1",
        label: "Platform_Engineer_2026.pdf",
        url: "https://storage.example.org/resumes/platform.pdf",
        confirmed: true,
        primary: true,
        resource_version: "1",
      },
    },
    context_digest: "digest-1",
  },
};

const fictionalStatusConnected = {
  packet: fictionalPacket,
  connected: true,
  manual: false,
  page_review_required: false,
  in_page_network_isolation: false,
  cancellation_pending: false,
  recovery: null,
  automated_submission_enabled: false,
  owner_consent_available: true,
  opportunity_context_available: true,
  company_source_urls: ["https://finpulse.example"],
  execution: null,
  analysis: {
    diagnostic: "application_form_ready",
    page_context: {
      url: "https://boards.greenhouse.io/finpulse/jobs/987654",
      title: "FinPulse Labs - Staff Platform Engineer",
      heading: "Apply for this Job",
    },
    warnings: ["Custom CAPTCHA widget detected on submission screen."],
    fields: [
      {
        field_id: "field-name",
        question: "Full Name",
        supported: true,
        kind: "text",
        manual_reason: null,
      },
      {
        field_id: "field-resume",
        question: "Resume Upload",
        supported: true,
        kind: "file",
        manual_reason: null,
      },
      {
        field_id: "field-captcha",
        question: "Cloudflare Turnstile Verification",
        supported: false,
        kind: "custom_widget",
        manual_reason:
          "Automated filling of security CAPTCHAs is strictly prohibited.",
      },
      {
        field_id: "field-q1",
        question: "Multi-cloud Kubernetes migration experience",
        supported: true,
        kind: "textarea",
        manual_reason: null,
      },
    ],
    validation: [
      {
        field_id: "field-name",
        complete: true,
        reason: null,
      },
      {
        field_id: "field-resume",
        complete: true,
        reason: null,
      },
      {
        field_id: "field-q1",
        complete: false,
        reason:
          "Missing answer: candidate knowledge does not contain confirmed multi-cloud metrics.",
      },
    ],
  },
};

function mount(packet = fictionalPacket) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <BrowserAssistant packet={packet} />
    </QueryClientProvider>,
  );
}

describe("Browser Assistant UI Improvements", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "browser-applications/policy") {
        return {
          origins: ["https://boards.greenhouse.io"],
          digest: "policy-hash-123",
        } as any;
      }
      if (path === `browser-applications/${fictionalPacket.id}`) {
        return fictionalStatusConnected as any;
      }
      return {} as any;
    });
  });

  it("displays application context and readiness indicators with PDF resume confirmation", async () => {
    mount();

    expect(
      await screen.findByText("Staff Platform Engineer"),
    ).toBeInTheDocument();
    expect(screen.getByText("FinPulse Labs")).toBeInTheDocument();
    expect(
      screen.getByText("https://boards.greenhouse.io/finpulse/jobs/987654"),
    ).toBeInTheDocument();

    // Selected resume status
    expect(screen.getByText("Platform_Engineer_2026.pdf")).toBeInTheDocument();
    expect(screen.getByText("Selection confirmed")).toBeInTheDocument();

    // Readiness indicators
    expect(screen.getByText("DESTINATION READY")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("RESUME CONFIRMED")).toBeInTheDocument();
    expect(screen.getByText("Resume selection confirmed")).toBeInTheDocument();
    expect(screen.getByText("SUBMISSION MODE")).toBeInTheDocument();
    expect(screen.getByText("Manual review & handoff")).toBeInTheDocument();
  });

  it("prominently displays non-submission guarantee notices and manual handoff instructions", async () => {
    mount();

    expect(
      await screen.findByText(/Manual Handoff & Non-Submission Guarantee:/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/It NEVER submits your application to the employer/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /When filling finishes, inspect every field on the official employer website and submit manually/i,
      ),
    ).toBeInTheDocument();
  });

  it("distinguishes supported vs unsupported fields requiring manual entry", async () => {
    mount();

    // Click 'Get status' to load analysis state
    const statusBtn = screen.getByRole("button", { name: "Get status" });
    await userEvent.click(statusBtn);

    expect(
      await screen.findByText(
        "Observed page: Apply for this Job · https://boards.greenhouse.io/finpulse/jobs/987654",
      ),
    ).toBeInTheDocument();

    // Unsupported fields section
    expect(
      screen.getByText("Unsupported fields requiring manual entry"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cloudflare Turnstile Verification"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        /Automated filling of security CAPTCHAs is strictly prohibited/i,
      ).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("links to '/needs-input' queue when incomplete or missing questions are detected", async () => {
    mount();

    // Load status with analysis
    await userEvent.click(screen.getByRole("button", { name: "Get status" }));

    // Unfilled questions section is visible
    expect(
      await screen.findByText(
        "Unfilled or incomplete questions needing attention",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Missing answer: candidate knowledge does not contain confirmed multi-cloud metrics/i,
      ),
    ).toBeInTheDocument();

    // Dedicated button to open 'Needs your input' queue
    const linkBtn = screen.getByRole("link", {
      name: /Open 'Needs your input' queue/i,
    });
    expect(linkBtn).toBeInTheDocument();
    expect(linkBtn).toHaveAttribute("href", "/needs-input");
  });
});

it("requires a valid destination and never equates resume selection with PDF verification", async () => {
  vi.mocked(api).mockResolvedValue({
    origins: [],
    digest: "fictional-policy",
  } as any);
  mount({
    ...fictionalPacket,
    snapshot: {
      ...fictionalPacket.snapshot,
      destination: { ...fictionalPacket.snapshot.destination, valid: false },
    },
  } as any);
  expect(screen.getByText("Needs destination review")).toBeInTheDocument();
  expect(screen.queryByText("Configured")).toBeNull();
  expect(screen.queryByText("Confirmed & Verified")).toBeNull();
  expect(screen.queryByText("Ready (PDF verified)")).toBeNull();
});
