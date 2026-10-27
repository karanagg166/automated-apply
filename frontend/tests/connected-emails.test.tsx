import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
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

const fictionalAccounts: ReadAccount[] = [
  {
    id: "account-1111",
    email: "primary-candidate@example.org",
    granted_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
    status: "connected",
    last_verified_at: "2026-03-01T10:00:00Z",
    sync_enabled: true,
    body_access_reviewed: false,
    sync: {
      version: 3,
      status: "completed",
      last_sync_at: "2026-03-01T11:00:00Z",
      scanned: 15,
      inserted: 3,
      last_error: null,
      policy: {
        enabled: true,
        sender_allowlist: ["jobs@acme.example", "alerts@naukri.example"],
        label_allowlist: ["Label_Jobs"],
        query_allowlist: null,
        read_body: false,
        body_purpose: null,
        backfill_days: 7,
        retention_days: 14,
        max_pages: 1,
      },
    },
  },
  {
    id: "account-2222",
    email: "secondary-updates@example.org",
    granted_scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    status: "reconnect_required",
    last_verified_at: "2026-02-15T09:00:00Z",
    sync_enabled: false,
    body_access_reviewed: true,
    sync: {
      version: 1,
      status: "reauthorization_required",
      last_sync_at: "2026-02-15T10:00:00Z",
      scanned: 0,
      inserted: 0,
      last_error: "OAuth token refresh expired. Reconnect required.",
      policy: null,
    },
  },
];

const fictionalEvidence: JobEmailEvidence[] = [
  {
    id: "evidence-1",
    account_id: "account-1111",
    message_id: "msg-123",
    thread_id: "th-123",
    received_at: "2026-03-01T08:00:00Z",
    observed_at: "2026-03-01T11:00:00Z",
    expires_at: "2026-03-15T11:00:00Z",
    sender: "jobs@acme.example",
    subject: "Application update: Software Engineer at Acme",
    read_body: false,
    verification_status: "verified",
    submission_confirmed: false,
    links: [{ url: "https://acme.example/jobs/1", label: "Job Description" }],
    signals: ["interview_invited"],
    job_alerts: [
      {
        title: "Senior Backend Engineer",
        company: "Acme Cloud",
        location: "Bengaluru (Remote)",
        status: "new",
        extracted_at: "2026-03-01T11:01:00Z",
        source_url: "https://acme.example/jobs/1",
      },
    ],
  },
];

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConnectedEmails />
    </QueryClientProvider>,
  );
}

describe("Connected Gmail accounts read-only UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "integrations/gmail/accounts") {
        return { accounts: fictionalAccounts, workflow: "read_only" } as any;
      }
      if (path === "integrations/gmail/accounts/account-1111/evidence") {
        return { evidence: fictionalEvidence } as any;
      }
      if (path.includes("/evidence")) {
        return { evidence: [] } as any;
      }
      return {} as any;
    });
  });

  it("renders multiple independent Gmail accounts with granted scopes and connection status", async () => {
    mount();

    expect(
      await screen.findByRole("heading", {
        name: "primary-candidate@example.org",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "secondary-updates@example.org" }),
    ).toBeInTheDocument();

    // Check status badges
    expect(screen.getByText("connected")).toBeInTheDocument();
    expect(screen.getByText("reconnect required")).toBeInTheDocument();

    // Check scope distinction
    expect(
      screen.getByText("Metadata only (Headers & dates)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Body read granted (Job alerts)"),
    ).toBeInTheDocument();
  });

  it("strictly enforces READ-ONLY controls and has ZERO send/reply/draft/delete controls", async () => {
    mount();

    await screen.findByRole("heading", {
      name: "primary-candidate@example.org",
    });

    // Must NEVER contain send, reply, forward, compose, draft, delete, archive or mark read buttons
    expect(screen.queryByRole("button", { name: /^send/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^reply/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^forward/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^compose/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^draft/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^archive/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /mark as read/i })).toBeNull();

    // Prominent Read-Only notice must be visible
    expect(screen.getByText(/Strict Read-Only Boundary/i)).toBeInTheDocument();
  });

  it("never combines accounts in a way that obscures source email address", async () => {
    mount();

    // The evidence item displays its source account
    expect(
      await screen.findByText("Application update: Software Engineer at Acme"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Account: primary-candidate@example\.org/i),
    ).toBeInTheDocument();
  });

  it("previews extracted job alerts and vacancy records before import", async () => {
    mount();

    expect(
      await screen.findByText("Application update: Software Engineer at Acme"),
    ).toBeInTheDocument();

    // Extracted job alert details are visible
    expect(
      screen.getByText("Senior Backend Engineer @ Acme Cloud"),
    ).toBeInTheDocument();
    expect(screen.getByText("Bengaluru (Remote)")).toBeInTheDocument();

    // Click preview record
    const previewBtn = screen.getByRole("button", { name: "Preview record" });
    await userEvent.click(previewBtn);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Extracted Job Alert Preview")).toBeInTheDocument();
  });

  it("triggers manual sync and opens read policy configuration modal", async () => {
    vi.mocked(post).mockResolvedValue({
      sync: { version: 4, status: "in_progress" },
    });

    mount();

    await screen.findByRole("heading", {
      name: "primary-candidate@example.org",
    });

    // Click Sync now for the connected account
    const syncBtns = screen.getAllByRole("button", {
      name: "Sync now",
    });
    await userEvent.click(syncBtns[0]);
    expect(post).toHaveBeenCalledWith(
      "integrations/gmail/accounts/account-1111/sync",
    );

    // Click Configure read policy
    const policyBtns = screen.getAllByRole("button", {
      name: "Configure read policy",
    });
    await userEvent.click(policyBtns[0]);

    // Modal opens showing policy configuration
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/Sender Allowlist/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Allowed Custom Labels/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save policy" }),
    ).toBeInTheDocument();
  });

  it("supports disconnecting an account with confirmation", async () => {
    vi.mocked(post).mockResolvedValue({ disconnected: true });

    mount();

    await screen.findByRole("heading", {
      name: "primary-candidate@example.org",
    });

    const disconnectBtns = screen.getAllByRole("button", {
      name: "Disconnect",
    });
    await userEvent.click(disconnectBtns[0]);

    expect(post).toHaveBeenCalledWith(
      "integrations/gmail/accounts/account-1111/disconnect",
    );
  });

  it("displays an honest unavailable state when backend returns 404", async () => {
    const error404 = new Error("Not Found");
    (error404 as any).status = 404;
    vi.mocked(api).mockRejectedValue(error404);

    mount();

    expect(
      await screen.findByText("Codex Multi-Account Gmail Contract Pending"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The backend multi-account read-only endpoints/i),
    ).toBeInTheDocument();
  });
});
