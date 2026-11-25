import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  HITL_PATH,
  HitlInbox,
  TelegramStatusBadge,
  telegramBadge,
} from "@/features/autopilot-hitl";
import { api, post, type Schema } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const telegram = (
  overrides: Partial<Schema<"TelegramStatusRead">> = {},
): Schema<"TelegramStatusRead"> => ({
  configured: true,
  polling_state: "polling",
  stale: false,
  conflict_detected: false,
  conflict_detected_at: null,
  last_poll_at: "2026-11-26T09:00:00Z",
  last_update_id: 10,
  last_error: null,
  owner_chat_id: "••••321",
  open_hitl_count: 3,
  ...overrides,
});

const item = (overrides: Record<string, unknown>) => ({
  id: "33333333-3333-4333-8333-333333333333",
  ref: "333333",
  application_id: "44444444-4444-4444-8444-444444444444",
  platform: "naukri",
  kind: "QUESTION",
  status: "OPEN",
  question: "Are you willing to relocate to Pune?",
  options: ["Yes", "No"],
  resolver_reason: "llm_unconfigured",
  company: "Acme",
  title: "Python Developer",
  job_url: "https://example.com/job",
  application_state: "WAITING_FOR_USER",
  telegram_msg_id: 101,
  answer_text: null,
  resolved_via: null,
  created_at: "2026-11-26T08:00:00Z",
  resolved_at: null,
  consumed_at: null,
  ...overrides,
});

const items = [
  item({}),
  item({
    id: "55555555-5555-4555-8555-555555555555",
    ref: "555555",
    kind: "OTP",
    question: "Naukri needs OTP",
    options: [],
    resolver_reason: null,
    telegram_msg_id: null,
  }),
  item({
    id: "66666666-6666-4666-8666-666666666666",
    ref: "666666",
    kind: "AUTH",
    question: "[Naukri] Session expired",
    options: [],
    application_id: null,
    company: null,
    title: null,
  }),
];

let telegramState = telegram();

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  telegramState = telegram();
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/telegram/status") return structuredClone(telegramState);
    if (path === HITL_PATH)
      return {
        items: structuredClone(items),
        total: items.length,
        limit: 50,
        offset: 0,
      };
    throw new Error(path);
  });
  vi.mocked(post).mockResolvedValue({
    ok: true,
    code: "answered",
    message:
      "Answered 333333 (Acme · Python Developer). Job re-queued with priority.",
  });
});

it("maps Telegram poller state to the status-bar badge", () => {
  expect(telegramBadge(telegram())).toEqual({
    label: "Telegram: Connected",
    tone: "green",
  });
  expect(telegramBadge(telegram({ polling_state: "conflict" })).tone).toBe(
    "red",
  );
  expect(telegramBadge(telegram({ configured: false })).label).toBe(
    "Telegram: Not configured",
  );
  expect(telegramBadge(telegram({ stale: true })).label).toBe(
    "Telegram: Offline",
  );
  expect(telegramBadge(telegram({ polling_state: "error" })).tone).toBe(
    "amber",
  );
});

it("renders the badge from the live status endpoint", async () => {
  telegramState = telegram({ polling_state: "conflict" });
  mount(<TelegramStatusBadge />);
  expect(await screen.findByText("Telegram: Conflict")).toBeInTheDocument();
});

it("answers a question with a clicked option and saves it to the cache", async () => {
  const user = userEvent.setup();
  mount(<HitlInbox />);
  const card = await screen.findByLabelText("HITL 333333");
  expect(within(card).getByText(/Acme · Python Developer/)).toBeInTheDocument();
  expect(within(card).getByText("Sent to Telegram")).toBeInTheDocument();
  const submit = within(card).getByRole("button", { name: "Answer & resume" });
  expect(submit).toBeDisabled();
  await user.click(within(card).getByRole("button", { name: "1. Yes" }));
  expect(within(card).getByRole("button", { name: "1. Yes" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(within(card).getByLabelText(/Save to semantic cache/)).toBeChecked();
  await user.click(submit);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${items[0].id}/resolve`, {
      answer: "Yes",
      cache_answer: true,
    }),
  );
  expect(
    await screen.findByText(/re-queued with priority/),
  ).toBeInTheDocument();
});

it("can answer without caching, skip a job and submit an OTP uncached", async () => {
  const user = userEvent.setup();
  mount(<HitlInbox />);
  const card = await screen.findByLabelText("HITL 333333");
  await user.click(within(card).getByRole("button", { name: "2. No" }));
  await user.click(within(card).getByLabelText(/Save to semantic cache/));
  await user.click(
    within(card).getByRole("button", { name: "Answer & resume" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${items[0].id}/resolve`, {
      answer: "No",
      cache_answer: false,
    }),
  );
  await user.click(within(card).getByRole("button", { name: "Skip job" }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${items[0].id}/skip`),
  );
  const otp = screen.getByLabelText("HITL 555555");
  expect(within(otp).queryByLabelText(/Save to semantic cache/)).toBeNull();
  expect(within(otp).getByText("Not yet on Telegram")).toBeInTheDocument();
  await user.type(within(otp).getByLabelText("OTP code"), "482913");
  await user.click(
    within(otp).getByRole("button", { name: "Answer & resume" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`v2/hitl/${items[1].id}/resolve`, {
      answer: "482913",
      cache_answer: false,
    }),
  );
});

it("resumes a portal from an AUTH alert", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValue({
    ok: true,
    platform: "naukri",
    message:
      "naukri resumed: the worker re-checks the session on its next tick.",
    auth_status: "UNKNOWN",
    resolved_auth_requests: 1,
  });
  mount(<HitlInbox />);
  const card = await screen.findByLabelText("HITL 666666");
  expect(within(card).getByText(/login-setup/)).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Skip job" })).toBeNull();
  await user.click(
    within(card).getByRole("button", {
      name: "I've logged in — resume portal",
    }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/portal-rules/naukri/resume-auth"),
  );
  expect(await screen.findByText(/re-checks the session/)).toBeInTheDocument();
});

it("warns about a 409 conflict with the legacy poller", async () => {
  telegramState = telegram({ polling_state: "conflict" });
  mount(<HitlInbox />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "com.automated-apply.rust",
  );
  expect(screen.getByText("3 open")).toBeInTheDocument();
});
