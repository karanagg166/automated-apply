import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, patch, post, type Schema } from "@/lib/api";
import { CareerFacts } from "@/features/career-facts";
import { ApprovedAnswers } from "@/features/approved-answers";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));
const profile: Schema<"CandidateProfileRead"> = {
  id: "11111111-1111-4111-8111-111111111111",
  full_name: "Alex Example",
  email: "alex@example.org",
  version: 7,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  singleton_key: "primary",
  preferences: { minimum_salary: 900000, salary_currency: "INR" },
};
const draft: Schema<"DraftRead"> = {
  id: "22222222-2222-4222-8222-222222222222",
  candidate_profile_id: profile.id,
  job_id: null,
  question: "Describe a challenging project you built",
  answer: "I built a Python service and solved a retry problem.",
  question_category: "project_explanation",
  writing_style: "professional",
  provider: "ollama",
  model: "fictional-local",
  evidence_references: [
    { source_type: "candidate_profile", source_id: profile.id },
  ],
  candidate_profile_version: 7,
  review_status: "reviewed",
  stale: false,
  created_at: profile.created_at,
  updated_at: profile.updated_at,
};
function mount(element: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      {element}
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(profile);
});

it("saves explicit compensation units without copying minimum salary or guessing work authorization", async () => {
  mount(<CareerFacts profile={profile} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("Private application facts"));
  expect(screen.getByLabelText("Current compensation amount")).toHaveValue(
    null,
  );
  const save = screen.getByRole("button", {
    name: "Save reviewed career facts",
  });
  expect(save).toBeDisabled();
  await user.type(
    screen.getByLabelText("Expected compensation amount"),
    "1800000",
  );
  await user.type(
    screen.getByLabelText("Expected compensation currency"),
    "INR",
  );
  await user.selectOptions(
    screen.getByLabelText("Expected compensation period"),
    "year",
  );
  await user.selectOptions(
    screen.getByLabelText("Expected compensation type"),
    "ctc",
  );
  await user.click(
    screen.getByRole("checkbox", {
      name: "I reviewed these private career facts and their units.",
    }),
  );
  await user.click(save);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "profile",
      expect.objectContaining({
        method: "PATCH",
        headers: { "If-Match": '"7"' },
      }),
    ),
  );
  const options = vi.mocked(api).mock.calls[0][1]!;
  const body = JSON.parse(String(options.body));
  expect(body.preferences.current_compensation).toBeNull();
  expect(body.preferences.expected_compensation).toEqual({
    amount: "1800000",
    currency: "INR",
    period: "year",
    kind: "ctc",
  });
  expect(body.preferences.open_to_relocation).toBeNull();
  expect(body.preferences.work_authorizations).toEqual([]);
  expect(body.preferences.minimum_salary).toBeUndefined();
});

it("adds a country with unknown authorization and requires an explicit answer", async () => {
  mount(<CareerFacts profile={profile} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("Private application facts"));
  await user.click(
    screen.getByRole("button", { name: "Add country authorization" }),
  );
  expect(screen.getByLabelText("Authorized to work")).toHaveValue("");
  expect(
    screen.getByLabelText("Need sponsorship now or in future"),
  ).toHaveValue("");
  await user.type(screen.getByLabelText("Country code"), "IN");
  await user.type(screen.getByLabelText("Country name"), "India");
  await user.selectOptions(screen.getByLabelText("Authorized to work"), "true");
  await user.click(screen.getByRole("checkbox"));
  await user.click(
    screen.getByRole("button", { name: "Save reviewed career facts" }),
  );
  await waitFor(() => expect(api).toHaveBeenCalled());
  const body = JSON.parse(String(vi.mocked(api).mock.calls[0][1]!.body));
  expect(body.preferences.work_authorizations).toEqual([
    {
      country_code: "IN",
      country_name: "India",
      authorized_to_work: true,
      requires_sponsorship_now_or_future: null,
    },
  ]);
});

it("requires current owner review before approving saved answer reuse", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith("application-answers/drafts")
      ? [draft]
      : { enabled: true, owner_approval_available: true, approvals: {} },
  );
  mount(<ApprovedAnswers profileVersion={7} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("Reviewed application answers"));
  const button = await screen.findByRole("button", {
    name: "Approve answer reuse",
  });
  expect(button).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(button);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `application-answers/drafts/${draft.id}/approve-reuse`,
      {
        expected_profile_version: 7,
        scope: "general_profile",
        confirm_reviewed_answer: true,
      },
    ),
  );
});

it("prevents company motivation reuse without a saved job and hides approval without owner configuration", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith("application-answers/drafts")
      ? [
          {
            ...draft,
            question_category: "motivation",
            question: "Why join this company?",
          },
        ]
      : { enabled: true, owner_approval_available: true, approvals: {} },
  );
  mount(<ApprovedAnswers profileVersion={7} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("Reviewed application answers"));
  const article = (await screen.findByText("Why join this company?")).closest(
    "article",
  )!;
  expect(
    within(article).queryByRole("button", { name: "Approve answer reuse" }),
  ).not.toBeInTheDocument();
  expect(
    within(article).getByText(/requires an exact saved job/),
  ).toBeInTheDocument();
});
