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
    screen.getByRole("button", { name: "Resume Application" }),
  ).toBeVisible();

  const dateInput = screen.getByLabelText("Interview date");
  await userEvent.type(dateInput, "2026-11-15");

  const submitButton = screen.getByRole("button", {
    name: "Submit Answer from Dashboard",
  });
  await userEvent.click(submitButton);

  expect(post).toHaveBeenCalledWith("execution/questions/q-1/answer", {
    answer: "2026-11-15T10:00 Asia/Kolkata",
  });
});
