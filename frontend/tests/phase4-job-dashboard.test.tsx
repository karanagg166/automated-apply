import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Jobs, type Job } from "@/features/jobs";
import {
  ConnectedEmails,
  type ReadAccount,
  type JobEmailEvidence,
} from "@/features/connected-emails";
import { BrowserAssistant } from "@/features/browser-assistant";
import { CandidateKnowledge } from "@/features/candidate-knowledge";
import { api, post, type Schema } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/jobs",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const phase4MockJobs: Job[] = [
  {
    id: "00000000-0000-0000-0000-000000000001",
    title: "Senior Fullstack Engineer (India / Remote)",
    company_name: "FinTech India Solutions",
    company_id: "00000000-0000-0000-0000-0000000000c1",
    company_domain: "fintechindia.example.com",
    company_intelligence: {
      team_size: "51-200",
      description: "Next-gen payments infrastructure for emerging markets.",
    },
    location: "Bengaluru, India (Hybrid)",
    country: "India",
    remote_type: "hybrid",
    is_remote: false,
    employment_type: "full_time",
    salary_min: 3000000,
    salary_max: 4200000,
    salary_currency: "INR",
    salary_period: "year",
    skills_required: ["TypeScript", "Next.js", "Python", "FastAPI"],
    match_score: 95,
    match: {
      match_score: 95,
      explanation: "Matches core stack: TypeScript, Next.js, FastAPI",
      matched_skills: ["TypeScript", "FastAPI"],
      missing_skills: ["Kafka"],
    },
    recommended_resume: {
      resource_id: "res-ind-1",
      label: "Karan_Fullstack_Senior_2026.pdf",
      reason:
        "Aligns with Next.js App Router and distributed payment integrations.",
    },
    application_deadline: "2026-12-31T23:59:59Z",
    status: "discovered" as any,
    application_state: null,
    source_platform: "lever",
    source_verification_status: "verified",
    date_posted: "2026-10-25T08:00:00Z",
    last_observed_at: "2026-10-28T09:00:00Z",
    created_at: "2026-10-28T09:00:00Z" as any,
    updated_at: "2026-10-28T09:00:00Z" as any,
    job_url: "https://jobs.lever.co/fintechindia/senior-fullstack",
    application_url:
      "https://jobs.lever.co/fintechindia/senior-fullstack/apply",
    description:
      "We are seeking a Senior Fullstack Engineer to scale our transactional ledger. Requirements: 5+ years building distributed React/Node/Python systems.",
  },
  {
    id: "00000000-0000-0000-0000-000000000002",
    title: "Staff Platform Engineer (100% Remote)",
    company_name: "CloudScale Systems",
    company_id: "00000000-0000-0000-0000-0000000000c2",
    company_domain: "cloudscale.example.com",
    company_intelligence: {
      team_size: "500+",
      description: "Autonomous cloud operations platform.",
    },
    location: "Worldwide (100% Remote)",
    remote_type: "remote",
    is_remote: true,
    employment_type: "full_time",
    salary_min: 160000,
    salary_max: 195000,
    salary_currency: "USD",
    salary_period: "year",
    skills_required: ["Go", "Kubernetes", "PostgreSQL", "Terraform"],
    match_score: 88,
    match: {
      match_score: 88,
      explanation: "Demonstrated infrastructure automation background",
      matched_skills: ["Go", "Kubernetes"],
      missing_skills: ["Rust"],
    },
    recommended_resume: {
      resource_id: "res-plat-1",
      label: "Platform_Architect_Resume.pdf",
      reason:
        "Highlights multi-region Kubernetes and infrastructure orchestration.",
    },
    application_deadline: null,
    status: "shortlisted" as any,
    application_state: null,
    source_platform: "ashby",
    source_verification_status: "verified",
    date_posted: "2026-10-27T12:00:00Z",
    last_observed_at: "2026-10-28T10:00:00Z",
    created_at: "2026-10-28T10:00:00Z" as any,
    updated_at: "2026-10-28T10:00:00Z" as any,
    job_url: "https://jobs.ashbyhq.com/cloudscale/staff-platform",
    application_url: "https://jobs.ashbyhq.com/cloudscale/staff-platform/apply",
    description:
      "Join our platform team to architect resilient distributed control planes.",
  },
];

function createClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

describe("Phase 4: New Job Discovery Experience", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.startsWith("jobs/saved")) {
        return { jobs: phase4MockJobs };
      }
      if (path.startsWith("jobs/search")) {
        return {
          jobs:
            new URLSearchParams(path.split("?")[1]).get("country") === "IN"
              ? phase4MockJobs.filter((job) => job.country === "India")
              : phase4MockJobs,
          total: phase4MockJobs.length,
          page: 1,
          limit: 20,
        };
      }
      return {};
    });
  });

  it("renders new ATS source platform badges and rights attribution truthfully", async () => {
    render(
      <QueryClientProvider client={createClient()}>
        <Jobs />
      </QueryClientProvider>,
    );

    // Initial heading & tab
    expect(
      await screen.findByText("Senior Fullstack Engineer (India / Remote)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Staff Platform Engineer (100% Remote)"),
    ).toBeInTheDocument();

    // Check source platform labels
    expect(screen.getByText("lever")).toBeInTheDocument();
    expect(screen.getByText("ashby")).toBeInTheDocument();
  });

  it("filters jobs by quick regional filter (India / Remote) and employee size", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <Jobs />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Senior Fullstack Engineer (India / Remote)"),
    ).toBeInTheDocument();

    // Filter by India quick badge (starts with 🇮🇳 India)
    const indiaFilterBtn = screen.getByRole("button", {
      name: /^🇮🇳 India/i,
    });
    await user.click(indiaFilterBtn);

    // FinTech India Solutions should remain visible, CloudScale Systems (Worldwide Remote) should be filtered out
    expect(
      screen.getByText("Senior Fullstack Engineer (India / Remote)"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByText("Staff Platform Engineer (100% Remote)"),
      ).not.toBeInTheDocument(),
    );

    // Reset region filter
    await user.click(indiaFilterBtn);
    expect(
      await screen.findByText("Staff Platform Engineer (100% Remote)"),
    ).toBeInTheDocument();
  });

  it("opens Job Preview Modal displaying description, match breakdown, and recommended resume", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <Jobs />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Senior Fullstack Engineer (India / Remote)"),
    ).toBeInTheDocument();

    // Click "Preview" on the first job
    const previewBtns = screen.getAllByRole("button", { name: /^Preview$/i });
    await user.click(previewBtns[0]);

    // Modal opens with job details
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Job Description Preview")).toBeInTheDocument();
    expect(
      screen.getByText(
        /We are seeking a Senior Fullstack Engineer to scale our transactional ledger/i,
      ),
    ).toBeInTheDocument();

    // Match explanation & evidence
    expect(screen.getByText("Candidate Match Analysis")).toBeInTheDocument();
    expect(
      screen.getByText(/Matches core stack: TypeScript, Next.js, FastAPI/i),
    ).toBeInTheDocument();
    expect(screen.getByText("! Kafka")).toBeInTheDocument();

    // Recommended resume
    expect(
      screen.getByText("Resume Recommendation & Readiness"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Karan_Fullstack_Senior_2026.pdf"),
    ).toBeInTheDocument();

    // Application readiness
    expect(screen.getByText("Ready to prepare")).toBeInTheDocument();

    // Close modal via accessible close button
    const closeBtn = screen.getByRole("button", { name: "Close dialog" });
    await user.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});

