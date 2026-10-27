import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Jobs, type Job } from "@/features/jobs";
import { api, post } from "@/lib/api";

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

const mockJobs: Job[] = [
  {
    id: "00000000-0000-0000-0000-000000000001",
    title: "Senior Backend Engineer",
    company_name: "Acme Cloud Corp",
    company_id: "00000000-0000-0000-0000-0000000000c1",
    company_domain: "acmecloud.example.org",
    company_intelligence: {
      team_size: "15-50",
    },
    location: "Berlin, Germany",
    remote_type: "hybrid",
    is_remote: false,
    employment_type: "full_time",
    salary_min: 80000,
    salary_max: 95000,
    salary_currency: "EUR",
    salary_period: "year",
    skills_required: ["Python", "FastAPI", "PostgreSQL"],
    match_score: 92,
    match: {
      match_score: 92,
      missing_skills: ["Kubernetes"],
    },
    status: "discovered" as any,
    application_state: null,
    source_platform: "arbeitnow",
    source_verification_status: "verified",
    date_posted: "2026-10-20T08:00:00Z",
    last_observed_at: "2026-10-25T14:30:00Z",
    created_at: "2026-10-25T14:30:00Z" as any,
    updated_at: "2026-10-25T14:30:00Z" as any,
    job_url: "https://arbeitnow.example.org/jobs/acme-backend",
    application_url: "https://acmecloud.example.org/careers/apply",
  },
  {
    id: "00000000-0000-0000-0000-000000000002",
    title: "Distributed Systems Architect",
    company_name: null, // missing company evidence
    company_id: null,
    company_intelligence: {}, // missing team size
    location: null, // unknown location
    remote_type: "unknown",
    is_remote: false,
    employment_type: null,
    salary_min: null, // missing salary
    salary_max: null,
    salary_currency: null,
    salary_range: null,
    skills_required: [], // empty skills
    match_score: null,
    match: null, // no match calculation
    status: "applied" as any, // submitted application
    application_state: "user_reported_submitted",
    source_platform: "remotive",
    source_verification_status: "unverified",
    date_posted: null, // missing publication date
    last_observed_at: "2026-10-26T12:00:00Z",
    created_at: "2026-10-26T12:00:00Z" as any,
    updated_at: "2026-10-26T12:00:00Z" as any,
    job_url: "https://remotive.example.org/jobs/distributed-architect",
    application_url: null,
  },
  {
    id: "00000000-0000-0000-0000-000000000003",
    title: "Frontend Specialist",
    company_name: "Fintech Sandbox",
    company_id: "00000000-0000-0000-0000-0000000000c3",
    company_intelligence: {
      headcount: "100+",
    },
    location: "Remote - Worldwide",
    remote_type: "remote",
    is_remote: true,
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_range: "$110k - $130k",
    skills_required: ["React", "TypeScript", "Next.js"],
    match_score: 84,
    match: {
      match_score: 84,
      missing_skills: [],
    },
    status: "shortlisted" as any,
    application_state: "ready_for_review", // packet prepared, but not submitted
    source_platform: "hacker_news",
    source_verification_status: "verified",
    date_posted: "2026-10-22T10:00:00Z",
    last_observed_at: "2026-10-26T16:00:00Z",
    created_at: "2026-10-26T16:00:00Z" as any,
    updated_at: "2026-10-26T16:00:00Z" as any,
    job_url: "https://news.ycombinator.example.org/item?id=12345",
    application_url: "javascript:alert(1)", // unsafe javascript URL! Must be sanitized by helper
  },
];

function mount() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Jobs />
    </QueryClientProvider>,
  );
}

