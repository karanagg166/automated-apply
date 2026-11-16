import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Outreach, OutreachDetail } from "@/features/outreach";
import { api, patch, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}));
const id = "11111111-1111-4111-8111-111111111111";
let draft: any;
beforeEach(() => {
  vi.clearAllMocks();
  draft = {
    id,
    subject: "Fictional introduction",
    body: "Reviewed fictional message.",
    recipient_email: "target@example.com",
    draft_revision: 3,
    approval_status: "draft_created",
    delivery_status: "not_sent",
    created_at: "2026-01-01T00:00:00Z",
    outbound_messages_sent: 0,
    eligibility: { eligible_for_approval: true, blockers: [], warnings: [] },
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === `outreach/drafts/${id}`) return draft;
    if (path === "outreach/drafts?limit=100")
      return { drafts: [draft], total: 1 };
    if (path === "outreach/history")
      return {
        messages: [
          {
            id: "retained-attempt",
            status: "outcome_unknown",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      };
    if (path.startsWith("outreach/send-attempts/"))
      return {
        status: "outcome_unknown",
        reconciliation_required: true,
        attempted_at: "2026-01-01T00:00:00Z",
        accepted_at: null,
        rfc_message_id: "fictional-message@example.com",
        confirmation_token: "PRIVATE_CONFIRMATION_CANARY",
        approval_hash: "PRIVATE_HASH_CANARY",
      };
    if (path === "integrations/gmail/status")
      return {
        status: "connected",
        sending_enabled: true,
        send_capability: "send_authorized",
      };
    return {} as any;
  });
  vi.mocked(post).mockResolvedValue({});
  vi.mocked(patch).mockResolvedValue({});
});
function mount(detail = true) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {detail ? <OutreachDetail id={id} /> : <Outreach />}
    </QueryClientProvider>,
  );
}

it("preserves exact local approval while offering no send flow even when legacy status would authorize it", async () => {
  mount();
  const approve = await screen.findByRole("button", {
    name: "Approve exact content",
  });
  await waitFor(() => expect(approve).toBeEnabled());
  expect(screen.getByText("Reading and drafts only")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Gmail account and draft workspace" }),
  ).toHaveAttribute("href", "/connections");
  expect(
    screen.queryByRole("button", { name: /send/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalledWith("integrations/gmail/status");
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(approve);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`outreach/drafts/${id}/approve`, {
      expected_revision: 3,
    }),
  );
  expect(
    vi.mocked(post).mock.calls.every(([path]) => path.endsWith("/approve")),
  ).toBe(true);
});

it("preserves an uncertain historical attempt and renders useful evidence without raw internal fields", async () => {
  draft.send_attempt_id = "retained-attempt";
  mount();
  await screen.findByText("Manual reconciliation is required.");
  expect(screen.getByLabelText("Subject")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Approve exact content" }),
  ).toBeDisabled();
  expect(
    screen.getByText("Message reference: fictional-message@example.com"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Provider acceptance recorded: Not observed"),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/PRIVATE_CONFIRMATION_CANARY|PRIVATE_HASH_CANARY/),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
});

it("keeps the local draft list and historical uncertainty visible under the read and draft policy", async () => {
  mount(false);
  await screen.findByText("Fictional introduction");
  expect(screen.getByText(/Sending is disabled\./)).toBeInTheDocument();
  expect(await screen.findByText("outcome unknown")).toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});
