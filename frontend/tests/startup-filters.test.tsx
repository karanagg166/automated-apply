import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
import { StartupExplorer, sizeFilter } from "@/features/startups";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const fictionalStartupA: Schema<"StartupRead"> = {
  company_id: "aaaaaaaa-1111-4111-8111-111111111111",
  company_name: "Acme Cloud AI",
  company_domain: "acme-ai.example",
  attributes: {
    industry: "AI / Machine Learning",
    description: "Fictional platform for real-time observability.",
    city: "Bengaluru",
    country: "India",
    location: "Bengaluru, India",
    is_remote: true,
    technology_stack: ["Python", "FastAPI", "React", "Docker"],
  },
  exact_employee_count: false,
  employee_count: null,
  team_size_band: "11-50",
  team_size_evidence_status: "source_reported",
  leader_evidence_count: 2,
  technical_staff_count: 14,
  verification_status: "verified",
  hiring_status: "hiring_confirmed",
  startup_match_score: 95,
  current_job_count: 4,
  professional_contact_count: 6,
  sources: ["official_careers", "github_public"],
  shortlisted: false,
  matching_roles: 2,
  missing_information: [],
  team_size_evidence: [
    {
      source_url: "https://linkedin.example/company/acme-ai",
      observed_at: "2026-03-01T10:00:00Z",
      source_type: "linkedin_public",
      confidence: 0.95,
      detail: "11-50 employees on official public profile",
    },
  ],
  hiring_evidence: [
    {
      job_id: "job-1",
      title: "Senior Backend Engineer",
      evidence_url: "https://acme-ai.example/careers/backend",
      observed_at: "2026-03-05T12:00:00Z",
      fresh: true,
      source_type: "careers_page",
      confidence: 0.9,
      detail: "Actively hiring Backend Engineers",
    },
  ],
};

const fictionalStartupB: Schema<"StartupRead"> = {
  company_id: "bbbbbbbb-2222-4222-8222-222222222222",
  company_name: "Boutique DevTools India",
  company_domain: "boutique-dev.example",
  attributes: {
    industry: "Software / SaaS",
    description: "Fictional micro-SaaS developer tooling.",
    city: "Pune",
    country: "India",
    location: "Pune, India",
    is_remote: false,
    technology_stack: ["TypeScript", "Next.js"],
  },
  exact_employee_count: true,
  employee_count: 7,
  team_size_band: "1-10",
  team_size_evidence_status: "conflicting",
  leader_evidence_count: 0,
  technical_staff_count: 5,
  verification_status: "conflicting",
  hiring_status: "hiring_unknown",
  startup_match_score: 75,
  current_job_count: 1,
  professional_contact_count: 2,
  sources: ["direct"],
  shortlisted: false,
  matching_roles: 1,
  missing_information: [],
  team_size_evidence: [],
  hiring_evidence: [],
};

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <StartupExplorer />
    </QueryClientProvider>,
  );
}

