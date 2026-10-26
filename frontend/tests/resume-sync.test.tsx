import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
import { ResumeSync } from "@/features/resume-sync";
import { ResumeReview } from "@/features/resume-review";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const source =
  "https://drive.google.com/file/d/fictional_drive_resume_001/view?usp=drivesdk";
const version: Schema<"ResumeVersionRead"> = {
  id: "11111111-1111-4111-8111-111111111111",
  private_resume_id: "22222222-2222-4222-8222-222222222222",
  file_id: "fictional_drive_resume_001",
  canonical_url: source,
  file_name: "fictional_resume.pdf",
  sha256: "a".repeat(64),
  downloaded_at: "2026-01-01T00:00:00Z",
  source_modified_at: null,
  source_etag: null,
  drive_revision: null,
  review_status: "pending",
  review_cycle: 1,
  candidate_profile_version: 1,
  approved_profile_version: null,
};
const state: Schema<"SyncStatus"> = {
  file_name: null,
  last_downloaded_at: null,
  source_modified_at: null,
  source_etag: null,
  drive_revision: null,
  metadata_note:
    "Drive revision metadata may be unavailable; every check verifies PDF SHA-256.",
  source: "Google Drive",
  canonical_url: source,
  file_id: version.file_id,
  generation: 1,
  connected: false,
  status: "not_checked",
  sync_enabled: false,
  interval_hours: 24,
  requires_review: true,
  last_error: null,
  last_checked_at: null,
  last_changed_at: null,
  latest: null,
  active: null,
  history: [],
  pending_changes: false,
  scheduler_active: false,
  scheduler_message:
    "Automatic periodic checking is inactive. Deploy and run the resume check worker.",
};
const review: Schema<"ResumeReviewRead"> = {
  version,
  expected_generation: 1,
  expected_profile_version: 1,
  current_profile: {
    full_name: "Alex Example",
    email: "alex@example.org",
    verified_skills: ["Python", "FastAPI"],
  },
  proposed_profile: {
    full_name: "Alex Example",
    email: "alex@example.org",
    verified_skills: ["Python", "FastAPI", "Docker"],
  },
  suggested_identity: {
    full_name: "Alex Example",
    email: "alex@example.org",
    verified_skills: ["Python", "Docker"],
  },
  differences: [
    {
      category: "skills",
      current_verified: ["Python", "FastAPI"],
      before: ["Python", "FastAPI"],
      after: ["Python", "Docker"],
      added: ["Docker"],
      removed: ["FastAPI"],
    },
  ],
  text: "Alex Example\nPython Docker",
  warnings: ["Every claim requires owner review."],
  stale_answer_count: 2,
  stale_packet_count: 1,
};
function mount(component: React.ReactNode) {
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
      {component}
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(post).mockReset();
  vi.mocked(post).mockResolvedValue({});
});

it("does not show a connected source before fetching or imply the flag starts a scheduler", async () => {
  vi.mocked(api).mockResolvedValue({ ...state, sync_enabled: true });
  mount(<ResumeSync />);
  expect(
    await screen.findByText("Awaiting successful validation"),
  ).toBeVisible();
  expect(
    screen.getByText(/Automatic periodic checking is inactive/),
  ).toBeVisible();
  expect(screen.queryByText("Fetched and validated")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Review Changes" })).toBeDisabled();
});

it("defers live Drive download and directs the owner to manual PDF upload", async () => {
  vi.mocked(api).mockResolvedValue(state);
  mount(<ResumeSync />);
  expect(
    await screen.findByRole("button", { name: "Sync Now" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Google Drive OAuth and live PDF download are deferred/),
  ).toBeVisible();
  expect(post).not.toHaveBeenCalled();
});

it("preserves the active version while surfacing pending changes and access failures", async () => {
  vi.mocked(api).mockResolvedValue({
    ...state,
    status: "failed",
    last_error: "access_denied_or_revoked",
    latest: version,
    active: {
      ...version,
      id: "33333333-3333-4333-8333-333333333333",
      sha256: "b".repeat(64),
      review_status: "approved",
    },
    history: [version],
    pending_changes: true,
  });
  mount(<ResumeSync />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "access denied or revoked",
  );
  expect(screen.getByText(/fictional_resume.pdf · bbbbbbbbbbbb/)).toBeVisible();
  expect(screen.getByText(/Pending changes need your review/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Review Changes" })).toBeEnabled();
});

it("requires owner review, retains confirmed skills and sends exact edited facts", async () => {
  vi.mocked(api).mockResolvedValue(review);
  const close = vi.fn();
  mount(<ResumeReview versionId={version.id} onClose={close} />);
  const button = await screen.findByRole("button", {
    name: "Approve New Resume Version",
  });
  expect(button).toBeDisabled();
  expect(screen.getByLabelText("Reviewed skills")).toHaveValue(
    "Python, FastAPI, Docker",
  );
  const checkbox = screen.getByRole("checkbox", { name: /I reviewed the PDF/ });
  await userEvent.click(checkbox);
  await userEvent.clear(screen.getByLabelText("Reviewed full name"));
  await userEvent.type(
    screen.getByLabelText("Reviewed full name"),
    "Alex Reviewed",
  );
  await userEvent.type(screen.getByLabelText("Reviewed skills"), ", Redis");
  expect(button).toBeDisabled();
  await userEvent.click(checkbox);
  await userEvent.click(button);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `dashboard/resume-sync/versions/${version.id}/approve`,
      expect.objectContaining({
        owner_confirmed: true,
        expected_generation: 1,
        expected_profile_version: 1,
        profile: expect.objectContaining({
          full_name: "Alex Reviewed",
          verified_skills: ["Python", "FastAPI", "Docker", "Redis"],
        }),
        allow_skill_removals: false,
      }),
    ),
  );
  await waitFor(() => expect(close).toHaveBeenCalled());
});

it("saves explicit source changes with opt-in settings and no automatic download", async () => {
  vi.mocked(api).mockResolvedValue(state);
  mount(<ResumeSync />);
  await userEvent.click(
    await screen.findByRole("button", {
      name: "Change Resume Source / Settings",
    }),
  );
  const field = screen.getByLabelText("Canonical Google Drive resume URL");
  await userEvent.clear(field);
  const changed = source.replace("001", "002");
  await userEvent.type(field, changed);
  await userEvent.click(
    screen.getByRole("button", { name: "Save resume source settings" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "dashboard/resume-sync/source",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          canonical_url: changed,
          expected_generation: 1,
          sync_enabled: false,
          interval_hours: 24,
        }),
      }),
    ),
  );
  expect(post).not.toHaveBeenCalled();
});
