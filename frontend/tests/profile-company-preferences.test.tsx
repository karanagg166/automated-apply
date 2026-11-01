import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { ProfileWizard } from "@/features/profile";
import { api, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
vi.mock("@/features/profile-resources", () => ({
  ProfileResources: () => null,
}));
vi.mock("@/features/project-context", () => ({ ProjectContext: () => null }));
vi.mock("@/features/resume-sync", () => ({ ResumeSync: () => null }));
vi.mock("@/features/career-facts", () => ({ CareerFacts: () => null }));
vi.mock("@/features/approved-answers", () => ({ ApprovedAnswers: () => null }));

beforeEach(() => vi.clearAllMocks());

it.each([
  {
    stages: "",
    priority: "false",
    expectedStages: [],
    expectedPriority: false,
  },
  {
    stages: "seed",
    priority: "true",
    expectedStages: ["seed"],
    expectedPriority: true,
  },
])(
  "saves active company preferences with profile version and review: $stages/$priority",
  async ({ stages, priority, expectedStages, expectedPriority }) => {
    const profile = {
      id: "fictional-profile",
      version: 7,
      full_name: "Alex Example",
      email: "alex@example.org",
      verified_skills: ["Python"],
      verified_experience_years: 0.333333,
      verified_roles: [],
      education: [],
      projects: [],
      preferences: {
        target_titles: ["Software Engineer"],
        company_stages: ["early"],
        prioritize_startups: true,
        excluded_companies: ["Excluded Example"],
        current_location: "Fictional City",
      },
    };
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "profile") {
        return options?.method === "PUT" ? { ...profile, version: 8 } : profile;
      }
      if (path === "dashboard/onboarding/manifest") return { resources: [] };
      if (path === "candidate/resources") return { resources: [] };
      if (path === "dashboard/resumes") return { resumes: [] };
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.mocked(post).mockResolvedValue({});
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ProfileWizard />
      </QueryClientProvider>,
    );
    await screen.findByDisplayValue("Alex Example");
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Search preferences/ }),
    );
    expect(screen.getByLabelText("Allowed company stages")).toHaveValue(
      "early",
    );
    expect(screen.getByLabelText("Startup preference")).toHaveValue("true");
    expect(screen.getByLabelText("Current location")).toHaveValue(
      "Fictional City",
    );
    await user.clear(screen.getByLabelText("Current location"));
    await user.type(
      screen.getByLabelText("Current location"),
      "Updated Fictional City",
    );
    await user.clear(screen.getByLabelText("Allowed company stages"));
    if (stages)
      await user.type(screen.getByLabelText("Allowed company stages"), stages);
    await user.selectOptions(
      screen.getByLabelText("Startup preference"),
      priority,
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(
      screen.getByRole("checkbox", { name: /I reviewed these facts/ }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save reviewed profile" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("local-agent/profile-confirmation", {
        expected_version: 8,
        owner_confirmed: true,
      }),
    );
    const saved = vi
      .mocked(api)
      .mock.calls.find(
        ([path, options]) => path === "profile" && options?.method === "PUT",
      );
    expect(saved?.[1]?.headers).toEqual({ "If-Match": '"7"' });
    const body = JSON.parse(String(saved?.[1]?.body));
    expect(body.preferences).toMatchObject({
      company_stages: expectedStages,
      prioritize_startups: expectedPriority,
      excluded_companies: ["Excluded Example"],
      current_location: "Updated Fictional City",
    });
    expect(body.verified_skills).toEqual(["Python"]);
    expect(body.verified_experience_years).toBe(0.333333);
  },
);
