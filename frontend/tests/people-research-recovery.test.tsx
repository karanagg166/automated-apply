import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { CompanyPeople } from "@/features/people";
import {
  readResearchAttempt,
  recoverResearch,
  prepareNewResearch,
  type ResearchAttempt,
} from "@/features/people-research-attempt";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/features/people-research-attempt", () => ({
  readResearchAttempt: vi.fn(),
  recoverResearch: vi.fn(),
  prepareNewResearch: vi.fn(),
}));
const company = "10000000-0000-0000-0000-000000000001";
const request = "20000000-0000-0000-0000-000000000002";
let retained: ResearchAttempt | null;
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  retained = null;
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/contacts") ? { contacts: [] } : { people: [] },
  );
  vi.mocked(readResearchAttempt).mockImplementation(() => retained);
  vi.mocked(recoverResearch).mockImplementation(async () => {
    retained = { companyId: company, requestId: request };
    return {
      request_id: request,
      company_id: company,
      status: "success",
      recorded_state: "completed",
      persistence_status: "imported",
      people: [],
    };
  });
  vi.mocked(prepareNewResearch).mockImplementation(async () => {
    retained = null;
  });
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CompanyPeople
        companyId={company}
        companyName="Fictional Company"
        domain="company-fixture.example"
      />
    </QueryClientProvider>,
  );
}
async function open() {
  const user = userEvent.setup();
  await user.click(
    screen.getByText("Review an optional founder / leader research plan"),
  );
  return user;
}
it("recovers an uncertain retained request without new paid approval or a false completion message", async () => {
  retained = { companyId: company, requestId: request };
  vi.mocked(recoverResearch).mockResolvedValueOnce({
    request_id: request,
    company_id: company,
    status: "outcome_unknown",
    recorded_state: "dispatch_admitted",
    people: [],
  });
  mount();
  const user = await open();
  await user.click(
    screen.getByRole("button", { name: /Recover saved research/ }),
  );
  await screen.findByText(/The search result is uncertain/);
  expect(recoverResearch).toHaveBeenCalledWith(
    company,
    expect.objectContaining({ source: "public_search", limit: 5 }),
    false,
  );
  expect(
    screen.queryByText(/Research results are saved/),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/request_id/)).not.toBeInTheDocument();
  expect(prepareNewResearch).not.toHaveBeenCalled();
});
it("requires approval for a fresh search and review before preparing another, retaining the result history", async () => {
  mount();
  const user = await open();
  const run = screen.getByRole("button", { name: /Run approved research/ });
  expect(run).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", {
      name: /I authorize this limited official-company research/,
    }),
  );
  await user.click(run);
  await screen.findByText(/Research results are saved/);
  expect(recoverResearch).toHaveBeenCalledWith(
    company,
    expect.any(Object),
    true,
  );
  const next = screen.getByRole("button", { name: /Prepare a new search/ });
  expect(next).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", {
      name: /I reviewed the saved research result/,
    }),
  );
  await user.click(next);
  await waitFor(() =>
    expect(prepareNewResearch).toHaveBeenCalledWith(company, request),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /Run approved research/ }),
    ).toBeDisabled(),
  );
  expect(recoverResearch).toHaveBeenCalledTimes(1);
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path === "discovery/people/search"),
  ).toBe(false);
});
it("blocks a fresh research action when durable recovery metadata cannot be read", async () => {
  vi.mocked(readResearchAttempt).mockImplementation(() => {
    throw new Error("Research recovery storage unavailable");
  });
  mount();
  const user = await open();
  await user.click(
    screen.getByRole("checkbox", {
      name: /I authorize this limited official-company research/,
    }),
  );
  expect(
    screen.getByRole("button", { name: /Run approved research/ }),
  ).toBeDisabled();
  expect(recoverResearch).not.toHaveBeenCalled();
  expect(
    await screen.findByText(/Research recovery storage unavailable/),
  ).toBeInTheDocument();
});
