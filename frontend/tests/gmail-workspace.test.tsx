import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import { GmailWorkspace } from "@/features/gmail-workspace";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
vi.mock("@/features/connected-emails", () => ({
  ConnectedEmails: () => <div>Existing job-alert lead review</div>,
}));
const base = "integrations/gmail/workspace";
const aid = "11111111-1111-4111-8111-111111111111";
let accounts: any[], drafts: any[], history: any[];
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <GmailWorkspace />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  accounts = [
    { slot: "read_1", status: "not_connected" },
    { slot: "read_2", status: "not_connected" },
    { slot: "outreach", status: "not_connected", drafts_enabled: false },
  ];
  drafts = [];
  history = [];
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === `${base}/accounts`)
      return { schema_ready: true, accounts } as any;
    if (path === `${base}/drafts`) return { drafts } as any;
    if (path === `${base}/history`) return { history } as any;
    if (path.endsWith("/evidence")) return { evidence: [] } as any;
    return {} as any;
  });
  vi.mocked(post).mockResolvedValue({});
});

it("offers three independent OAuth choices without asking for an email or starting OAuth", async () => {
  mount();
  await screen.findByText("Account 1 · Read only");
  expect(screen.getByText("Account 2 · Read only")).toBeInTheDocument();
  expect(
    screen.getByText("Account 3 · Outreach drafts only"),
  ).toBeInTheDocument();
  const cards = screen.getAllByRole("article");
  expect(cards).toHaveLength(3);
  expect(
    within(cards[0]).getByRole("button", { name: "Connect with Google" }),
  ).toBeDisabled();
  fireEvent.click(
    within(cards[0]).getByRole("checkbox", {
      name: "Authorize this account for read-only metadata access",
    }),
  );
  expect(
    within(cards[0]).getByRole("button", { name: "Connect with Google" }),
  ).toBeEnabled();
  expect(
    within(cards[1]).getByRole("button", { name: "Connect with Google" }),
  ).toBeDisabled();
  expect(within(cards[0]).queryByRole("textbox")).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it("saves the selected historical window and folders without scanning automatically", async () => {
  accounts[0] = {
    slot: "read_1",
    id: aid,
    status: "connected",
    sync_enabled: true,
    sync: { version: 0, status: "selection_required", policy: null },
  };
  mount();
  const card = (await screen.findByText("Account 1 · Read only")).closest(
    "article",
  )!;
  expect(
    within(card).getByLabelText("Historical lookback (months, maximum 24)"),
  ).toHaveValue(24);
  expect(within(card).getByLabelText("Inbox")).toBeChecked();
  expect(within(card).getByLabelText("Sent Mail")).toBeChecked();
  expect(
    within(card).getByRole("button", { name: "Scan next batch (up to 25)" }),
  ).toBeDisabled();
  fireEvent.click(
    within(card).getByLabelText("Enable this reviewed scan selection"),
  );
  fireEvent.change(
    within(card).getByLabelText("Optional custom label IDs, comma separated"),
    { target: { value: "Label_jobs" } },
  );
  fireEvent.click(
    within(card).getByRole("button", { name: "Save account settings" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `integrations/gmail/accounts/${aid}/selection`,
      expect.anything(),
    ),
  );
  const call = vi
    .mocked(api)
    .mock.calls.find((c) => c[0].endsWith("/selection"))!;
  expect(JSON.parse(call[1]!.body as string)).toMatchObject({
    folders: ["INBOX", "SENT"],
    history_months: 24,
    retention_days: 14,
    max_pages: 1,
    retain_metadata: true,
    read_body: false,
    label_allowlist: ["Label_jobs"],
  });
  expect(post).not.toHaveBeenCalled();
});

it("requires exact draft review, blocks dirty edits and never exposes a send operation", async () => {
  accounts[2] = { slot: "outreach", status: "connected", drafts_enabled: true };
  drafts = [
    {
      id: "a".repeat(32),
      version: 1,
      content_hash: "b".repeat(64),
      status: "local_draft",
      company: "Fictional Team",
      role: "Engineer",
      content: {
        recipient: "founder@fictional.example",
        subject: "Reviewed opportunity",
        body: "Reviewed candidate message",
      },
    },
  ];
  mount();
  const subject = await screen.findByLabelText("Draft subject");
  const save = screen.getByRole("button", {
    name: "Save reviewed draft in Gmail",
  });
  expect(save).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "I reviewed this exact recipient, subject and message",
    ),
  );
  expect(save).toBeEnabled();
  fireEvent.change(subject, { target: { value: "Edited subject" } });
  expect(save).toBeDisabled();
  expect(
    screen.getByLabelText(
      "I reviewed this exact recipient, subject and message",
    ),
  ).not.toBeChecked();
  expect(
    screen.queryByRole("button", { name: /^send/i }),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it("distinguishes confirmed history and keeps its retention separate", async () => {
  history = [
    {
      id: "a".repeat(32),
      version: 1,
      company: "Reviewed Team",
      role: "Engineer",
      applied_at: "2026-10-01T00:00:00Z",
      confirmed_application: true,
      status: "interview",
      retention_days: 365,
      evidence: { [aid]: ["a".repeat(32)] },
    },
    {
      id: "c".repeat(32),
      version: 1,
      company: "Uncertain Team",
      role: "Engineer",
      applied_at: "2026-10-02T00:00:00Z",
      confirmed_application: false,
      status: "uncertain",
      retention_days: 60,
      evidence: { [aid]: ["b".repeat(32)] },
    },
  ];
  mount();
  expect(await screen.findByText("Confirmed application")).toBeInTheDocument();
  expect(screen.getByText("Uncertain evidence")).toBeInTheDocument();
  expect(
    screen.getAllByLabelText("Change structured history retention (days)")[0],
  ).toHaveValue(365);
  expect(post).not.toHaveBeenCalled();
});

it("offers explicit read-only reconciliation of an uncertain draft without editable content or automatic action", async () => {
  accounts[2] = {
    slot: "outreach",
    status: "connected",
    drafts_enabled: true,
    generation: 2,
  };
  drafts = [
    {
      id: "a".repeat(32),
      version: 1,
      content_hash: "b".repeat(64),
      status: "unknown",
      company: "Fictional Co",
      role: "Rust",
      unconfirmed_gmail_draft_id: "fictional-draft",
      content: {
        recipient: "target@example.com",
        subject: "Reviewed subject",
        body: "Reviewed message",
      },
    },
  ];
  mount();
  const check = await screen.findByRole("button", {
    name: "Check for existing Gmail draft",
  });
  expect(check).toBeDisabled();
  expect(screen.getByLabelText("Draft message")).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Save draft edits locally" }),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "I reviewed this exact recipient, subject and message",
    }),
  );
  fireEvent.click(check);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `${base}/drafts/${"a".repeat(32)}/create-in-gmail`,
      {
        expected_version: 1,
        content_hash: "b".repeat(64),
        expected_account_generation: 2,
        owner_reviewed: true,
      },
    ),
  );
});

