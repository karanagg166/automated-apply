import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProofDrawer, lagLabel, tierTone } from "@/features/proof-drawer";
import { groupByStage, stageOf } from "@/features/pipeline-board";
import { api, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const ID = "11111111-1111-4111-8111-111111111111";
const CACHE_ID = "33333333-3333-4333-8333-333333333333";
const proof = (state = "APPLIED") => ({
  application: {
    id: ID,
    platform: "greenhouse",
    external_job_id: "gh-1",
    company_name: "Stripe",
    role_title: "Backend Engineer",
    job_url: "https://boards.greenhouse.io/stripe/jobs/1",
    state,
  },
  timing: {
    posted_at: "2026-11-27T04:00:00Z",
    discovered_at: "2026-11-27T04:05:00Z",
    queued_at: "2026-11-27T04:05:10Z",
    started_at: "2026-11-27T04:06:00Z",
    submitted_at: "2026-11-27T04:07:00Z",
    first_mover_lag_seconds: 420,
  },
  answers: [
    {
      question: "Years of Python?",
      answer: "1",
      source: "profile",
      tier_label: "Tier 1 Fact",
    },
    {
      question: "Willing to relocate?",
      answer: "Yes",
      source: "semantic_cache",
      tier_label: "Tier 3 Semantic 0.96",
      similarity: 0.96,
      cache_entry_id: CACHE_ID,
    },
    {
      question: "Notice period?",
      answer: "Immediate",
      source: "llm",
      tier_label: "Tier 4 LLM",
    },
  ],
  resume_variant_used: "backend",
  screenshot: "receipts/gh-1.png",
  mail_events: [
    {
      kind: "CONFIRMATION",
      subject: "Thanks for applying",
      sender: "no-reply@greenhouse.io",
      received_at: "2026-11-27T04:08:00Z",
    },
  ],
  outreach_draft: null,
  email_verified: true,
  confirmed_at: "2026-11-27T04:08:00Z",
  needs_reconciliation: state === "SUBMISSION_UNKNOWN",
});

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

it("formats lag, tones and funnel stages", () => {
  expect(lagLabel(420)).toBe("7m 0s");
  expect(lagLabel(null)).toBe("—");
  expect(tierTone("Tier 1 Fact")).toBe("green");
  expect(tierTone("Tier 4 LLM")).toBe("amber");
  const row = {
    id: "x",
    platform: "lever",
    external_job_id: "1",
    state: "APPLIED",
    attempts: 0,
    email_verified: false,
  };
  expect(stageOf(row)).toBe("applied");
  expect(stageOf({ ...row, email_verified: true })).toBe("verified");
  expect(stageOf({ ...row, reason: "verified_by_confirmation_email" })).toBe(
    "verified",
  );
  expect(stageOf({ ...row, funnel_stage: "INTERVIEW_INVITE" })).toBe(
    "interview",
  );
  expect(stageOf({ ...row, state: "SCORED" })).toBe("queued");
  expect(stageOf({ ...row, state: "FILTERED_OUT" })).toBe("closed");
  expect(groupByStage([row]).applied).toHaveLength(1);
});

it("renders timing, tier badges and quarantines a flagged cached answer", async () => {
  const user = userEvent.setup();
  vi.mocked(api).mockResolvedValue(proof());
  vi.mocked(post).mockResolvedValue({});
  const onClose = vi.fn();
  mount(<ProofDrawer applicationId={ID} onClose={onClose} />);
  const dialog = await screen.findByRole("dialog", {
    name: "Stripe — Backend Engineer",
  });
  expect(api).toHaveBeenCalledWith(`v2/applications/${ID}/proof`);
  expect(
    within(dialog).getByText("First-mover lag").nextSibling,
  ).toHaveTextContent("7m 0s");
  expect(within(dialog).getByText("Tier 1 Fact")).toBeInTheDocument();
  expect(within(dialog).getByText("Tier 3 Semantic 0.96")).toBeInTheDocument();
  expect(within(dialog).getByText("Tier 4 LLM")).toBeInTheDocument();
  expect(within(dialog).getByText("backend")).toBeInTheDocument();
  expect(within(dialog).getByText("Thanks for applying")).toBeInTheDocument();
  // only the cached answer can be flagged
  expect(
    within(dialog).getAllByRole("button", { name: /Flag bad answer/ }),
  ).toHaveLength(1);
  await user.click(
    within(dialog).getByRole("button", {
      name: "Flag bad answer and quarantine: Willing to relocate?",
    }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `v2/semantic-cache/${CACHE_ID}/quarantine`,
      {
        reason: "flagged_from_receipt",
      },
    ),
  );
  expect(await within(dialog).findByText("Quarantined")).toBeInTheDocument();
  expect(
    within(dialog).queryByText(/Reconcile unknown submission/),
  ).not.toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

it("requires typed RELEASE before releasing an unknown submission", async () => {
  const user = userEvent.setup();
  vi.mocked(api).mockResolvedValue(proof("SUBMISSION_UNKNOWN"));
  vi.mocked(post).mockResolvedValue({});
  mount(<ProofDrawer applicationId={ID} onClose={() => {}} />);
  const release = await screen.findByRole("button", {
    name: "Release: not submitted",
  });
  expect(release).toBeDisabled();
  await user.type(screen.getByLabelText(/Type RELEASE/), "RELEASE");
  await user.click(release);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/applications/${ID}/reconcile`, {
      action: "release_not_submitted",
      confirm: "RELEASE",
    }),
  );
});
