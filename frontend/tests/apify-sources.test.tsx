import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import { ApifySourceManagement } from "@/features/apify-sources";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const status = {
  provider: "apify",
  local_token_configured: true,
  monthly_limit_usd: 0,
  per_run_cap_usd: 0,
  budget_key: "apify",
  account_rotation: false,
  linkedin_collection_enabled: false,
  investigated_actors: ["harvestapi/linkedin-company"],
  last_account_inspection: null,
  local_budget: {
    month: "2026-10",
    reserved_usd: 0,
    remaining_local_usd: 0,
    accounting: "local_reservations_not_provider_credit",
  },
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ApifySourceManagement />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(
    async (path) =>
      (path === "integrations/providers/apify"
        ? status
        : {
            sources: [
              {
                id: "wellfound",
                display_name: "Wellfound",
                adapter_type: "apify",
                availability: "configuration_required",
              },
            ],
          }) as any,
  );
});
it("renders actual source IDs and zero budgets without fabricated actors or prices", async () => {
  mount();
  expect(await screen.findByText(/Wellfound/)).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "harvestapi/linkedin-company" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Unknown")).toBeInTheDocument();
  expect(screen.queryByText("Web Job Discovery Adapter")).toBeNull();
  expect(screen.queryByText(/\$5\.00/)).toBeNull();
});
it("never enables chargeable execution even with configured credentials", async () => {
  mount();
  expect(
    await screen.findByRole("button", { name: "Blocked by policy" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: /execute|configure & run/i }),
  ).toBeNull();
  expect(post).not.toHaveBeenCalled();
});
it("retrieves observed metadata instead of inventing prices or collection rights", async () => {
  vi.mocked(post).mockResolvedValue({
    actor_id: "harvestapi/linkedin-company",
    title: "Observed company Actor",
    observed_at: "2026-10-28T00:00:00Z",
    pricing: [{ pricingModel: "PAY_PER_EVENT" }],
    input_schema: {},
    schema_digest: "observed",
    collection_status: "disabled_pending_review",
    source_url: "https://api.apify.com/v2/acts/harvestapi~linkedin-company",
  });
  mount();
  await userEvent.click(
    await screen.findByRole("button", { name: "Inspect metadata (read only)" }),
  );
  expect(await screen.findByRole("dialog")).toHaveTextContent(
    "Observed company Actor",
  );
  expect(post).toHaveBeenCalledWith(
    "integrations/providers/apify/actors/inspect",
    { actor_id: "harvestapi/linkedin-company" },
  );
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "disabled pending review",
  );
});
it("uses only the read-only account inspector and reports backend errors", async () => {
  vi.mocked(post).mockRejectedValue(new Error("Provider limits unavailable"));
  mount();
  await userEvent.click(
    await screen.findByRole("button", {
      name: "Inspect account limits (read only)",
    }),
  );
  expect(
    await screen.findByText("Provider limits unavailable"),
  ).toBeInTheDocument();
  expect(post).toHaveBeenCalledWith("integrations/providers/apify/inspect");
});
