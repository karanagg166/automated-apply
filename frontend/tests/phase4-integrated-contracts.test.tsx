import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Jobs, getSourceDetails } from "@/features/jobs";
import { ConnectedEmails, detectUrlAts } from "@/features/connected-emails";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
function mount(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {component}
    </QueryClientProvider>,
  );
}
beforeEach(() => vi.clearAllMocks());

it("never treats missing source metadata or recognized vendor hosts as verified compatibility", () => {
  for (const source of [
    "lever",
    "ashby",
    "greenhouse",
    "smartrecruiters",
    "gmail_alert",
    "workday",
    "simplify",
  ]) {
    expect(getSourceDetails(source).liveVerified).toBe(false);
  }
  expect(getSourceDetails("simplify").adapterType).toBe("manual");
  expect(
    getSourceDetails("smartrecruiters", [
      { id: "smartrecruiters", availability: "configuration_required" },
    ]).availability,
  ).toBe("configuration_required");
  expect(detectUrlAts("https://evilgreenhouse.io/application").isAts).toBe(
    false,
  );
});

it("sends factual filters before pagination and trusts server evidence rather than guessing from titles or company metadata", async () => {
  const user = userEvent.setup();
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith("jobs/search")
      ? {
          total: 41,
          jobs: [
            {
              id: "00000000-0000-0000-0000-000000000001",
              title: "Server evidence result",
              source_platform: "ashby",
              status: "discovered",
              skills_required: [],
              company_name: "Fixture",
              job_url: "https://jobs.ashbyhq.com/fixture/id",
            },
          ],
        }
      : {
          sources: [
            {
              id: "ashby",
              availability: "configuration_required",
              adapter_type: "direct_api",
            },
          ],
        },
  );
  mount(<Jobs />);
  await screen.findByText("Server evidence result");
  await user.click(screen.getByRole("button", { name: /^🇮🇳 India/ }));
  await user.click(screen.getByRole("button", { name: /More filters/ }));
  const selects = screen.getAllByRole("combobox");
  const seniority = selects.find((element) =>
    within(element).queryByRole("option", { name: "Junior" }),
  )!;
  const size = selects.find((element) =>
    within(element).queryByRole("option", {
      name: "2–10 employees",
    }),
  )!;
  const freshness = selects.find((element) =>
    within(element).queryByRole("option", {
      name: "Last 14 days",
    }),
  )!;
  await user.selectOptions(seniority, "junior");
  await user.selectOptions(size, "2-10");
  await user.selectOptions(freshness, "14");
  await user.click(
    screen.getByRole("checkbox", { name: /Fit approved experience/ }),
  );
  await waitFor(() => {
    const paths = vi.mocked(api).mock.calls.map(([path]) => path);
    expect(
      paths.some((path) => {
        const query = new URLSearchParams(path.split("?")[1]);
        return (
          query.get("country") === "IN" &&
          query.get("experience_level") === "junior" &&
          query.get("company_size_band") === "2-10" &&
          query.get("published_within_days") === "14" &&
          query.get("approved_experience_fit") === "true" &&
          query.get("page") === "1" &&
          !query.has("max_age_days")
        );
      }),
    ).toBe(true);
  });
  expect(screen.getByText("Server evidence result")).toBeInTheDocument();
});

it("keeps same-URL Gmail import states independent per account and exposes historical ambiguity", async () => {
  const url = "https://jobs.lever.co/fixture/posting";
  const accounts = ["first", "second"].map((id) => ({
    id,
    account_email: `${id}@example.com`,
    granted_scopes: [],
    status: "connected",
    permissions: {
      read_metadata: true,
      read_body: false,
      send: false,
      modify: false,
    },
    sync_enabled: false,
    body_access_reviewed: false,
    sync: { version: 1, status: "idle", policy: null },
  }));
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "integrations/gmail/accounts")
      return { accounts, schema_ready: true, workflow: "readonly" };
    const id = path.includes("/first/") ? "first" : "second";
    if (path.endsWith("/evidence"))
      return {
        evidence: [
          {
            id: `${id}-evidence`,
            account_id: id,
            message_id: "same-message-id",
            thread_id: "thread",
            received_at: new Date().toISOString(),
            observed_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 86400000).toISOString(),
            links: [url, "https://jobs.lever.co/fixture/sibling"],
            signals: [],
            imported_job_ids: ["legacy-job"],
            submission_confirmed: false,
          },
        ],
      };
    if (path.endsWith("/leads"))
      return {
        leads: [
          {
            id: `${id}-lead`,
            url,
            evidence_ids: [`${id}-evidence`],
            import_state:
              id === "first" ? "imported" : "legacy_message_import_unknown",
            imported_job_ids: id === "first" ? ["job"] : [],
          },
        ],
      };
    return {};
  });
  mount(<ConnectedEmails />);
  await screen.findByLabelText("Evidence from first@example.com");
  const first = screen.getByLabelText("Evidence from first@example.com");
  const second = screen.getByLabelText("Evidence from second@example.com");
  expect(within(first).getByText("Already imported")).toBeInTheDocument();
  expect(
    within(second).queryByText("Already imported"),
  ).not.toBeInTheDocument();
  expect(
    within(second).getByText("Historical link import mapping unknown"),
  ).toBeInTheDocument();
  expect(
    within(second).getByRole("button", { name: "Review lead for import" }),
  ).toBeEnabled();
});