describe("Startup discovery and size filtering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockResolvedValue({ presets: [] });
  });

  it("produces exact size filter query parameters without inventing headcounts", () => {
    // 11-50 band
    expect(sizeFilter("11-50")).toEqual({
      min_employees: 11,
      max_employees: 50,
      exact_employee_count: false,
      include_unknown_size: false,
      size_bands: ["11-50"],
    });

    // 2-10 small startup band
    expect(sizeFilter("2-10")).toEqual({
      min_employees: 2,
      max_employees: 10,
      exact_employee_count: true,
      include_unknown_size: false,
      size_bands: [],
    });

    // 51-200 preset
    expect(sizeFilter("51-200")).toEqual({
      min_employees: null,
      max_employees: null,
      exact_employee_count: false,
      include_unknown_size: false,
      size_bands: ["51-200"],
    });

    // Unknown size
    expect(sizeFilter("unknown")).toEqual({
      min_employees: null,
      max_employees: null,
      exact_employee_count: false,
      include_unknown_size: true,
      size_bands: ["unknown"],
    });

    // All sizes
    expect(sizeFilter("all")).toEqual({
      min_employees: null,
      max_employees: null,
      exact_employee_count: false,
      include_unknown_size: true,
      size_bands: [],
    });
  });

  it("never turns an employee-size band into an invented exact headcount", async () => {
    vi.mocked(post).mockResolvedValue({
      startups: [fictionalStartupA, fictionalStartupB],
      total: 2,
      page: 1,
      per_page: 20,
    });

    mount();

    // Verify company names are displayed
    expect(await screen.findByText("Acme Cloud AI")).toBeInTheDocument();
    expect(screen.getByText("Boutique DevTools India")).toBeInTheDocument();

    // Startup A has band "11-50" and exact_employee_count: false
    // It should display "11-50 band", NOT any invented number
    expect(screen.getByText("11-50 band")).toBeInTheDocument();

    // Conflicting evidence never establishes an exact count.
    expect(screen.queryByText("7 employees (exact count)")).toBeNull();
    expect(screen.getByText("1-10 band")).toBeInTheDocument();
  });

  it("displays leader availability, technical evidence badges, and safe website links", async () => {
    vi.mocked(post).mockResolvedValue({
      startups: [fictionalStartupA],
      total: 1,
      page: 1,
      per_page: 20,
    });

    mount();

    expect(await screen.findByText("Acme Cloud AI")).toBeInTheDocument();

    // Founder / CEO availability badge with count
    expect(screen.getByText("Founder / CEO available (2)")).toBeInTheDocument();

    // Technical team evidence badge
    expect(
      screen.getByText("Technical staff evidence (14)"),
    ).toBeInTheDocument();

    // Verification status badge
    expect(screen.getByText(/Size:\s*source reported/i)).toBeInTheDocument();

    // Safe official website external link
    const siteLink = screen.getByRole("link", { name: "Official website" });
    expect(siteLink).toHaveAttribute(
      "href",
      expect.stringMatching(/^https:\/\/acme-ai\.example\/?$/),
    );
    expect(siteLink).toHaveAttribute("target", "_blank");
    expect(siteLink).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("supports filtering by India locations and industry domains", async () => {
    vi.mocked(post).mockResolvedValue({
      startups: [fictionalStartupA],
      total: 1,
      page: 1,
      per_page: 20,
    });

    mount();

    await screen.findByText("Acme Cloud AI");

    // Check size filter dropdown options include 11-50 and 2-10
    const sizeSelect = screen.getByLabelText("Company size");
    expect(sizeSelect).toBeInTheDocument();

    // Check Indian location filter dropdown
    const locationSelect = screen.getByLabelText("Location");
    expect(locationSelect).toBeInTheDocument();

    // Check industry filter dropdown
    const industrySelect = screen.getByLabelText("Industry");
    expect(industrySelect).toBeInTheDocument();

    // Select 11–50 size band
    fireEvent.change(sizeSelect, { target: { value: "11-50" } });

    // Select Bengaluru location
    fireEvent.change(locationSelect, { target: { value: "Bengaluru" } });

    // Select AI industry
    fireEvent.change(industrySelect, { target: { value: "AI" } });

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "startups/search",
        expect.objectContaining({
          industries: ["AI"],
          locations: ["Bengaluru"],
          size_bands: ["11-50"],
        }),
      ),
    );
  });

  it("renders empty state without fictional records and supports retry on error", async () => {
    vi.mocked(post)
      .mockRejectedValueOnce(
        new Error("Network timeout contacting startup directory"),
      )
      .mockResolvedValueOnce({
        startups: [],
        total: 0,
        page: 1,
        per_page: 20,
      });

    mount();

    expect(
      await screen.findByText(/Network timeout contacting startup directory/i),
    ).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: "Try again" });
    expect(retryBtn).toBeInTheDocument();

    await userEvent.click(retryBtn);

    expect(
      await screen.findByText("Your next team is out there."),
    ).toBeInTheDocument();
  });
});

it("renders an observed count with the actual backend evidence status", async () => {
  vi.mocked(post).mockResolvedValue({
    startups: [
      {
        ...fictionalStartupA,
        employee_count: 7,
        team_size_band: "2-10",
        team_size_evidence_status: "human_confirmed",
      },
    ],
    total: 1,
    page: 1,
    limit: 12,
  });
  mount();
  expect(
    await screen.findByText("7 employees (human confirmed)"),
  ).toBeInTheDocument();
});
