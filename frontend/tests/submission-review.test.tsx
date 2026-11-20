import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { SubmissionReview } from "@/features/submission-review";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const id = "11111111-1111-4111-8111-111111111111";
const submission = {
  application_id: id,
  job_id: "job-2",
  employer: "Fictional Employer",
  job_title: "Backend Engineer",
  application_url: "http://127.0.0.1:18765/fixtures/lever/example/jobs/2/apply",
  origin: "http://127.0.0.1:18765",
  request_url:
    "http://127.0.0.1:18765/fixtures/lever/example/jobs/2/applications",
  state: "awaiting_submission_approval",
  candidate_version: 2,
  packet_revision: 3,
  campaign_revision: 4,
  review_digest: "a".repeat(64),
  pdf_digest: "b".repeat(64),
  document_digest: "c".repeat(64),
  project_digest: "d".repeat(64),
  nonce: "nonce",
  expires_at: "2099-01-01T00:00:00Z",
  authorization: null,
  released: false,
  evidence: null,
};
function mount(data = submission, historyOnly = false) {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue([data]);
  vi.mocked(post).mockResolvedValue({});
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SubmissionReview historyOnly={historyOnly} />
    </QueryClientProvider>,
  );
}
it("shows retained uncertain evidence without exposing fixture write controls on Rust", async () => {
  mount({ ...submission, state: "submission_uncertain" }, true);
  expect(
    await screen.findByRole("heading", { name: "Saved submission history" }),
  ).toBeVisible();
  expect(await screen.findByText("Submission uncertain")).toBeVisible();
  expect(
    screen.queryByRole("button", {
      name: /check receipt|stop the remaining|authorize|submit this/i,
    }),
  ).toBeNull();
  expect(post).not.toHaveBeenCalled();
});
it("requires exact reviewed employer, URL and application selection before authorization", async () => {
  mount();
  const authorize = await screen.findByRole("button", {
    name: "Authorize this one application",
  });
  expect(authorize).toBeDisabled();
  expect(screen.getByText(`Selected application: ${id}`)).toBeVisible();
  expect(
    screen.getByText(`Application URL: ${submission.application_url}`),
  ).toBeVisible();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(authorize);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`browser/submissions/${id}/approve`, {
      nonce: "nonce",
      review_digest: "a".repeat(64),
      campaign_revision: 4,
      application_ids: [id],
      maximum_count: 1,
      scope: "submit_application",
    }),
  );
  expect(
    screen.queryByRole("button", { name: "Submit this approved application" }),
  ).toBeNull();
});
it("exposes read-only reconciliation and no submit control for uncertain outcomes", async () => {
  mount({ ...submission, state: "submission_uncertain" });
  expect(await screen.findByText("Submission uncertain")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Authorize this|Submit this/ }),
  ).toBeNull();
  await userEvent.click(
    screen.getByRole("button", { name: "Check receipt without resubmitting" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`browser/submissions/${id}/reconcile`),
  );
});
it("allows only fixed submission review controls through the owner gateway", () => {
  for (const action of ["approve", "execute", "reconcile"])
    expect(permittedRoute(`browser/submissions/${id}/${action}`, "POST")).toBe(
      true,
    );
  expect(permittedRoute("browser/submissions/stop", "POST")).toBe(true);
  for (const path of [
    "browser/submit_application",
    `browser/submissions/${id}/javascript`,
    `browser/submissions/${id}/retry`,
    "browser/submissions/../../execute",
  ])
    expect(permittedRoute(path, "POST")).toBe(false);
});
