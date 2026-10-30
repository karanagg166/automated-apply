import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocalMailboxes } from "@/features/local-mailboxes";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
let accounts: any[];
beforeEach(() => {
  vi.clearAllMocks();
  accounts = [1, 2].map((slot) => ({
    slot: String(slot),
    status: "not_connected",
    enabled: true,
    generation: 1,
    drafts_enabled: false,
    body_review_enabled: false,
    token_health: "saved_not_live_checked",
  }));
  vi.mocked(api).mockImplementation(async () => ({ accounts }) as any);
  vi.mocked(post).mockResolvedValue({});
});
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <LocalMailboxes />
    </QueryClientProvider>,
  );
}

it("keeps two independent consents and performs no automatic OAuth or mailbox request", async () => {
  mount();
  const first = (await screen.findByText("Gmail account 1")).closest(
    "section",
  )!;
  const second = screen.getByText("Gmail account 2").closest("section")!;
  expect(
    within(first).getByRole("button", { name: "Choose account with Google" }),
  ).toBeDisabled();
  fireEvent.click(within(first).getByRole("checkbox"));
  expect(
    within(first).getByRole("button", { name: "Choose account with Google" }),
  ).toBeEnabled();
  expect(
    within(second).getByRole("button", { name: "Choose account with Google" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});

it("searches only the explicitly chosen account and preserves body/draft gates", async () => {
  accounts[1] = {
    ...accounts[1],
    status: "connected",
    account_email: "second@example.org",
  };
  vi.mocked(post).mockResolvedValue({
    messages: [
      { id: "m1", from: "alerts@naukri.com", subject: "Selected job alert" },
    ],
  });
  mount();
  const second = (await screen.findByText("Gmail account 2")).closest(
    "section",
  )!;
  fireEvent.click(
    within(second).getByRole("button", { name: "Search up to three messages" }),
  );
  await screen.findByText(/Selected job alert/);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "integrations/gmail/local/accounts/2/search",
      { query: "Naukri newer_than:30d", limit: 3 },
    ),
  );
  expect(
    within(second).getByRole("button", { name: "Read selected alert" }),
  ).toBeDisabled();
  expect(
    within(second).getByRole("button", {
      name: "Create or verify one test draft to myself",
    }),
  ).toBeDisabled();
});

it("allows only fixed account and read/draft routes through the owner gateway", () => {
  expect(
    permittedRoute("integrations/gmail/local/accounts/1/drafts", "POST"),
  ).toBe(true);
  for (const operation of [
    "send",
    "delete",
    "forward",
    "settings",
    "batchDelete",
  ]) {
    expect(
      permittedRoute(
        `integrations/gmail/local/accounts/1/${operation}`,
        "POST",
      ),
    ).toBe(false);
  }
  expect(
    permittedRoute("integrations/gmail/local/accounts/3/connect", "POST"),
  ).toBe(false);
});

it("permits only bounded job alert controls through the authenticated gateway", () => {
  expect(
    permittedRoute("integrations/gmail/local/accounts/1/job-alerts", "PUT"),
  ).toBe(true);
  expect(
    permittedRoute(
      "integrations/gmail/local/accounts/1/job-alerts/sync",
      "POST",
    ),
  ).toBe(true);
  expect(
    permittedRoute("integrations/gmail/local/accounts/3/job-alerts", "PUT"),
  ).toBe(false);
  expect(
    permittedRoute(
      "integrations/gmail/local/accounts/1/job-alerts/send",
      "POST",
    ),
  ).toBe(false);
});