describe("Phase 4: Gmail Job Inbox Multi-Account & Message Details", () => {
  const account1Id = "11111111-1111-4111-8111-111111111111";
  const account2Id = "22222222-2222-4222-8222-222222222222";
  const evidenceId = "e".repeat(32);

  const mockAccounts: ReadAccount[] = [
    {
      id: account1Id,
      account_email: "primary.jobs@example.com",
      granted_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
      status: "connected",
      permissions: {
        read_metadata: true,
        read_body: false,
        send: false,
        modify: false,
      },
      sync_enabled: true,
      body_access_reviewed: false,
      sync: {
        version: 1,
        status: "ready",
        policy: {
          enabled: true,
          sender_allowlist: [],
          label_allowlist: ["Label_Jobs"],
          query_allowlist: null,
          read_body: false,
          body_purpose: null,
          backfill_days: 7,
          retention_days: 14,
          max_pages: 1,
        },
      },
    },
    {
      id: account2Id,
      account_email: "secondary.alerts@example.com",
      granted_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
      status: "connected",
      permissions: {
        read_metadata: true,
        read_body: false,
        send: false,
        modify: false,
      },
      sync_enabled: true,
      body_access_reviewed: false,
      sync: {
        version: 1,
        status: "ready",
        policy: {
          enabled: true,
          sender_allowlist: [],
          label_allowlist: ["Label_Alerts"],
          query_allowlist: null,
          read_body: false,
          body_purpose: null,
          backfill_days: 7,
          retention_days: 14,
          max_pages: 1,
        },
      },
    },
  ];

  const mockEvidence: JobEmailEvidence[] = [
    {
      id: evidenceId,
      account_id: account1Id,
      message_id: "msg-101",
      thread_id: "thread-101",
      received_at: "2026-10-28T08:00:00Z",
      observed_at: "2026-10-28T08:00:00Z",
      expires_at: "2026-11-10T00:00:00Z",
      verification_status: "requires_review",
      submission_confirmed: false,
      links: ["https://jobs.lever.co/fintechindia/senior-backend-101"],
      signals: ["possible_job_lead", "interview_invitation"],
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "integrations/gmail/accounts") {
        return {
          accounts: mockAccounts,
          workflow: "readonly",
          schema_ready: true,
        } as any;
      }
      if (path.endsWith("/evidence")) {
        return { evidence: mockEvidence } as any;
      }
      if (path.endsWith("/leads")) {
        return {
          leads: [
            {
              id: "lead-101",
              url: mockEvidence[0].links[0],
              evidence_ids: [evidenceId],
              verification_status: "requires_review",
              confirmed_vacancy: false,
            },
          ],
        } as any;
      }
      if (path.startsWith("jobs/search")) {
        return { total: 0, jobs: [] } as any;
      }
      return {};
    });
  });

  it("displays multiple authorized Gmail accounts and supports switching accounts", async () => {
    render(
      <QueryClientProvider client={createClient()}>
        <ConnectedEmails />
      </QueryClientProvider>,
    );

    // Initial heading & active accounts
    expect(
      await screen.findByRole("heading", { name: "Gmail Job Inbox" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        name: "primary.jobs@example.com",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "secondary.alerts@example.com",
      }),
    ).toBeInTheDocument();

    // Category filter tabs
    expect(
      screen.getByRole("button", { name: /Job Alerts/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Interview Invitations/i }),
    ).toBeInTheDocument();
  });

  it("filters inbox messages by category (Job Alerts vs Interview Invitations)", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <ConnectedEmails />
      </QueryClientProvider>,
    );

    const initialLinks = await screen.findAllByRole("link", {
      name: "Inspect retained source link",
    });
    expect(initialLinks.length).toBeGreaterThan(0);

    // Filter to Job Alerts (record has signals: ["possible_job_lead", "interview_invitation"])
    await user.click(screen.getByRole("button", { name: /Job Alerts/i }));
    const alertLinks = await screen.findAllByRole("link", {
      name: "Inspect retained source link",
    });
    expect(alertLinks.length).toBeGreaterThan(0);

    // Filter to Recruiter Outreach (not in signals)
    await user.click(
      screen.getByRole("button", { name: /Recruiter Outreach/i }),
    );
    expect(
      screen.queryAllByRole("link", { name: "Inspect retained source link" }),
    ).toHaveLength(0);

    // Filter back to All Messages
    await user.click(screen.getByRole("button", { name: /All Messages/i }));
    const allLinks = await screen.findAllByRole("link", {
      name: "Inspect retained source link",
    });
    expect(allLinks.length).toBeGreaterThan(0);
  });

  it("inspects message detail modal with detected vacancy link and duplicate detection", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <ConnectedEmails />
      </QueryClientProvider>,
    );

    const initialLinks = await screen.findAllByRole("link", {
      name: "Inspect retained source link",
    });
    expect(initialLinks.length).toBeGreaterThan(0);

    // Open message detail modal
    const messageDetailsBtns = screen.getAllByRole("button", {
      name: /Message details/i,
    });
    await user.click(messageDetailsBtns[0]);

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Read-Only Message Detail")).toBeInTheDocument();
    expect(screen.getByText("Extracted Vacancy Links:")).toBeInTheDocument();

    // Lever ATS platform detected
    expect(screen.getByText("Lever")).toBeInTheDocument();

    // Strict read-only guarantee visible
    expect(screen.getByText(/Read-Only Notice:/i)).toBeInTheDocument();
  });
});

