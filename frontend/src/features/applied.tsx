"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  CalendarCheck,
  CircleHelp,
  CircleSlash,
  Search,
  Send,
  TriangleAlert,
} from "lucide-react";
import { api, readable } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Input,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { stateTone } from "@/features/autopilot-forms";
import {
  APPLIED_REFRESH_MS,
  STATE_FILTERS,
  SUMMARY_DAYS,
  appliedListPath,
  barPercent,
  dayLabel,
  istStamp,
  pageCount,
  portalName,
  relativeTime,
  visiblePortals,
  type AppliedPage,
  type AppliedRow,
  type AppliedSummary,
  type DailyApplied,
  type PortalSummary,
  type StateFilter,
} from "@/features/applied-model";

export const SUMMARY_KEY = ["v2-applied-summary", SUMMARY_DAYS] as const;

export function useAppliedSummary() {
  return useQuery({
    queryKey: SUMMARY_KEY,
    queryFn: () =>
      api<AppliedSummary>(`v2/applications/summary?days=${SUMMARY_DAYS}`),
    refetchInterval: APPLIED_REFRESH_MS,
  });
}

/** Five headline tiles; `onUnknown` lets the Applied page jump the table to that state. */
export function AppliedKpis({
  summary,
  onUnknown,
}: {
  summary: AppliedSummary;
  onUnknown?: () => void;
}) {
  const t = summary.totals;
  return (
    <div className="metrics applied-metrics" aria-label="Application totals">
      <div className="metric">
        <div className="metric-label">
          Total applied
          <Send size={15} aria-hidden />
        </div>
        <strong>{t.applied_total}</strong>
        <small>Verified submissions, all portals</small>
      </div>
      <div className="metric">
        <div className="metric-label">
          Applied today
          <CalendarCheck size={15} aria-hidden />
        </div>
        <strong>{t.applied_today}</strong>
        <small>India time (IST) calendar day</small>
      </div>
      <div className="metric">
        <div className="metric-label">
          Last 7 days
          <CalendarCheck size={15} aria-hidden />
        </div>
        <strong>{t.applied_7d}</strong>
        <small>Including today</small>
      </div>
      <div className="metric">
        <div className="metric-label">
          Needs your input
          <CircleHelp size={15} aria-hidden />
        </div>
        <strong>{t.waiting_for_user}</strong>
        <small>
          <Link href="/autopilot" className="metric-link">
            Answer in Autopilot inbox
          </Link>
        </small>
      </div>
      <div className="metric">
        <div className="metric-label">
          Unknown submission
          <TriangleAlert size={15} aria-hidden />
        </div>
        <strong>{t.submission_unknown}</strong>
        <small>
          {onUnknown ? (
            <button
              type="button"
              className="metric-link"
              onClick={onUnknown}
              disabled={t.submission_unknown === 0}
            >
              Review these
            </button>
          ) : (
            <Link href="/applied" className="metric-link">
              Open Applied
            </Link>
          )}
        </small>
      </div>
    </div>
  );
}

