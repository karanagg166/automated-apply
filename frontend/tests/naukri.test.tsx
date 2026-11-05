import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Naukri } from "@/features/naukri";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "execution/naukri")
      return {
        configuration: {
          mode: "ON_DEMAND",
          interval_seconds: 21600,
          source: "saved_owner_imports",
          destinations: [],
          submission_permission: false,
        },
        executions: [],
        capabilities: {},
      };
    if (path === "execution/naukri/jobs") return { jobs: [] };
    if (path === "execution/questions") return [];
    throw Error(path);
  });
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Naukri />
    </QueryClientProvider>,
  );
}
it("defaults to on demand and does not start unattended work on mount", async () => {
  mount();
  await screen.findByRole("heading", { name: "Naukri" });
  expect(screen.getByRole("combobox", { name: "Automation mode" })).toHaveValue(
    "ON_DEMAND",
  );
  expect(screen.getByText(/Submission remains manual/)).toBeVisible();
  expect(post).not.toHaveBeenCalled();
});
it("imports only owner provided posting facts", async () => {
  mount();
  await screen.findByRole("heading", { name: "Naukri" });
  await userEvent.type(
    screen.getByLabelText("Naukri posting URL"),
    "https://www.naukri.com/job-listings-fictional-281026123456",
  );
  await userEvent.type(
    screen.getByLabelText("Role from the posting"),
    "Junior Software Engineer",
  );
  await userEvent.type(
    screen.getByLabelText("Employer from the posting"),
    "Fictional Circuit",
  );
  await userEvent.click(screen.getByRole("button", { name: "Import posting" }));
  expect(post).toHaveBeenCalledWith("execution/naukri/import", {
    jobs: [
      {
        url: "https://www.naukri.com/job-listings-fictional-281026123456",
        title: "Junior Software Engineer",
        employer: "Fictional Circuit",
      },
    ],
  });
});
it("allows only the fixed owner routes and no submit proxy", () => {
  expect(permittedRoute("execution/naukri", "PUT")).toBe(true);
  expect(permittedRoute("execution/naukri/import", "POST")).toBe(true);
  expect(
    permittedRoute(
      "execution/questions/11111111-1111-1111-1111-111111111111/answer",
      "POST",
    ),
  ).toBe(true);
  expect(permittedRoute("execution/naukri/submit", "POST")).toBe(false);
  expect(permittedRoute("execution/other/import", "POST")).toBe(false);
});

it("displays waiting for your answer and supports answering from the dashboard", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "execution/naukri")
      return {
        configuration: {
          mode: "ON_DEMAND",
          interval_seconds: 21600,
          source: "saved_owner_imports",
          destinations: [],
          submission_permission: false,
        },
        executions: [
          {
            id: "exec-1",
            role: "Junior Backend Engineer",
            employer: "Acme Corp",
            state: "NEEDS_INPUT",
            revision: 1,
            packet_id: "packet-1",
            diagnostic: "waiting_for_owner_answer",
          },
        ],
        capabilities: {},
      };
    if (path === "execution/naukri/jobs") return { jobs: [] };
    if (path === "execution/questions")
      return [
        {
          id: "q-1",
          execution_id: "exec-1",
          employer: "Acme Corp",
          role: "Junior Backend Engineer",
          question: "When are you available for an interview?",
          state: "pending",
          answer_type: "availability",
          packet_revision: 7,
          expires_at: "2099-01-01T00:00:00Z",
          answer: null,
          reuse_approved: false,
          answer_expires_at: null,
        },
      ];
    throw Error(path);
  });

  mount();
  expect(await screen.findByText("Waiting for Your Answer")).toBeVisible();
  expect(
    screen.getByText(/When are you available for an interview\?/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Resume Application" }),
  ).not.toBeInTheDocument();

  const dateInput = screen.getByLabelText("Interview date, time and time zone");
  await userEvent.type(dateInput, "2026-11-15T10:00 Asia/Kolkata");

  const submitButton = screen.getByRole("button", {
    name: "Submit Answer from Dashboard",
  });
  await userEvent.click(submitButton);

  expect(post).toHaveBeenCalledWith("execution/questions/q-1/answer", {
    answer: "2026-11-15T10:00 Asia/Kolkata",
    expected_revision: 7,
  });
});

it("shows an observed session as historical evidence without claiming API access", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) => {
    const response = await original(path, options);
    return path === "execution/naukri"
      ? {
          ...(response as object),
          account_session: {
            state: "browser_session_observed",
            last_verification_time: "2026-10-29T12:00:00Z",
            evidence_type: "extension_gesture_dom_indicator",
          },
        }
      : response;
  });
  mount();
  expect(
    await screen.findByText(
      /does not verify account identity or a Naukri API connection/,
    ),
  ).toBeVisible();
  expect(screen.getByText(/This is a past observation/)).toBeVisible();
  expect(post).not.toHaveBeenCalled();
});

it("explains skill matches and unknown experience while refusing closed jobs", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "execution/naukri/jobs"
      ? {
          jobs: [
            {
              id: "fictional-job",
              title: "Fictional Backend Engineer",
              job_url:
                "https://www.naukri.com/job-listings-fictional-281026123456",
              vacancy_review: "closed",
              state: "REJECTED",
              reason: "closed",
              profile_version: 1,
              match: {
                match_score: 45,
                matched_skills: ["Python"],
                missing_skills: ["Rust"],
                unknown_fields: ["experience_suitability"],
                negative_factors: [],
                explanation: "Experience unknown; no seniority points awarded.",
              },
            },
          ],
        }
      : original(path, options),
  );
  mount();
  expect(
    await screen.findByText("Experience unknown; no seniority points awarded."),
  ).toBeVisible();
  expect(screen.getByText("Matched skills: Python")).toBeVisible();
  expect(screen.getByText("Missing skills: Rust")).toBeVisible();
  expect(screen.getByText("Unknown: experience_suitability")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Prepare selected job" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});

it("allows an explicit dashboard answer after uncertain Telegram delivery without resending", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "execution/questions"
      ? [
          {
            id: "q-unknown",
            execution_id: "exec-unknown",
            employer: "Fictional",
            role: "Backend Engineer",
            question: "Are you willing to attend an in-person interview?",
            state: "delivery_unknown",
            answer_type: "choice",
            options: ["Yes", "No"],
            queue_work_id: "existing-work",
            packet_revision: 2,
            expires_at: "2099-01-01T00:00:00Z",
            reuse_approved: false,
          },
        ]
      : original(path, options),
  );
  mount();
  expect(
    await screen.findByText(/this prompt will not be automatically resent/),
  ).toBeVisible();
  const submit = screen.getByRole("button", {
    name: "Submit Answer from Dashboard",
  });
  expect(submit).toBeDisabled();
  expect(screen.getByLabelText("Your verified answer")).toHaveValue("");
  expect(post).not.toHaveBeenCalled();
  await userEvent.selectOptions(
    screen.getByLabelText("Your verified answer"),
    "No",
  );
  await userEvent.click(submit);
  expect(post).toHaveBeenCalledExactlyOnceWith(
    "execution/questions/q-unknown/answer",
    { expected_revision: 2, answer: "No" },
  );
});
