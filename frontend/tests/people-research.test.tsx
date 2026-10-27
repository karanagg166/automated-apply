import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { CompanyPeople, type Contact } from "@/features/people";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

const fictionalContacts: Contact[] = [
  {
    id: "contact-1",
    company_id: "comp-1",
    company: "Acme Tech",
    full_name: "Anita Sharma",
    role_title: "Chief Technology Officer",
    linkedin_url: "https://www.linkedin.com/in/anita-example",
    professional_url: "https://anita-example.github.io",
    email: "anita@acme-tech.example",
    email_status: "verified",
    source: "github_commit_signature",
    confidence: "supported",
    do_not_contact: false,
    suppression_reason: null,
    manual_linkedin_available: true,
    manual_outreach_review_available: true,
    email_send_ready: true,
    retention_expired: false,
    last_checked_at: "2026-03-01T12:00:00Z",
  },
  {
    id: "contact-2",
    company_id: "comp-1",
    company: "Acme Tech",
    full_name: "Vikram Malhotra",
    role_title: "Founder & CEO",
    linkedin_url: "https://www.linkedin.com/in/vikram-example",
    professional_url: null,
    email: "vikram@acme-tech.example",
    email_status: "guessed",
    source: "provider_pattern_guess",
    confidence: "unverified",
    do_not_contact: false,
    suppression_reason: null,
    manual_linkedin_available: true,
    manual_outreach_review_available: false,
    email_send_ready: false,
    retention_expired: false,
    last_checked_at: "2026-02-15T09:00:00Z",
  },
  {
    id: "contact-3",
    company_id: "comp-1",
    company: "Acme Tech",
    full_name: "Rahul Verma",
    role_title: "Senior Backend Engineer",
    linkedin_url: null,
    professional_url: "https://github.com/rahul-example",
    email: null,
    email_status: "unknown",
    source: "public_github_team",
    confidence: "provider_reported",
    do_not_contact: false,
    suppression_reason: null,
    manual_linkedin_available: false,
    manual_outreach_review_available: false,
    email_send_ready: false,
    retention_expired: true,
    last_checked_at: "2025-11-01T10:00:00Z",
  },
  {
    id: "contact-4",
    company_id: "comp-1",
    company: "Acme Tech",
    full_name: "Pooja Nair",
    role_title: "Technical Recruiter",
    linkedin_url: "https://www.linkedin.com/in/pooja-recruiter",
    professional_url: null,
    email: "pooja@acme-tech.example",
    email_status: "unverified",
    source: "apollo_provider",
    confidence: "provider_reported",
    do_not_contact: true,
    suppression_reason: "Requested exclusion from automated indexing",
    manual_linkedin_available: true,
    manual_outreach_review_available: false,
    email_send_ready: false,
    retention_expired: false,
    last_checked_at: "2026-01-20T14:00:00Z",
  },
];

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <CompanyPeople
        companyId="comp-1"
        companyName="Acme Tech"
        domain="acme-tech.example"
      />
    </QueryClientProvider>,
  );
}

describe("Company and people research screen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "companies/comp-1/contacts") {
        return { contacts: fictionalContacts } as any;
      }
      if (path === "companies/comp-1/people") {
        return { people: [] } as any;
      }
      return {} as any;
    });
  });

  it("renders verified source-backed CTO contact and safe professional URL", async () => {
    mount();

    expect(await screen.findByText("Anita Sharma")).toBeInTheDocument();
    expect(screen.getByText(/Chief Technology Officer/i)).toBeInTheDocument();

    // Source-backed confidence badge
    expect(screen.getByText("Verified · Source-backed")).toBeInTheDocument();

    // Verified mailbox badge
    expect(screen.getByText("Verified mailbox")).toBeInTheDocument();

    // Safe external profile URL
    const links = screen.getAllByRole("link", {
      name: "Open professional profile",
    });
    expect(links[0]).toHaveAttribute(
      "href",
      expect.stringMatching(
        /^https:\/\/www\.linkedin\.com\/in\/anita-example\/?$/,
      ),
    );
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("NEVER marks a guessed business email as verified", async () => {
    mount();

    expect(await screen.findByText("Vikram Malhotra")).toBeInTheDocument();
    expect(screen.getByText(/Founder & CEO/i)).toBeInTheDocument();

    // Guessed email MUST show as Guessed email (Unverified)
    expect(screen.getByText("Guessed email (Unverified)")).toBeInTheDocument();
  });

  it("distinguishes stale/retention expired and suppressed contacts", async () => {
    mount();

    expect(await screen.findByText("Rahul Verma")).toBeInTheDocument();
    // Retention expired badge
    expect(screen.getByText("Retention expired · Stale")).toBeInTheDocument();

    expect(screen.getByText("Pooja Nair")).toBeInTheDocument();
    // Suppression badge and reason
    expect(screen.getByText("Suppressed")).toBeInTheDocument();
    expect(
      screen.getByText(/Requested exclusion from automated indexing/i),
    ).toBeInTheDocument();
  });

  it("supports role filtering tabs (Founders & CEOs, CTOs & Leaders, Engineers, Recruiters)", async () => {
    mount();

    await screen.findByText("Anita Sharma");

    // Click Founders & CEOs tab
    const founderTab = screen.getByRole("button", { name: "Founders & CEOs" });
    await userEvent.click(founderTab);

    // Only Vikram Malhotra (Founder & CEO) should be shown
    expect(screen.getByText("Vikram Malhotra")).toBeInTheDocument();
    expect(screen.queryByText("Anita Sharma")).toBeNull();
    expect(screen.queryByText("Rahul Verma")).toBeNull();
    expect(screen.queryByText("Pooja Nair")).toBeNull();

    // Click Engineers tab
    const engineerTab = screen.getByRole("button", { name: "Engineers" });
    await userEvent.click(engineerTab);

    // Only Rahul Verma should be shown
    expect(screen.getByText("Rahul Verma")).toBeInTheDocument();
    expect(screen.queryByText("Vikram Malhotra")).toBeNull();
  });

  it("strictly enforces NO automated email sending or LinkedIn message dispatch controls", async () => {
    mount();

    await screen.findByText("Anita Sharma");

    // Zero send email or automated messaging buttons
    expect(screen.queryByRole("button", { name: /send email/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /send message/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /auto connect/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /send invitation/i }),
    ).toBeNull();
  });
});
