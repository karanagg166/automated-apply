import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  DRAFTS_PATH,
  QuotaFallbackPanel,
  channelTone,
} from "@/features/autopilot-drafts";
import { PortalRulesEditor } from "@/features/autopilot-rules";
import { api, type Schema } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));

type Rules = Schema<"PortalRulesRead">;

const PORTALS: Array<[string, string, boolean]> = [
  ["greenhouse", "Greenhouse (direct ATS)", false],
  ["himalayas", "Himalayas", true],
  ["hiringcafe", "HiringCafe", true],
  ["instahyre", "Instahyre", true],
  ["internshala", "Internshala", true],
  ["lever", "Lever (direct ATS)", false],
  ["naukri", "Naukri", true],
  ["we_work_remotely", "We Work Remotely", true],
  ["wellfound", "Wellfound", true],
  ["work_at_a_startup", "YC Work at a Startup", true],
];

const rules: Rules[] = PORTALS.map(([platform, label, login]) => ({
  platform,
  label,
  enabled: platform === "naukri",
  auto_apply_enabled: false,
  max_applies_per_day: 50,
  max_applies_per_hour: 10,
  max_job_age_days: 7,
  max_applicants: 300,
  unknown_applicants_policy: "allow_lower_bound",
  min_delay_sec: 45,
  max_delay_sec: 150,
  active_hours_start: "08:00",
  active_hours_end: "23:30",
  timezone: "Asia/Kolkata",
  auth_status: "UNKNOWN",
  revision: 1,
  adapter_status: platform === "naukri" ? "ready" : "pending_phase6",
  requires_login: login,
}));

const mail = (
  overrides: Partial<Schema<"MailStatusRead">> = {},
): Schema<"MailStatusRead"> => ({
  permission: "READ_AND_DRAFT_ONLY",
  permission_label: "Gmail Permission: Read + Draft Only (Sending Disabled)",
  disabled: false,
  channel_mode: "auto",
  active_channel: "imap",
  imap_configured: true,
  imap_email: "ka•••@gmail.com",
  imap_host: "imap.gmail.com",
  mail_app_available: true,
  mail_app_disabled: false,
  resume_attachment_configured: true,
  ...overrides,
});

const enrichment: Schema<"EnrichmentStatusRead"> = {
  backend: "postgres",
  disabled: false,
  fetch_pages: true,
  cached_domains: 4,
  providers: [
    {
      provider: "apollo",
      configured: true,
      state: "cooldown",
      daily_cap: 10,
      used_today: 3,
      period_key: "2026-11-26",
      cooldown_until: "2026-11-27T06:30:00Z",
      last_error: "http_403_plan_restricted",
      key_env: "APOLLO_API_KEY",
    },
    {
      provider: "apify",
      configured: true,
      state: "cap_reached",
      daily_cap: 5,
      used_today: 5,
      period_key: "2026-11-26",
      cooldown_until: null,
      last_error: null,
      key_env: "APIFY_API_TOKEN",
    },
    {
      provider: "signalhire",
      configured: false,
      state: "unconfigured",
      daily_cap: 5,
      used_today: 0,
      period_key: "2026-11-26",
      cooldown_until: null,
      last_error: null,
      key_env: "SIGNALHIRE_API_KEY",
    },
  ],
};

const drafts: Schema<"EmailDraftPage"> = {
  total: 1,
  limit: 25,
  offset: 0,
  items: [
    {
      id: "77777777-7777-4777-8777-777777777777",
      application_id: "44444444-4444-4444-8444-444444444444",
      platform: "naukri",
      company_name: "Acme",
      role_title: "Backend Engineer",
      recipient_email: "careers@acme.example",
      subject: "Application: Backend Engineer at Acme",
      body_preview: "Hi Acme hiring team, …",
      channel: "imap",
      status: "CREATED",
      composer: "template",
      enrichment_source: "jd_text",
      last_error: null,
      created_at: "2026-11-26T09:00:00Z",
      application_state: "DRAFTED_AND_QUEUED",
      retry_after: "2026-11-27T02:30:00Z",
    },
  ],
};

