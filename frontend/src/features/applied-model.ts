import type { Schema } from "@/lib/api";

export type AppliedSummary = Schema<"ApplicationSummary">;
export type PortalSummary = Schema<"PortalSummary">;
export type DailyApplied = Schema<"DailyApplied">;
export type AppliedDetail = Schema<"ApplicationDetail">;
export type AppliedRow = Schema<"ApplicationRead">;
export type AppliedPage = Schema<"ApplicationPage">;

export const APPLIED_PAGE_SIZE = 25;
export const APPLIED_REFRESH_MS = 30000;
export const SUMMARY_DAYS = 14;
export const IST = "Asia/Kolkata";

/** Table state filters; "" lists every state. */
export const STATE_FILTERS = [
  ["APPLIED", "Applied"],
  ["SUBMISSION_UNKNOWN", "Unknown submission"],
  ["FAILED", "Failed"],
  ["WAITING_FOR_USER", "Needs your input"],
  ["", "All states"],
] as const;
export type StateFilter = (typeof STATE_FILTERS)[number][0];

const PORTAL_NAMES: Record<string, string> = {
  naukri: "Naukri",
  instahyre: "Instahyre",
  internshala: "Internshala",
  wellfound: "Wellfound",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  remotive: "Remotive",
  arbeitnow: "Arbeitnow",
  hacker_news: "Hacker News",
  himalayas: "Himalayas",
  hiringcafe: "HiringCafe",
  work_at_a_startup: "Work at a Startup",
  we_work_remotely: "We Work Remotely",
};

export function portalName(platform: string) {
  return (
    PORTAL_NAMES[platform] ||
    platform
      .split(/[_-]+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase() + part.slice(1))
      .join(" ")
  );
}

export function appliedListPath({
  platform,
  state,
  q,
  page,
}: {
  platform: string;
  state: StateFilter;
  q: string;
  page: number;
}) {
  const params = new URLSearchParams({
    limit: String(APPLIED_PAGE_SIZE),
    offset: String(Math.max(0, page - 1) * APPLIED_PAGE_SIZE),
  });
  if (platform) params.set("platform", platform);
  if (state) params.set("state", state);
  const query = q.trim();
  if (query) params.set("q", query.slice(0, 100));
  return `v2/applications?${params}`;
}

export function pageCount(total: number) {
  return Math.max(1, Math.ceil(total / APPLIED_PAGE_SIZE));
}

/** Absolute time on the owner's clock, e.g. "27 Nov 2026, 11:30 am IST". */
export function istStamp(value?: string | null, fallback = "—") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return `${date.toLocaleString("en-IN", {
    timeZone: IST,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })} IST`;
}

const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** "3 hours ago" / "just now"; empty string for missing or invalid input. */
export function relativeTime(value?: string | null, now = Date.now()) {
  if (!value) return "";
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = Math.round((time - now) / 1000);
  if (Math.abs(seconds) < 60) return "just now";
  const format = new Intl.RelativeTimeFormat("en-IN", { numeric: "auto" });
  for (const [unit, size] of UNITS)
    if (Math.abs(seconds) >= size)
      return format.format(Math.trunc(seconds / size), unit);
  return "just now";
}

/** Short weekday + day label for a YYYY-MM-DD local date (no timezone shift). */
export function dayLabel(isoDate: string) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.toLocaleDateString("en-IN", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
  });
}

/** Bar height in percent of the tallest day; non-zero days keep a visible 4% stub. */
export function barPercent(value: number, max: number) {
  if (value <= 0 || max <= 0) return 0;
  return Math.max(4, Math.round((value / max) * 100));
}

/** Portals worth a card: any activity first (backend order), all of them if none has any. */
export function visiblePortals(portals: PortalSummary[]) {
  const active = portals.filter((p) => p.total > 0);
  return active.length ? active : portals;
}

const SOURCE_LABELS: Record<string, string> = {
  profile: "Profile",
  profile_identity: "Profile identity",
  screening_facts: "Screening facts",
  resume_picker: "Resume picker",
  skip_optional: "Skipped (optional)",
  composer: "Composed note",
  human_hitl: "Your answer",
  llm: "AI answer",
  semantic_cache: "Saved answer",
};

export function answerSourceLabel(source?: string | null) {
  if (!source) return "";
  return SOURCE_LABELS[source] || source.replaceAll("_", " ");
}
