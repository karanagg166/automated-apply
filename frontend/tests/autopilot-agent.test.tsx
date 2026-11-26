import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  AgentControlChat,
  RecruiterRepliesFeed,
} from "@/features/autopilot-agent";
import { rulesPatch, rulesToForm } from "@/features/autopilot-forms";
import { api, post, type Schema } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

type Replies = Schema<"MailReplyPage">;

let replies: Replies;

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  replies = {
    permission: "READ_ONLY",
    configured: true,
    tiers: { imap: true, gmail_api: false, mail_app: true },
    items: [
      {
        id: "e1",
        kind: "INTERVIEW",
        source: "imap",
        company_name: "Acme",
        sender: "hr@acme.example.com",
        subject: "Technical interview next week",
        snippet: "Can we schedule a call?",
        platform: "naukri",
        received_at: "2026-11-26T09:00:00Z",
      },
    ],
  };
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/mail/replies?limit=20") return structuredClone(replies);
    throw new Error(path);
  });
  vi.mocked(post).mockImplementation(async (_path: string, body: unknown) => {
    const text = (body as { text: string }).text;
    if (text.includes("send"))
      return {
        reply:
          "⛔ Email sending is disabled by design: Gmail is READ + DRAFT ONLY.",
        tool: "forbidden",
        source: "deterministic",
        verdict: "rejected",
        ok: false,
      };
    return {
      reply: "✅ Updated Internshala: paused_until=2026-11-26 12:00 UTC.",
      tool: "update_portal_rule",
      source: "deterministic",
      verdict: "ok",
      ok: true,
    };
  });
});

it("sends owner messages to the control agent and shows guardrail refusals", async () => {
  const user = userEvent.setup();
  mount(<AgentControlChat />);
  await user.type(
    screen.getByRole("textbox", { name: "Message" }),
    "pause Internshala for 3 hours",
  );
  await user.click(screen.getByRole("button", { name: "Send to agent" }));
  expect(post).toHaveBeenCalledWith("v2/agent/chat", {
    text: "pause Internshala for 3 hours",
  });
  const log = screen.getByRole("list", { name: "Agent conversation" });
  expect(
    await within(log).findByText(/Updated Internshala/),
  ).toBeInTheDocument();
  expect(within(log).getByText("update portal rule")).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Message" }),
    "send all drafts",
  );
  await user.click(screen.getByRole("button", { name: "Send to agent" }));
  expect(
    await within(log).findByText(/READ \+ DRAFT ONLY/),
  ).toBeInTheDocument();
  expect(within(log).getByText("rejected")).toBeInTheDocument();
});

it("example prompts run in one click and the send button needs text", async () => {
  const user = userEvent.setup();
  mount(<AgentControlChat />);
  expect(screen.getByRole("button", { name: "Send to agent" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "how many applied today?" }),
  );
  expect(post).toHaveBeenCalledWith("v2/agent/chat", {
    text: "how many applied today?",
  });
});

it("lists recruiter replies from the read-only inbox watcher", async () => {
  mount(<RecruiterRepliesFeed />);
  const list = await screen.findByRole("list", { name: "Recruiter replies" });
  expect(within(list).getByText("Acme")).toBeInTheDocument();
  expect(within(list).getByText("Interview")).toBeInTheDocument();
  expect(
    within(list).getByText("Technical interview next week"),
  ).toBeInTheDocument();
  expect(screen.getByText("Read-only inbox")).toBeInTheDocument();
  expect(screen.getByText("Reading via imap → mail app")).toBeInTheDocument();
});

it("shows an empty state and an unconfigured badge", async () => {
  replies = { ...replies, configured: false, items: [] };
  mount(<RecruiterRepliesFeed />);
  expect(await screen.findByText("No replies yet")).toBeInTheDocument();
  expect(screen.getByText("Inbox not configured")).toBeInTheDocument();
});

it("validates and patches the live quota fallback fields", () => {
  const rules = {
    platform: "lever",
    enabled: false,
    auto_apply_enabled: false,
    max_applies_per_day: 50,
    max_applies_per_hour: 10,
    max_job_age_days: 7,
    max_applicants: 300,
    unknown_applicants_policy: "allow_lower_bound" as const,
    min_delay_sec: 45,
    max_delay_sec: 150,
    active_hours_start: "08:00",
    active_hours_end: "23:30",
    timezone: "Asia/Kolkata",
    auth_status: "UNKNOWN" as const,
    revision: 2,
    quota_fallback_daily_cap: 10,
    quota_drafts_per_cycle: 5,
    allow_unknown_posting_age: false,
    allow_unknown_posting_age_default: false,
    label: "Lever (direct ATS)",
    adapter_status: "ready" as const,
    requires_login: false,
  };
  const form = rulesToForm(rules);
  expect(form.quota_fallback_daily_cap).toBe("10");
  const ok = rulesPatch(rules, {
    ...form,
    quota_fallback_daily_cap: "3",
    quota_drafts_per_cycle: "0",
  });
  expect(ok.errors).toEqual([]);
  expect(ok.patch).toEqual({
    revision: 2,
    quota_fallback_daily_cap: 3,
    quota_drafts_per_cycle: 0,
  });
  const bad = rulesPatch(rules, {
    ...form,
    quota_fallback_daily_cap: "101",
    quota_drafts_per_cycle: "-1",
  });
  expect(bad.errors).toEqual([
    "Quota fallback daily cap must be between 0 and 100.",
    "Drafts per cycle must be between 0 and 50.",
  ]);
});