let mailState = mail();
let draftState = drafts;

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
  mailState = mail();
  draftState = drafts;
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/mail/status") return structuredClone(mailState);
    if (path === "v2/enrichment/status") return structuredClone(enrichment);
    if (path === DRAFTS_PATH) return structuredClone(draftState);
    if (path === "v2/portal-rules") return structuredClone(rules);
    throw new Error(path);
  });
});

it("shows the mail bridge, the locked read + draft badge and credit meters", async () => {
  mount(<QuotaFallbackPanel />);
  expect(
    await screen.findByRole("heading", {
      name: "Gmail Drafts & Enrichment (Quota Fallback)",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("status", {
      name: "Gmail Permission: Read + Draft Only (Sending Disabled)",
    }),
  ).toBeInTheDocument();
  const bridge = await screen.findByLabelText("Mail bridge status");
  expect(within(bridge).getByText("IMAP (Gmail Drafts)")).toBeInTheDocument();
  expect(
    within(bridge).getByText("Configured · ka•••@gmail.com"),
  ).toBeInTheDocument();
  const apollo = screen.getByLabelText("Apollo enrichment");
  expect(within(apollo).getByText("Cooling down")).toBeInTheDocument();
  expect(
    within(apollo).getByRole("progressbar", {
      name: "Free credits today: 3 of 10",
    }),
  ).toBeInTheDocument();
  expect(
    within(screen.getByLabelText("Apify enrichment")).getByText(
      "Daily cap reached",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByLabelText("SignalHire enrichment")).getByText(
      "SIGNALHIRE_API_KEY",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/4 company domains cached/)).toBeInTheDocument();
});

it("lists recent drafts with recipient, channel and tomorrow's retry", async () => {
  mount(<QuotaFallbackPanel />);
  const table = await screen.findByRole("table");
  const row = within(table).getAllByRole("row")[1];
  expect(within(row).getByText("careers@acme.example")).toBeInTheDocument();
  expect(within(row).getByText("IMAP")).toBeInTheDocument();
  expect(within(row).getByText("Saved in Drafts")).toBeInTheDocument();
  expect(within(row).getByText("drafted and queued")).toBeInTheDocument();
  expect(within(row).getByText(/^Retry /)).toBeInTheDocument();
  expect(screen.getByText("1 drafts")).toBeInTheDocument();
});

it("explains how to configure an unconfigured bridge and shows an empty table", async () => {
  mailState = mail({
    active_channel: "unconfigured",
    imap_configured: false,
    imap_email: null,
    mail_app_available: false,
  });
  draftState = { ...drafts, items: [], total: 0 };
  mount(<QuotaFallbackPanel />);
  expect(await screen.findByText("Unconfigured")).toBeInTheDocument();
  expect(screen.getByText("GMAIL_IMAP_APP_PASSWORD")).toBeInTheDocument();
  expect(await screen.findByText("No drafts yet")).toBeInTheDocument();
  expect(channelTone("unconfigured")).toBe("amber");
  expect(channelTone("mail_app")).toBe("green");
});

it("manages all 10 portals and marks which adapters can run live", async () => {
  mount(<PortalRulesEditor />);
  const headings = await screen.findAllByRole("heading", { level: 3 });
  expect(headings.map((h) => h.textContent)).toEqual(PORTALS.map((p) => p[1]));
  expect(screen.getAllByText("Adapter ready")).toHaveLength(1);
  expect(screen.getAllByText("Phase 6 adapter pending")).toHaveLength(9);
  expect(screen.getAllByText("No login needed")).toHaveLength(2);
  const naukri = screen.getByRole("region", { name: "Naukri" });
  expect(within(naukri).getByText("Adapter ready")).toBeInTheDocument();
  expect(
    within(naukri).getByRole("button", { name: "Save Naukri rules" }),
  ).toBeInTheDocument();
});
