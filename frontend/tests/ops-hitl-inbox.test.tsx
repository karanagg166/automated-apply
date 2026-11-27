import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import {
  HitlInboxPage,
  cacheBlockReason,
  laneOf,
  prioritize,
} from "@/features/hitl-inbox";
import { HITL_PATH } from "@/features/autopilot-hitl";
import { api, post } from "@/lib/api";
import { hitl } from "./ops-fixtures";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const relocate = hitl({ created_at: "2026-11-28T07:00:00Z" });
const motivation = hitl({
  id: "55555555-5555-4555-8555-555555555555",
  ref: "555555",
  question: "Why do you want to join Acme?",
  options: [],
  company: "Acme",
  created_at: "2026-11-28T06:00:00Z",
});
const otp = hitl({
  id: "66666666-6666-4666-8666-666666666666",
  ref: "666666",
  kind: "OTP",
  question: "Greenhouse security code timed out",
  options: [],
  company: "Stripe",
  created_at: "2026-11-28T08:30:00Z",
});
const fresh = hitl({
  id: "77777777-7777-4777-8777-777777777777",
  ref: "777777",
  company: "Fresh Co",
  priority: 1,
  fit_score: 88,
  created_at: "2026-11-28T08:45:00Z",
});

function renderInbox() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <HitlInboxPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(post).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) => {
    expect(path).toBe(HITL_PATH);
    return {
      items: [relocate, motivation, otp, fresh],
      total: 4,
      limit: 50,
      offset: 0,
    };
  });
  vi.mocked(post).mockResolvedValue({
    ok: true,
    code: "ok",
    message: "Answered",
    answer: "Yes",
    cached: true,
  });
});

it("orders P0 first, then fast lane, then standard", () => {
  expect(laneOf(otp)).toBe("p0");
  expect(laneOf(fresh)).toBe("fast");
  expect(laneOf(relocate)).toBe("standard");
  expect(
    prioritize([relocate, motivation, fresh, otp]).map((i) => i.ref),
  ).toEqual(["666666", "777777", "555555", "333333"]);
});

it("submits an answer and promotes it to the semantic cache", async () => {
  const user = userEvent.setup();
  renderInbox();
  const queue = await screen.findByRole("list", { name: "Open requests" });
  const rows = within(queue).getAllByRole("button");
  expect(rows[0]).toHaveTextContent("Stripe");
  await user.click(
    rows.find(
      (row) =>
        /Acme/.test(row.textContent ?? "") &&
        /relocate/.test(row.textContent ?? ""),
    )!,
  );
  await user.click(screen.getByRole("radio", { name: "Yes" }));
  const cache = screen.getByRole("checkbox", {
    name: "Promote to Semantic Cache",
  });
  expect(cache).toBeEnabled();
  expect(cache).toBeChecked();
  await user.click(screen.getByRole("button", { name: /Submit & resume/ }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${relocate.id}/resolve`, {
      answer: "Yes",
      cache_answer: true,
    }),
  );
  expect(await screen.findByText("Answered")).toBeInTheDocument();
});

it("disables cache promotion for company-motivation questions", async () => {
  const user = userEvent.setup();
  renderInbox();
  await user.click(await screen.findByText("Why do you want to join Acme?"));
  const cache = screen.getByRole("checkbox", {
    name: "Promote to Semantic Cache",
  });
  expect(cache).toBeDisabled();
  expect(cache).not.toBeChecked();
  expect(screen.getByText(/company_motivation/)).toBeInTheDocument();
  await user.type(screen.getByLabelText("Your answer"), "Mission fit{Enter}");
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${motivation.id}/resolve`, {
      answer: "Mission fit",
      cache_answer: false,
    }),
  );
});

it("flags never_cache policies and custom prompts", () => {
  expect(cacheBlockReason(hitl({ cache_policy: "never_cache" }))).toMatch(
    /never_cache/,
  );
  expect(
    cacheBlockReason(
      hitl({ question: "Write a SQL query to find duplicates" }),
    ),
  ).toMatch(/never_cache/);
  expect(cacheBlockReason(relocate)).toBeNull();
  expect(cacheBlockReason(otp)).not.toBeNull();
});

it("skips a job", async () => {
  const user = userEvent.setup();
  renderInbox();
  await user.click(await screen.findByRole("button", { name: /Skip job/ }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${otp.id}/skip`, {}),
  );
});
