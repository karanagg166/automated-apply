import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Applied } from "@/features/applied";
import { AppliedDetail } from "@/features/applied-detail";
import {
  appliedListPath,
  barPercent,
  dayLabel,
  istStamp,
  pageCount,
  portalName,
  relativeTime,
  visiblePortals,
  type AppliedSummary,
  type PortalSummary,
} from "@/features/applied-model";
import { permittedRoute } from "@/lib/gateway";
import { api, ApiError } from "@/lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/applied",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));

const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";

function portal(
  platform: string,
  over: Partial<PortalSummary> = {},
): PortalSummary {
  return {
    platform,
    applied_total: 0,
    applied_today: 0,
    applied_7d: 0,
    submission_unknown: 0,
    failed: 0,
    waiting_for_user: 0,
    applying: 0,
    queued: 0,
    quota_parked: 0,
    filtered_out: 0,
    total: 0,
    states: {},
    ...over,
  };
}

const summary: AppliedSummary = {
  generated_at: "2026-11-27T06:00:00Z",
  timezone: "Asia/Kolkata",
  days: 3,
  totals: portal("all", {
    applied_total: 25,
    applied_today: 4,
    applied_7d: 12,
    waiting_for_user: 2,
    submission_unknown: 3,
    total: 40,
  }),
  portals: [
    portal("naukri", {
      applied_total: 20,
      applied_today: 3,
      total: 30,
      submission_unknown: 3,
    }),
    portal("hacker_news", {
      applied_total: 5,
      applied_today: 1,
      total: 10,
      failed: 1,
    }),
    portal("lever"),
  ],
  daily: [
    { date: "2026-11-25", applied: 0, by_platform: {} },
    { date: "2026-11-26", applied: 2, by_platform: { naukri: 2 } },
    {
      date: "2026-11-27",
      applied: 4,
      by_platform: { naukri: 3, hacker_news: 1 },
    },
  ],
};

const row = {
  id: ID,
  platform: "naukri",
  external_job_id: "123",
  company_name: "Razorpay",
  role_title: "Backend Engineer",
  job_url: "https://www.naukri.com/job-listings-123",
  state: "APPLIED",
  attempts: 1,
  applied_at: "2026-11-27T05:00:00Z",
  updated_at: "2026-11-27T05:00:00Z",
};

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  push.mockReset();
});

describe("applied model", () => {
  it("builds list paths with filters, search and offset", () => {
    expect(
      appliedListPath({ platform: "", state: "APPLIED", q: "", page: 1 }),
    ).toBe("v2/applications?limit=25&offset=0&state=APPLIED");
    expect(
      appliedListPath({
        platform: "naukri",
        state: "",
        q: "  razor pay ",
        page: 3,
      }),
    ).toBe("v2/applications?limit=25&offset=50&platform=naukri&q=razor+pay");
    expect(pageCount(0)).toBe(1);
    expect(pageCount(26)).toBe(2);
  });

  it("formats IST times, relative times and day labels", () => {
    expect(istStamp("2026-11-27T05:00:00Z")).toMatch(
      /27 Nov 2026.*10:30.*IST$/i,
    );
    expect(istStamp(null)).toBe("—");
    const now = Date.parse("2026-11-27T08:00:00Z");
    expect(relativeTime("2026-11-27T05:00:00Z", now)).toBe("3 hours ago");
    expect(relativeTime("2026-11-27T07:59:30Z", now)).toBe("just now");
    expect(relativeTime("bad", now)).toBe("");
    expect(dayLabel("2026-11-27")).toBe("27 Nov");
  });

  it("names portals, scales bars and hides idle portals", () => {
    expect(portalName("hacker_news")).toBe("Hacker News");
    expect(portalName("new_board")).toBe("New Board");
    expect(barPercent(0, 10)).toBe(0);
    expect(barPercent(1, 100)).toBe(4);
    expect(barPercent(10, 10)).toBe(100);
    expect(visiblePortals(summary.portals).map((p) => p.platform)).toEqual([
      "naukri",
      "hacker_news",
    ]);
    const idle = [portal("lever")];
    expect(visiblePortals(idle)).toEqual(idle);
  });

  it("allows the new routes through the proxy allowlist only", () => {
    expect(permittedRoute("v2/applications/summary", "GET")).toBe(true);
    expect(permittedRoute(`v2/applications/${ID}`, "GET")).toBe(true);
    expect(permittedRoute(`v2/applications/${ID}`, "DELETE")).toBe(false);
    expect(permittedRoute("v2/applications/../status", "GET")).toBe(false);
  });
});