function AppliedChart({ daily }: { daily: DailyApplied[] }) {
  const max = Math.max(0, ...daily.map((d) => d.applied));
  const total = daily.reduce((sum, d) => sum + d.applied, 0);
  const best = daily.reduce<DailyApplied | undefined>(
    (top, d) => (d.applied > (top?.applied ?? 0) ? d : top),
    undefined,
  );
  return (
    <section className="panel applied-chart-panel" aria-labelledby="chart-h">
      <div className="panel-header">
        <div>
          <h2 id="chart-h">Applied per day</h2>
          <p>
            Last {daily.length} days · {total} total
            {best ? ` · best ${dayLabel(best.date)} (${best.applied})` : ""}
          </p>
        </div>
      </div>
      <div className="panel-body">
        {total === 0 ? (
          <p className="muted">No verified submissions in this window yet.</p>
        ) : (
          <div
            className="bar-chart"
            role="img"
            aria-label={`Applications per day for the last ${daily.length} days: ${daily
              .map((d) => `${dayLabel(d.date)} ${d.applied}`)
              .join(", ")}`}
          >
            {daily.map((d, i) => {
              const tip = `${dayLabel(d.date)}: ${d.applied} applied${
                Object.keys(d.by_platform ?? {}).length
                  ? ` (${Object.entries(d.by_platform ?? {})
                      .map(([p, n]) => `${portalName(p)} ${n}`)
                      .join(", ")})`
                  : ""
              }`;
              return (
                <div className="bar-col" key={d.date} title={tip}>
                  <span className="bar-value">{d.applied || ""}</span>
                  <div className="bar-track">
                    <span
                      className="bar"
                      style={{ height: `${barPercent(d.applied, max)}%` }}
                    />
                  </div>
                  <span className="bar-day" aria-hidden>
                    {i === daily.length - 1
                      ? "Today"
                      : (daily.length - 1 - i) % 2 === 0
                        ? dayLabel(d.date)
                        : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        <details className="spaced">
          <summary>Show as table</summary>
          <table className="compact-table">
            <caption className="visually-hidden">Applications per day</caption>
            <thead>
              <tr>
                <th scope="col">DAY</th>
                <th scope="col">APPLIED</th>
                <th scope="col">BY PORTAL</th>
              </tr>
            </thead>
            <tbody>
              {[...daily].reverse().map((d) => (
                <tr key={d.date}>
                  <td>{dayLabel(d.date)}</td>
                  <td>{d.applied}</td>
                  <td>
                    {Object.entries(d.by_platform ?? {})
                      .map(([p, n]) => `${portalName(p)} ${n}`)
                      .join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </section>
  );
}

function PortalCards({
  summary,
  selected,
  onSelect,
}: {
  summary: AppliedSummary;
  selected: string;
  onSelect: (platform: string) => void;
}) {
  const portals = visiblePortals(summary.portals);
  const card = (p: PortalSummary, label: string, value: string) => (
    <button
      key={value || "all"}
      type="button"
      className={`portal-card ${selected === value ? "active" : ""}`}
      aria-pressed={selected === value}
      onClick={() => onSelect(value)}
    >
      <span className="portal-card-name">{label}</span>
      <strong>{p.applied_total}</strong>
      <span className="portal-card-sub">
        applied · {p.applied_today} today · {p.applied_7d} this week
      </span>
      {(p.submission_unknown > 0 || p.failed > 0 || p.waiting_for_user > 0) && (
        <span className="tag-list">
          {p.waiting_for_user > 0 && (
            <Badge tone="amber">{p.waiting_for_user} need input</Badge>
          )}
          {p.submission_unknown > 0 && (
            <Badge tone="red">{p.submission_unknown} unknown</Badge>
          )}
          {p.failed > 0 && <Badge tone="red">{p.failed} failed</Badge>}
        </span>
      )}
    </button>
  );
  return (
    <section className="spaced" aria-labelledby="portals-h">
      <div className="section-heading">
        <h2 id="portals-h">By portal</h2>
        <p className="muted">
          Select a portal to filter the table.
          {portals.length < summary.portals.length
            ? ` ${summary.portals.length - portals.length} portals with no activity are hidden.`
            : ""}
        </p>
      </div>
      <div
        className="portal-cards spaced"
        role="group"
        aria-label="Portal filter"
      >
        {card(summary.totals, "All portals", "")}
        {portals.map((p) => card(p, portalName(p.platform), p.platform))}
      </div>
    </section>
  );
}

function AppliedTable({
  platform,
  state,
  setState,
}: {
  platform: string;
  state: StateFilter;
  setState: (s: StateFilter) => void;
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  // The page resets to 1 whenever a filter changes (no effect needed).
  const filterKey = `${platform}|${state}|${q}`;
  const [paging, setPaging] = useState({ key: filterKey, page: 1 });
  const page = paging.key === filterKey ? paging.page : 1;
  const setPage = (update: (p: number) => number) =>
    setPaging({ key: filterKey, page: update(page) });
  const list = useQuery({
    queryKey: ["v2-applied-list", platform, state, q, page],
    queryFn: () =>
      api<AppliedPage>(appliedListPath({ platform, state, q, page })),
    refetchInterval: APPLIED_REFRESH_MS,
    placeholderData: keepPreviousData,
  });
  const pages = list.data ? pageCount(list.data.total) : 1;
  const filtered = Boolean(platform || q.trim() || state !== "APPLIED");
  return (
    <section className="spaced" aria-labelledby="table-h">
      <div className="split log-toolbar">
        <div className="section-heading">
          <h2 id="table-h">
            {platform ? `${portalName(platform)} applications` : "Applications"}
          </h2>
          <p className="muted" aria-live="polite">
            {list.data
              ? `${list.data.total} ${state ? readable(state).toLowerCase() : "in any state"} · newest first · refreshes every 30s`
              : "Loading applications…"}
          </p>
        </div>
      </div>
      <div className="filter-panel spaced">
        <div className="filter-search">
          <Search size={16} aria-hidden />
          <label htmlFor="applied-search" className="visually-hidden">
            Search company or role
          </label>
          <Input
            id="applied-search"
            type="search"
            placeholder="Search company or role…"
            value={search}
            maxLength={100}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="state-tabs" role="group" aria-label="State filter">
          {STATE_FILTERS.map(([value, label]) => (
            <button
              key={value || "all"}
              type="button"
              className={`state-tab ${state === value ? "active" : ""}`}
              aria-pressed={state === value}
              onClick={() => setState(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {list.isPending ? (
        <Skeleton />
      ) : list.isError ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : list.data.items.length === 0 ? (
        <Empty
          title={filtered ? "No matches" : "No applications yet"}
          description={
            filtered
              ? "Nothing matches this portal, state and search. Try All states or clear the search."
              : "Verified submissions appear here as soon as the worker applies."
          }
        />
      ) : (
        <>
          <div className="table-wrap" aria-busy={list.isFetching}>
            <table className="applied-table">
              <caption className="visually-hidden">
                Applications, newest first. Open a role to see screening answers
                and state history.
              </caption>
              <thead>
                <tr>
                  <th scope="col">ROLE</th>
                  <th scope="col">PORTAL</th>
                  <th scope="col">STATE</th>
                  <th scope="col">
                    {state === "APPLIED" ? "APPLIED" : "UPDATED"}
                  </th>
                  <th scope="col">
                    <span className="visually-hidden">Job posting</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <Row
                    key={item.id}
                    item={item}
                    open={() => router.push(`/applied/${item.id}`)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <Button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </Button>
            <span>
              Page {page} of {pages}
            </span>
            <Button
              disabled={page >= pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

function Row({ item, open }: { item: AppliedRow; open: () => void }) {
  const when = item.applied_at || item.updated_at || item.created_at;
  return (
    <tr className="clickable-row" onClick={open}>
      <td>
        <Link
          href={`/applied/${item.id}`}
          className="applied-role-link"
          onClick={(e) => e.stopPropagation()}
        >
          <strong>{item.role_title || "Untitled role"}</strong>
        </Link>
        <small>{item.company_name || "Unknown company"}</small>
      </td>
      <td>
        <Badge>{portalName(item.platform)}</Badge>
      </td>
      <td>
        <Badge tone={stateTone(item.state)}>{readable(item.state)}</Badge>
        {item.state !== "APPLIED" && item.reason && (
          <small className="reason-cell">{readable(item.reason)}</small>
        )}
      </td>
      <td>
        <span>{relativeTime(when) || "—"}</span>
        <small>{istStamp(when)}</small>
      </td>
      <td onClick={(e) => e.stopPropagation()}>
        {item.job_url ? (
          <External href={item.job_url} className="small-print">
            Job
          </External>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
    </tr>
  );
}

export function Applied() {
  const summary = useAppliedSummary();
  const [platform, setPlatform] = useState("");
  const [state, setState] = useState<StateFilter>("APPLIED");
  return (
    <>
      <PageTitle
        eyebrow="APPLIED · PYTHON V2 WORKER"
        title="Everything you've applied to"
        description="Every submission the autopilot made, portal by portal, with the screening answers it used. Updates every 30 seconds."
        actions={
          <Link href="/autopilot" className="button secondary">
            Autopilot controls
            <ArrowUpRight size={14} />
          </Link>
        }
      />
      {summary.isPending ? (
        <Skeleton />
      ) : summary.isError ? (
        <ErrorState error={summary.error} retry={() => summary.refetch()} />
      ) : (
        <>
          <AppliedKpis
            summary={summary.data}
            onUnknown={() => setState("SUBMISSION_UNKNOWN")}
          />
          <AppliedChart daily={summary.data.daily} />
          <PortalCards
            summary={summary.data}
            selected={platform}
            onSelect={setPlatform}
          />
        </>
      )}
      {summary.data && summary.data.totals.total === 0 && (
        <div className="spaced">
          <Notice>
            <CircleSlash size={15} aria-hidden /> The worker has not recorded
            any jobs yet. Start it from Autopilot.
          </Notice>
        </div>
      )}
      <AppliedTable platform={platform} state={state} setState={setState} />
    </>
  );
}