it("labels a retained historical draft reference separately from verified content", async () => {
  drafts = [
    {
      id: "a".repeat(32),
      version: 1,
      content_hash: "b".repeat(64),
      status: "saved_in_gmail",
      company: "Fictional Co",
      role: "Rust",
      gmail_draft_id: "historical-draft",
      content: {
        recipient: "target@example.com",
        subject: "Retained subject",
        body: "Retained message",
      },
    },
  ];
  mount();
  await screen.findByText(
    "Saved draft reference retained. Open Gmail to review its current contents.",
  );
  expect(
    screen.queryByText(
      "Draft content verified in Gmail. Open Gmail to review or edit it.",
    ),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it("allows only fixed account/history/draft routes and denies send/write operations", () => {
  expect(permittedRoute(`${base}/accounts/read_1/connect`, "POST")).toBe(true);
  expect(
    permittedRoute(`${base}/drafts/${"a".repeat(32)}/create-in-gmail`, "POST"),
  ).toBe(true);
  for (const op of [
    "send",
    "reply",
    "archive",
    "delete",
    "modify",
    "mark-read",
  ]) {
    expect(permittedRoute(`${base}/accounts/read_1/${op}`, "POST")).toBe(false);
    expect(
      permittedRoute(`${base}/drafts/${"a".repeat(32)}/${op}`, "POST"),
    ).toBe(false);
  }
});