describe("Applied page", () => {
  it("shows KPIs, chart, portal cards and filters the table by portal, state and search", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.startsWith("v2/applications/summary")) return summary;
      return { items: [row], total: 1, limit: 25, offset: 0 };
    });
    const user = userEvent.setup();
    mount(<Applied />);
    const totals = await screen.findByLabelText("Application totals");
    expect(within(totals).getByText("25")).toBeInTheDocument();
    expect(within(totals).getByText("Needs your input")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /27 Nov 4/ })).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "Backend Engineer" }),
    ).toHaveAttribute("href", `/applied/${ID}`);
    expect(screen.getByText("Razorpay")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      "v2/applications?limit=25&offset=0&state=APPLIED",
    );

    await user.click(screen.getByRole("button", { name: /Hacker News/ }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "v2/applications?limit=25&offset=0&platform=hacker_news&state=APPLIED",
      ),
    );
    expect(screen.getByRole("button", { name: /Hacker News/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Review these" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "v2/applications?limit=25&offset=0&platform=hacker_news&state=SUBMISSION_UNKNOWN",
      ),
    );
    await user.type(screen.getByLabelText("Search company or role"), "razor");
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "v2/applications?limit=25&offset=0&platform=hacker_news&state=SUBMISSION_UNKNOWN&q=razor",
      ),
    );
    await user.click(screen.getByText("Razorpay"));
    expect(push).toHaveBeenCalledWith(`/applied/${ID}`);
  });

  it("shows empty and error states", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.startsWith("v2/applications/summary"))
        throw new ApiError(503, "Python v2 tables are missing");
      return { items: [], total: 0, limit: 25, offset: 0 };
    });
    mount(<Applied />);
    expect(
      await screen.findByText("Python v2 tables are missing"),
    ).toBeInTheDocument();
    expect(await screen.findByText("No applications yet")).toBeInTheDocument();
  });
});

describe("Applied detail", () => {
  it("renders screening answers, submission facts and the timeline", async () => {
    vi.mocked(api).mockResolvedValue({
      ...row,
      receipt: {
        verified: true,
        source: "header_applied_after_submit",
        ats: null,
        clicked_apply: true,
        has_screenshot: true,
        confirmation_url: null,
        answers: [
          { question: "Notice period?", answer: "30 days", source: "profile" },
          { question: "Expected CTC", answer: "12 LPA", source: "human_hitl" },
        ],
        answers_source: "receipt",
      },
      timeline: [
        {
          from_state: "DISCOVERED",
          to_state: "APPLYING",
          event_type: "apply_started",
          created_at: "2026-11-27T04:59:00Z",
        },
        {
          from_state: "APPLYING",
          to_state: "APPLIED",
          event_type: "confirmed",
          created_at: "2026-11-27T05:00:00Z",
        },
      ],
    });
    mount(<AppliedDetail id={ID} />);
    expect(
      await screen.findByRole("heading", { name: "Backend Engineer" }),
    ).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`v2/applications/${ID}`);
    expect(screen.getByText("Verified receipt")).toBeInTheDocument();
    expect(screen.getByText("Notice period?")).toBeInTheDocument();
    expect(screen.getByText("12 LPA")).toBeInTheDocument();
    expect(screen.getByText("Your answer")).toBeInTheDocument();
    expect(screen.getByText("Saved on this Mac")).toBeInTheDocument();
    const history = screen.getByRole("list", { name: "State history" });
    const items = within(history).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("APPLYING → APPLIED");
    expect(
      screen.getByRole("link", { name: /Back to applied/ }),
    ).toHaveAttribute("href", "/applied");
  });

  it("shows a not-found state for unknown ids", async () => {
    vi.mocked(api).mockRejectedValue(
      new ApiError(404, "Application not found"),
    );
    mount(<AppliedDetail id={ID} />);
    expect(
      await screen.findByText("Application not found"),
    ).toBeInTheDocument();
  });
});
