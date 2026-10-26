import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { LocalConnections } from "@/features/local-connections";
import { api, ApiError } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));

const row = {
  name: "Fictional portal",
  group: "platforms",
  configuration_status: "configured",
  state: "browser_session_observed",
  identity_verification: "account_identity_unverified",
  capability_verification: "manual_handoff_only_no_applicant_api",
  capabilities: ["manual_handoff"],
  actual_evidence_type: "extension_gesture_dom_indicator",
  owner_authorization_required: true,
  may_consume_paid_credits: false,
  safe_next_action: "Review the actual portal.",
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <LocalConnections />
    </QueryClientProvider>,
  );
}
beforeEach(() => vi.clearAllMocks());
it("keeps a browser indicator separate from verification", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "local-agent/connections"
      ? [row]
      : { version: 1, default: "approve", platforms: {} },
  );
  mount();
  expect(
    await screen.findByText("Browser session observed", { exact: true }),
  ).toBeVisible();
  expect(
    screen.queryByText("Verified", { exact: true }),
  ).not.toBeInTheDocument();
});
it("does not promote configured credentials to verified status", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "local-agent/connections"
      ? [{ ...row, state: "credentials_configured" }]
      : { version: 1, default: "approve", platforms: {} },
  );
  mount();
  expect(
    await screen.findByText("Not connected", { exact: true }),
  ).toBeVisible();
  expect(
    screen.queryByText("Verified", { exact: true }),
  ).not.toBeInTheDocument();
});
it("shows connection failures without invented connection cards", async () => {
  vi.mocked(api).mockRejectedValue(
    new ApiError(503, "Connection evidence unavailable"),
  );
  mount();
  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(
    "Connection evidence unavailable",
  );
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
});