describe("Jobs feature", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return {
          total: mockJobs.length,
          jobs: structuredClone(mockJobs),
        };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });
  });

  it("renders status tabs and changes application status filter", async () => {
    const user = userEvent.setup();
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    const shortlistedTab = screen.getByRole("button", {
      name: "Shortlisted",
    });
    expect(shortlistedTab).toHaveAttribute("aria-pressed", "false");

    await user.click(shortlistedTab);

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("application_status=shortlisted"),
      );
    });

    const appliedTab = screen.getByRole("button", { name: "Applied" });
    await user.click(appliedTab);

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("application_status=applied"),
      );
    });
  });

  it("filters jobs by title, location, skill, and source platform", async () => {
    const user = userEvent.setup();
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    const titleInput = screen.getByRole("textbox", { name: "Job title" });
    await user.type(titleInput, "Backend");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(expect.stringContaining("role=Backend"));
    });

    const locationInput = screen.getByRole("textbox", {
      name: "Job location",
    });
    await user.type(locationInput, "Berlin");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("location=Berlin"),
      );
    });

    const skillInput = screen.getByRole("textbox", { name: "Job skill" });
    await user.type(skillInput, "Python");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(expect.stringContaining("skill=Python"));
    });

    const platformSelect = screen.getByRole("combobox", {
      name: "Source platform",
    });
    await user.selectOptions(platformSelect, "arbeitnow");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("platform=arbeitnow"),
      );
    });
  });

  it("truthfully displays missing salary, missing company, unknown location and unknown team size", async () => {
    mount();

    await waitFor(() => {
      expect(
        screen.getByText("Distributed Systems Architect"),
      ).toBeInTheDocument();
    });

    // Check honest labels for job 2 (where evidence is missing)
    expect(
      screen.getByText("Company evidence not available"),
    ).toBeInTheDocument();
    expect(screen.getByText("Team size: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Salary: Not disclosed")).toBeInTheDocument();
    expect(screen.getByText("Location unknown")).toBeInTheDocument();
    expect(screen.getByText("Remote status unknown")).toBeInTheDocument();
  });

  it("accurately labels publication dates vs observation dates", async () => {
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    // Job 1 has both date_posted and last_observed_at
    expect(screen.getByText(/Published 20 Oct 2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Observed 25 Oct 2026/i)).toBeInTheDocument();

    // Job 2 has no date_posted
    expect(screen.getByText("Published date unknown")).toBeInTheDocument();
  });

  it("clearly distinguishes between Prepare application, Open application site, and Application submitted", async () => {
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    // Job 1 is not submitted: should show "Prepare application" button
    expect(
      screen.getAllByRole("button", { name: /Prepare application/i })[0],
    ).toBeInTheDocument();

    // Job 2 has been submitted: should show "Application submitted" badge
    expect(
      screen.getByText("Submission reported by owner"),
    ).toBeInTheDocument();

    // External link safety:
    // Job 1 has valid https URL
    const openSiteLinks = screen.getAllByRole("link", {
      name: /Open application site/i,
    });
    expect(openSiteLinks[0]).toHaveAttribute(
      "href",
      "https://acmecloud.example.org/careers/apply",
    );
    expect(openSiteLinks[0]).toHaveAttribute("target", "_blank");
    expect(openSiteLinks[0]).toHaveAttribute("rel", "noopener noreferrer");

    // Job 3 had unsafe javascript: URL -> should be sanitized to "Link unavailable"
    expect(screen.getByText("Link unavailable")).toBeInTheDocument();
  });

  it("displays match score and missing skills when returned", async () => {
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    // Job 1 has score 92/100 and missing skill Kubernetes
    expect(screen.getByText("92")).toBeInTheDocument();
    expect(screen.getByText(/Missing skills: Kubernetes/i)).toBeInTheDocument();

    // Job 2 has null match score -> should show "Profile needed" badge
    expect(screen.getByText("Profile needed")).toBeInTheDocument();
  });

  it("handles pagination controls and page limits", async () => {
    mount();

    await waitFor(() => {
      expect(screen.getByText(/Page 1 of 1/i)).toBeInTheDocument();
    });

    const prevButton = screen.getByRole("button", { name: "Previous" });
    const nextButton = screen.getByRole("button", { name: "Next" });

    // Since total = 3 and limit = 20, totalPages = 1
    expect(prevButton).toBeDisabled();
    expect(nextButton).toBeDisabled();
  });

  it("renders empty state when zero jobs match", async () => {
    vi.mocked(api).mockResolvedValueOnce({ total: 0, jobs: [] });
    mount();

    await waitFor(() => {
      expect(
        screen.getByText("Room for the right opportunity."),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/No saved jobs match these filters/i),
      ).toBeInTheDocument();
    });
  });

  it("does not trigger job submissions or Gmail sending from UI", async () => {
    mount();

    await waitFor(() => {
      expect(screen.getByText("Senior Backend Engineer")).toBeInTheDocument();
    });

    // Ensure no background network requests to Gmail or submission APIs were made
    expect(post).not.toHaveBeenCalled();
  });
  it("distinguishes provider confirmation from an owner report or legacy applied flag", async () => {
    const jobs = [
      {
        ...mockJobs[0],
        status: "applied",
        application_state: "provider_confirmed_submitted",
      },
      { ...mockJobs[1] },
      { ...mockJobs[2], status: "applied", application_state: null },
    ];
    vi.mocked(api).mockResolvedValueOnce({ total: jobs.length, jobs });
    mount();
    expect(await screen.findByText("Submission confirmed")).toBeInTheDocument();
    expect(
      screen.getByText("Submission reported by owner"),
    ).toBeInTheDocument();
    expect(screen.getByText("Marked applied")).toBeInTheDocument();
  });

  it("uses backend employee_count evidence and preserves salary upper bounds", async () => {
    vi.mocked(api).mockResolvedValueOnce({
      total: 1,
      jobs: [
        {
          ...mockJobs[0],
          company_intelligence: { employee_count: 8, team_size_band: "1-10" },
          salary_min: null,
          salary_max: 95000,
          salary_range: null,
        },
      ],
    });
    mount();
    expect(await screen.findByText("Team size: 8")).toBeInTheDocument();
    expect(screen.getByText(/EUR Up to 95,000 \/ year/)).toBeInTheDocument();
    expect(screen.queryByText("Salary: Not disclosed")).not.toBeInTheDocument();
  });

  it("loads source options dynamically from discovery/sources including new providers", async () => {
    const dynamicSources = [
      { id: "arbeitnow", display_name: "Arbeitnow" },
      { id: "greenhouse", display_name: "Greenhouse" },
      { id: "lever", display_name: "Lever ATS" },
      { id: "ashby", display_name: "Ashby HQ" },
    ];
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: mockJobs.length, jobs: structuredClone(mockJobs) };
      }
      if (path === "discovery/sources") {
        return { sources: dynamicSources };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    const user = userEvent.setup();
    mount();

    const select = await screen.findByRole("combobox", {
      name: "Source platform",
    });

    await waitFor(() => {
      expect(
        within(select).getByRole("option", { name: "Lever ATS" }),
      ).toHaveValue("lever");
      expect(
        within(select).getByRole("option", { name: "Ashby HQ" }),
      ).toHaveValue("ashby");
    });

    await user.selectOptions(select, "lever");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("platform=lever"),
      );
    });
  });

  it("distinguishes saved-job search filter from live discovery availability and does not claim live verification", async () => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: mockJobs.length, jobs: structuredClone(mockJobs) };
      }
      if (path === "discovery/sources") {
        return {
          sources: [
            {
              id: "greenhouse",
              display_name: "Greenhouse",
              live_verified: false,
            },
            { id: "ashby", display_name: "Ashby", live_verified: true },
          ],
        };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    mount();

    const select = await screen.findByRole("combobox", {
      name: "Source platform",
    });

    await waitFor(() => {
      expect(
        within(select).getByRole("option", { name: "Greenhouse" }),
      ).toBeInTheDocument();
      expect(
        within(select).getByRole("option", { name: "Ashby" }),
      ).toBeInTheDocument();
    });

    // Neither option should display misleading "live verified" or "(Free API)" labels in saved job filter
    expect(
      within(select).queryByText(/live verified/i),
    ).not.toBeInTheDocument();
    expect(within(select).queryByText(/Free API/i)).not.toBeInTheDocument();

    // Check disclaimer presence explaining origin filtering vs live verification
    expect(
      screen.getByText(
        /Source filter searches saved opportunities by origin; catalog presence does not imply live verification/i,
      ),
    ).toBeInTheDocument();
  });

  it("handles failed source metadata request gracefully without breaking the Jobs page", async () => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: mockJobs.length, jobs: structuredClone(mockJobs) };
      }
      if (path === "discovery/sources") {
        throw new Error("503 Service Unavailable");
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    mount();

    // Page renders jobs normally despite metadata failure
    expect(
      await screen.findByText("Senior Backend Engineer"),
    ).toBeInTheDocument();

    // Fallback source options remain usable
    const select = screen.getByRole("combobox", { name: "Source platform" });
    expect(
      within(select).getByRole("option", { name: "Arbeitnow" }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole("option", { name: "Greenhouse" }),
    ).toBeInTheDocument();
  });

  it("handles empty or missing source metadata by falling back to known providers", async () => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: mockJobs.length, jobs: structuredClone(mockJobs) };
      }
      if (path === "discovery/sources") {
        return { sources: [] };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    mount();

    expect(
      await screen.findByText("Senior Backend Engineer"),
    ).toBeInTheDocument();

    const select = screen.getByRole("combobox", { name: "Source platform" });
    expect(
      within(select).getByRole("option", { name: "Arbeitnow" }),
    ).toBeInTheDocument();
  });

  it("distinguishes zero results matching active filters from an empty repository, and supports filter reset", async () => {
    const user = userEvent.setup();

    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: 0, jobs: [] };
      }
      if (path === "discovery/sources") {
        return { sources: [] };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    mount();

    // With default status filter (not_applied), it indicates no saved jobs match these filters
    await waitFor(() => {
      expect(
        screen.getByText("Room for the right opportunity."),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/No saved jobs match these filters/i),
      ).toBeInTheDocument();
    });

    // Both Reset filters and Discover jobs action are present
    const resetButtons = screen.getAllByRole("button", {
      name: /Reset.*filters/i,
    });
    expect(resetButtons.length).toBeGreaterThan(0);

    const discoverLinks = screen.getAllByRole("link", {
      name: /Discover jobs/i,
    });
    expect(discoverLinks.length).toBeGreaterThanOrEqual(2);
    expect(discoverLinks[0]).toHaveAttribute("href", "/discover");

    // Click Reset filters
    await user.click(resetButtons[0]);

    // Now query was triggered with application_status=all and hasActiveFilters is false
    await waitFor(() => {
      expect(screen.getByText("No saved jobs yet")).toBeInTheDocument();
      expect(
        screen.getByText(/No saved jobs found in your repository/i),
      ).toBeInTheDocument();
    });
  });

  it("preserves custom or uncataloged platform filter in select options", async () => {
    const user = userEvent.setup();
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("jobs/search")) {
        return { total: mockJobs.length, jobs: structuredClone(mockJobs) };
      }
      if (path === "discovery/sources") {
        return {
          sources: [{ id: "greenhouse", display_name: "Greenhouse" }],
        };
      }
      throw new Error(`Unhandled api path: ${path}`);
    });

    mount();

    const select = await screen.findByRole("combobox", {
      name: "Source platform",
    });

    await user.selectOptions(select, "greenhouse");

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        expect.stringContaining("platform=greenhouse"),
      );
    });
  });

  it("provides accessible filter reset in filter panel when active filters exist", async () => {
    const user = userEvent.setup();
    mount();

    expect(
      await screen.findByText("Senior Backend Engineer"),
    ).toBeInTheDocument();

    const titleInput = screen.getByRole("textbox", { name: "Job title" });
    await user.type(titleInput, "Staff");

    const resetButton = screen.getByRole("button", {
      name: "Reset search filters",
    });
    expect(resetButton).toBeInTheDocument();

    await user.click(resetButton);

    await waitFor(() => {
      expect(titleInput).toHaveValue("");
    });
  });
});
