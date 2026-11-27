import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  RulesStudio,
  hardRulesPatch,
  toHardRules,
} from "@/features/rules-studio";
import { api, patch, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

const profile = {
  version: 4,
  has_profile: true,
  target_roles: ["Backend Engineer"],
  keywords_excluded: ["Senior"],
  company_blacklist: [],
  keywords_required: [],
  total_experience_years: 0.33,
  max_required_experience_years: 0,
  min_match_score: null,
  current_location: "Faridabad",
  remote_policy: "any" as const,
};

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/screening-profile") return structuredClone(profile);
    if (path === "v2/worker/telemetry")
      return {
        telegram: { quiet_hours: "23:30-08:00", quiet_hours_active: false },
      };
    if (path === "v2/portal-rules") return [];
    throw new Error(path);
  });
});

it("builds a minimal versioned patch", () => {
  const form = {
    ...toHardRules(profile),
    keywords_excluded: "Senior, Lead",
    max_required_experience_years: "1",
  };
  const { body, changed, errors } = hardRulesPatch(profile, form);
  expect(errors).toEqual([]);
  expect(changed.sort()).toEqual([
    "keywords_excluded",
    "max_required_experience_years",
  ]);
  expect(body).toMatchObject({
    version: 4,
    keywords_excluded: ["Senior", "Lead"],
    max_required_experience_years: 1,
  });
  expect(
    hardRulesPatch(profile, { ...form, min_match_score: "500" }).errors,
  ).toHaveLength(1);
});

it("saves hard rules and explains a job against them", async () => {
  const user = userEvent.setup();
  vi.mocked(patch).mockResolvedValue({
    ...profile,
    version: 5,
    keywords_excluded: ["Senior", "Lead"],
  });
  vi.mocked(post).mockResolvedValue({
    decision: "FILTERED",
    passed: false,
    reasons: ["experience 3+ years > max 0"],
    checks: [
      { name: "title_match", passed: true, detail: "Backend Engineer" },
      { name: "experience", passed: false, detail: "3+ years required" },
    ],
    score: { total: 42, breakdown: { skills: 30, title: 12 } },
  });
  mount(<RulesStudio />);
  expect(
    await screen.findByText("Quiet hours: 23:30-08:00"),
  ).toBeInTheDocument();
  const excluded = await screen.findByLabelText("Excluded title keywords");
  await user.clear(excluded);
  await user.type(excluded, "Senior, Lead");
  await user.click(screen.getByRole("button", { name: /Save 1 change/ }));
  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith("v2/screening-profile", {
      version: 4,
      keywords_excluded: ["Senior", "Lead"],
    }),
  );

  const testButton = screen.getByRole("button", { name: "Test job" });
  expect(testButton).toBeDisabled();
  await user.type(screen.getByLabelText("Job title"), "Backend Engineer");
  await user.type(
    screen.getByLabelText("Experience required (as posted)"),
    "3+ years",
  );
  await user.click(testButton);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/rules/explain", {
      title: "Backend Engineer",
      experience_text: "3+ years",
    }),
  );
  const verdict = await screen.findByLabelText("Rules verdict");
  expect(
    within(verdict).getByText("Filtered out · FILTERED"),
  ).toBeInTheDocument();
  expect(within(verdict).getByText("Score 42")).toBeInTheDocument();
  expect(within(verdict).getByText("3+ years required")).toBeInTheDocument();
  expect(within(verdict).getByText("fail")).toBeInTheDocument();
  expect(within(verdict).getByText("skills").nextSibling).toHaveTextContent(
    "30",
  );
});