describe("Phase 4: Universal Form Assistant UI", () => {
  const fictionalPacket: Schema<"PacketRead"> = {
    id: "packet-universal-1",
    job_id: "job-universal-1",
    platform: "ashby",
    lifecycle_state: "ready_for_review",
    tracking_state: "not_applied",
    revision: 1,
    approved_revision: 1,
    review_status: "approved",
    submission_mode: "manual_handoff",
    created_at: "2026-10-28T10:00:00Z",
    updated_at: "2026-10-28T10:00:00Z",
    fields: [],
    readiness: {
      state: "needs_review",
      blockers: [],
      manual_steps: ["Inspect filled values before submitting manually."],
      warnings: [],
      stale: false,
    },
    snapshot: {
      preparation_supported: true,
      job_title: "Senior Backend Engineer",
      company_name: "FinPulse Labs",
      original_job_url: "https://finpulse.example/jobs/backend",
      source_platform: "ashby",
      destination: {
        application_url: "https://jobs.ashbyhq.com/finpulse/998877",
        kind: "employer_external",
        valid: true,
        source_confidence: "source_consistent",
      },
      resume: {
        reason: "Matched backend profile",
        upload_status: "manual_resume_upload_required",
        selected: {
          resource_id: "resume-1",
          label: "Senior_Backend_2026.pdf",
          url: "https://storage.example.org/resumes/backend.pdf",
          confirmed: true,
          primary: true,
          resource_version: "1",
        },
      },
      context_digest: "digest-1",
    },
  };

  const universalStatus = {
    packet: fictionalPacket,
    connected: true,
    manual: false,
    page_review_required: false,
    in_page_network_isolation: true,
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
        url: "https://jobs.ashbyhq.com/finpulse/998877",
        title: "FinPulse Labs - Senior Backend Engineer Application",
        heading: "Application Form",
      },
      warnings: [],
      fields: [
        {
          field_id: "field-name",
          question: "Full Legal Name",
          supported: true,
          kind: "text",
          manual_reason: null,
        },
        {
          field_id: "field-email",
          question: "Email Address",
          supported: true,
          kind: "email",
          manual_reason: null,
        },
        {
          field_id: "field-experience",
          question: "Years of Experience with Distributed Queues",
          supported: true,
          kind: "number",
          manual_reason: null,
        },
        {
          field_id: "field-missing-q1",
          question: "What is your target notice period?",
          supported: false,
          kind: "text",
          manual_reason: "Answer not found in verified facts",
        },
      ],
      validation: [
        {
          field_id: "field-name",
          complete: true,
          reason: "Provided from verified candidate profile",
        },
        {
          field_id: "field-email",
          complete: true,
          reason: "Provided from verified candidate profile",
        },
        {
          field_id: "field-experience",
          complete: true,
          reason: "Provided from verified candidate profile",
        },
        {
          field_id: "field-missing-q1",
          complete: false,
          reason: "Target notice period not answered in candidate facts",
        },
      ],
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "browser-applications/policy") {
        return {
          origins: ["https://jobs.ashbyhq.com"],
          digest: "policy-hash-123",
        } as any;
      }
      if (path === `browser-applications/${fictionalPacket.id}`) {
        return universalStatus as any;
      }
      return {};
    });
  });

  it("detects ATS platform (Ashby) and displays completion metric badges after status check", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <BrowserAssistant packet={fictionalPacket} />
      </QueryClientProvider>,
    );

    // Initial platform detection from destination URL
    expect(await screen.findByText("Ashby ATS")).toBeInTheDocument();
    expect(screen.getByText("Recognized URL host")).toBeInTheDocument();

    // Click 'Get status' to load analysis and field metrics
    const statusBtn = screen.getByRole("button", { name: "Get status" });
    await user.click(statusBtn);

    // Check field completion metrics
    expect(await screen.findByText("3 supported")).toBeInTheDocument();
    expect(screen.getByText("3 ready")).toBeInTheDocument();
    expect(screen.getByText("1 incomplete")).toBeInTheDocument();
    expect(screen.getByText("1 manual")).toBeInTheDocument();

    // Check explicit non-submission notice
    expect(
      screen.getByText(/It NEVER submits your application to the employer/i),
    ).toBeInTheDocument();
  });

  it("opens Needs Input without inventing a durable ID from the DOM field ID", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <BrowserAssistant packet={fictionalPacket} />
      </QueryClientProvider>,
    );

    // Click 'Get status' to load analyzed fields
    const statusBtn = screen.getByRole("button", { name: "Get status" });
    await user.click(statusBtn);

    const questionMatches = await screen.findAllByText(
      /What is your target notice period\?/i,
    );
    expect(questionMatches.length).toBeGreaterThanOrEqual(1);

    // Needs Input deep-link
    const answerLink = screen.getByRole("link", {
      name: /Answer in Needs Input/i,
    });
    expect(answerLink).toHaveAttribute("href", "/needs-input");
  });
});

