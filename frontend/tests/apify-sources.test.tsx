import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import { ApifySourceManagement } from "@/features/apify-sources";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ApifySourceManagement />
    </QueryClientProvider>,
  );
}

describe("Apify source & actor management", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "discovery/sources") {
        return {
          sources: [
            {
              id: "apify-web",
              platform: "apify",
              enabled: true,
              mode: "public_lookup",
              schedule: "manual",
              filter_defaults: { keywords: ["Python"], locations: ["India"] },
            },
          ],
        } as any;
      }
      if (path === "dashboard/connections") {
        return {
          providers: [
            {
              provider: "apify",
              configured: true,
              authorized: true,
              live_verified: true,
              capability: "discovery",
              budget: 4.5,
              next_action: "ready",
            },
          ],
        } as any;
      }
      return {} as any;
    });
  });

  it("displays provider account quota, cost limits, and actor catalog", async () => {
    mount();

    // Verify main headings and quota metrics once queries resolve
    expect(
      await screen.findByText("Configured & Authorized"),
    ).toBeInTheDocument();
    expect(screen.getByText("LOCAL BUDGET CAP")).toBeInTheDocument();
    expect(screen.getByText("USD per month max")).toBeInTheDocument();
    expect(screen.getByText("PAY_PER_EVENT")).toBeInTheDocument();

    // Verify actors are rendered
    expect(screen.getByText("Web Job Discovery Adapter")).toBeInTheDocument();
    expect(
      screen.getByText("Naukri Portal Adapter (Restricted)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("LinkedIn Portal Adapter (Unauthorized)"),
    ).toBeInTheDocument();
  });

  it("disables execution controls for restricted and unauthorized actors", async () => {
    mount();

    await screen.findByText("Configured & Authorized");

    // Blocked actors have "Blocked by policy" disabled buttons
    const blockedBtns = screen.getAllByRole("button", {
      name: "Blocked by policy",
    });
    expect(blockedBtns.length).toBeGreaterThanOrEqual(2);
    for (const btn of blockedBtns) {
      expect(btn).toBeDisabled();
    }

    // No LinkedIn login, cookie import, or automated messaging controls exist anywhere
    expect(screen.queryByRole("button", { name: /login/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /cookie/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /invite/i })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /cookie/i })).toBeNull();
  });

  it("distinguishes free metadata lookup from chargeable execution in the inspect modal", async () => {
    mount();

    await screen.findByText("Configured & Authorized");

    // Click "Inspect metadata (Free)" on the first actor
    const inspectBtns = screen.getAllByRole("button", {
      name: "Inspect metadata (Free)",
    });
    await userEvent.click(inspectBtns[0]);

    // Modal opens showing metadata inspection
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByText(/Free schema and capability review/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Metadata inspection does not invoke the provider or consume credits/i,
      ),
    ).toBeInTheDocument();
  });

  it("requires explicit double consent before executing a chargeable actor", async () => {
    vi.mocked(post).mockResolvedValue({
      id: "run-1111",
      platform: "apify",
      query: { keywords: ["Python"], locations: ["India"] },
      status: "completed",
      counts: { discovered: 5, inserted: 2, duplicate: 3, failed: 0 },
      failure_reason: null,
      created_at: "2026-03-01T00:00:00Z",
    });

    mount();

    await screen.findByText("Configured & Authorized");

    // Open run modal for available actor
    const runBtn = screen.getByRole("button", {
      name: "Configure & Run",
    });
    await userEvent.click(runBtn);

    // Check modal opened with description
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Verify estimated usage, required criteria, and explicit consent before execution/i,
      ),
    ).toBeInTheDocument();

    const executeBtn = screen.getByRole("button", {
      name: "Execute approved run",
    });
    // Initially disabled because consents are unchecked
    expect(executeBtn).toBeDisabled();

    // Check cost consent
    const costCheckbox = screen.getByLabelText(
      /I understand this execution consumes platform credits/i,
    );
    await userEvent.click(costCheckbox);
    expect(executeBtn).toBeDisabled(); // Still disabled, need permission consent

    // Check permission consent
    const permissionCheckbox = screen.getByLabelText(
      /I confirm I have reviewed data-source rights/i,
    );
    await userEvent.click(permissionCheckbox);

    // Now execute button should be enabled
    expect(executeBtn).not.toBeDisabled();

    // Click execute
    await userEvent.click(executeBtn);

    // post must have been called with discovery/runs
    expect(post).toHaveBeenCalledWith(
      "discovery/runs",
      expect.objectContaining({
        source: "apify",
        allow_paid: true,
      }),
    );
  });
});
