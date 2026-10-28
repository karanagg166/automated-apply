import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import {
  ConnectedEmails,
  type ReadAccount,
  type JobEmailEvidence,
} from "@/features/connected-emails";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const first = "11111111-1111-4111-8111-111111111111",
  second = "22222222-2222-4222-8222-222222222222",
  evidenceId = "a".repeat(32);
const accounts: ReadAccount[] = [first, second].map((id, index) => ({
  id,
  account_email: `${index ? "second" : "first"}@example.org`,
  granted_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
  status: "connected",
  permissions: {
    read_metadata: true,
    read_body: false,
    send: false,
    modify: false,
  },
  sync_enabled: true,
  body_access_reviewed: false,
  sync: {
    version: 1,
    status: "ready",
    policy: {
      enabled: true,
      sender_allowlist: [],
      label_allowlist: ["Label_Jobs"],
      query_allowlist: null,
      read_body: false,
      body_purpose: null,
      backfill_days: 7,
      retention_days: 14,
      max_pages: 1,
    },
  },
}));
const record: JobEmailEvidence = {
  id: evidenceId,
  account_id: first,
  message_id: "msg-first",
  thread_id: "thread-first",
  received_at: "2026-10-28T00:00:00Z",
  observed_at: "2026-10-28T00:00:00Z",
  expires_at: "2026-11-10T00:00:00Z",
  verification_status: "requires_review",
  submission_confirmed: false,
  links: ["https://jobs.example.org/posting"],
  signals: ["possible_job_lead"],
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ConnectedEmails />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "integrations/gmail/accounts")
      return { accounts, workflow: "readonly", schema_ready: true } as any;
    if (path.endsWith("/evidence"))
      return { evidence: path.includes(first) ? [record] : [] } as any;
    if (path.endsWith("/leads"))
      return {
        leads: path.includes(first)
          ? [
              {
                id: "lead-first",
                url: record.links[0],
                evidence_ids: [evidenceId],
                verification_status: "requires_review",
                confirmed_vacancy: false,
              },
            ]
          : [],
      } as any;
    return {} as any;
  });
});
it("renders actual account_email and selected string links with source attribution", async () => {
  mount();
  expect(
    await screen.findByRole("heading", { name: "first@example.org" }),
  ).toBeInTheDocument();
  const evidence = await screen.findByRole("region", {
    name: "Evidence from first@example.org",
  });
  expect(within(evidence).getByText(/msg-first/)).toBeInTheDocument();
  expect(
    within(evidence).getByRole("link", {
      name: "Inspect retained source link",
    }),
  ).toHaveAttribute("href", record.links[0]);
  expect(screen.queryByText(/unknown sender|No subject header/)).toBeNull();
  expect(
    screen.getByRole("region", { name: "Evidence from second@example.org" }),
  ).not.toHaveTextContent("msg-first");
});
it("shows HTTP 200 schema_ready:false as setup unavailable and disables connecting", async () => {
  vi.mocked(api).mockResolvedValue({
    accounts: [],
    workflow: "readonly",
    schema_ready: false,
    error_code: "gmail_readonly_schema_update_required",
  } as any);
  mount();
  expect(
    await screen.findByText("Read-only Gmail setup required"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Connect secondary account" }),
  ).toBeDisabled();
});
it("configures account-scoped policy with its actual version and no scheduling claim", async () => {
  mount();
  await screen.findByRole("heading", { name: "first@example.org" });
  await userEvent.click(
    screen.getAllByRole("button", { name: "Configure read policy" })[0],
  );
  const dialog = await screen.findByRole("dialog");
  expect(dialog).not.toHaveTextContent("scheduled");
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Save policy" }),
  );
  expect(api).toHaveBeenCalledWith(
    `integrations/gmail/accounts/${first}/selection`,
    expect.objectContaining({
      method: "PUT",
      body: expect.stringContaining('"expected_version":1'),
    }),
  );
});
it("requires owner-supplied job title and reviewed evidence before a scoped import", async () => {
  vi.mocked(post).mockResolvedValue({ inserted: 1 });
  mount();
  await userEvent.click(
    await screen.findByRole("button", { name: "Review lead for import" }),
  );
  const dialog = await screen.findByRole("dialog");
  const button = within(dialog).getByRole("button", {
    name: "Import reviewed lead",
  });
  expect(button).toBeDisabled();
  await userEvent.type(
    within(dialog).getByLabelText("Actual job title"),
    "Backend Engineer",
  );
  expect(button).toBeDisabled();
  await userEvent.click(within(dialog).getByRole("checkbox"));
  await userEvent.click(button);
  expect(post).toHaveBeenCalledWith(
    `integrations/gmail/accounts/${first}/evidence/${evidenceId}/import`,
    {
      job_url: record.links[0],
      title: "Backend Engineer",
      company_name: null,
      reviewed_job_evidence: true,
    },
  );
});
it("filters account evidence without leaking another mailbox and scopes sync", async () => {
  mount();
  await screen.findByRole("heading", { name: "first@example.org" });
  await userEvent.selectOptions(
    screen.getByLabelText("Filter by account"),
    second,
  );
  expect(
    await screen.findByRole("region", {
      name: "Evidence from second@example.org",
    }),
  ).not.toHaveTextContent("msg-first");
  expect(
    screen.queryByRole("region", { name: "Evidence from first@example.org" }),
  ).toBeNull();
  await userEvent.click(screen.getAllByRole("button", { name: "Sync now" })[1]);
  expect(post).toHaveBeenCalledWith(
    `integrations/gmail/accounts/${second}/sync`,
  );
});
it("has no send, modify, archive, delete or compose operation", async () => {
  mount();
  await screen.findByRole("heading", { name: "first@example.org" });
  for (const name of [
    /^send/i,
    /^modify/i,
    /^archive/i,
    /^delete/i,
    /^compose/i,
  ])
    expect(screen.queryByRole("button", { name })).toBeNull();
  expect(post).not.toHaveBeenCalled();
});