describe("Phase 4: Candidate Knowledge Stories & Bug Narratives", () => {
  const profileWithStories: Schema<"CandidateProfileRead"> = {
    id: "00000000-0000-0000-0000-000000000001",
    singleton_key: "primary",
    full_name: "Karan Aggarwal",
    email: "karan@example.com",
    phone: "+91 98765 43210",
    summary:
      "Senior Fullstack & Platform Engineer specializing in high-throughput systems.",
    personal_website: "https://karan.dev",
    github_url: "https://github.com/karan",
    linkedin_url: "https://linkedin.com/in/karan",
    portfolio_url: "https://karan.dev/portfolio",
    verified_experience_years: 6,
    verified_skills: [
      "Python",
      "FastAPI",
      "TypeScript",
      "Next.js",
      "PostgreSQL",
      "Redis",
    ],
    verified_roles: [],
    education: [],
    certifications: [],
    projects: [
      {
        name: "Distributed Idempotency Engine",
        contribution: "Lead Architect",
        description:
          "Zero-data-loss idempotency proxy processing 50,000 req/sec across payment gateways.",
        measurable_results:
          "Reduced duplicate charge rate from 0.4% to 0.000%, saving $120k annually.",
        technologies: ["Go", "Redis", "gRPC", "Docker"],
        url: "https://github.com/karan/idempotency-engine",
        implementation_details:
          "Architected two-phase commit lock with Redis Redlock and fallback SQLite journal for network partitions.",
        engineering_challenges:
          "Diagnosed a silent deadlock caused by unbuffered channels under TCP SYN flood; fixed with non-blocking select loops and ring buffers.",
      },
    ],
    preferences: {
      current_location: "Bengaluru, India",
      notice_period_days: 30,
      remote_preference: "any",
      current_compensation: null,
      expected_compensation: null,
      work_authorizations: [],
    },
    version: 4,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-28T10:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "profile") {
        return profileWithStories;
      }
      if (path === "profile/resources") {
        return { resources: [] };
      }
      if (path === "application-answers/saved") {
        return [];
      }
      if (path === "profile/reuse-bank") {
        return { enabled: true, approvals: {} };
      }
      return {};
    });
  });

  it("renders API integration examples & hardest bug stories in dedicated tab", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createClient()}>
        <CandidateKnowledge />
      </QueryClientProvider>,
    );

    // Find tab with stories count (1)
    const storiesTab = await screen.findByRole("tab", {
      name: /API integrations & hardest bugs \(1\)/i,
    });
    expect(storiesTab).toBeInTheDocument();

    // Click tab
    await user.click(storiesTab);

    // Verify stories content
    expect(
      await screen.findByRole("heading", {
        name: /API Integrations & Hardest Bug Stories \(1\)/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Distributed Idempotency Engine"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Architected two-phase commit lock with Redis Redlock/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Diagnosed a silent deadlock caused by unbuffered channels/i,
      ),
    ).toBeInTheDocument();
  });
});
