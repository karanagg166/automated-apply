"use client";
// Mission Control overview (spec 3.2): KPI strip, live activity feed and the portal control grid.
import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, RotateCcw } from "lucide-react";
import { api, patch, post, readable } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  GmailPermissionBadge,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { authTone, stamp } from "@/features/autopilot-forms";
import { RULES_KEY } from "@/features/autopilot-rules";
import { QuotaBar } from "@/features/autopilot-status";
import { durationLabel } from "@/features/ops-status-bar";
import { useLiveEvents, useTelemetry } from "@/lib/live-events";
import {
  TELEMETRY_KEY,
  type LiveEvent,
  type PortalRulesRead,
  type PortalTelemetry,
  type WorkerTelemetry,
} from "@/lib/ops-types";

export type FeedFilter = "all" | "applied" | "hitl" | "skipped" | "errors";
const FILTERS: [FeedFilter, string][] = [
  ["all", "All"],
  ["applied", "Applied"],
  ["hitl", "HITL"],
  ["skipped", "Skipped"],
  ["errors", "Errors"],
];

export function eventCategory(event: LiveEvent): FeedFilter | "other" {
  const state = String(event.payload.state ?? "");
  if (event.type === "job.applied" || event.type === "mail.reconciled")
    return "applied";
  if (event.type.startsWith("hitl.")) return "hitl";
  if (event.type === "job.failed" || event.type === "portal.breaker_changed")
    return "errors";
  if (state === "FILTERED_OUT" || event.payload.skipped) return "skipped";
  return "other";
}

export function eventSummary(event: LiveEvent) {
  const p = event.payload;
  const text = (key: string) =>
    typeof p[key] === "string" || typeof p[key] === "number"
      ? String(p[key])
      : "";
  const who = [text("company"), text("title")].filter(Boolean).join(" — ");
  const where = text("platform") ? readable(text("platform")) : "";
  const detail =
    text("step") ||
    text("reason") ||
    text("kind") ||
    text("state") ||
    text("decision");
  return [readable(event.type.replace(".", " ")), who, where, detail]
    .filter(Boolean)
    .join(" · ");
}

const CATEGORY_TONE = {
  applied: "green",
  hitl: "amber",
  errors: "red",
  skipped: "neutral",
  other: "neutral",
  all: "neutral",
} as const;

function Kpis({ data }: { data: WorkerTelemetry }) {
  const cap = data.portals.reduce(
    (sum, p) => sum + (p.enabled ? p.daily_cap : 0),
    0,
  );
  const k = data.kpis;
  const lag = data.first_mover.p50_seconds;
  return (
    <div className="ops-kpis" aria-label="Key metrics">
      <div className="metric">
        <div className="metric-label">APPLIED TODAY</div>
        <strong>{k.applied_today}</strong>
        <QuotaBar
          label="Daily quota"
          used={k.applied_today}
          max={cap || 1}
          hit={false}
        />
      </div>
      <div className="metric">
        <div className="metric-label">VERIFIED RECEIPTS</div>
        <strong>{k.verified_receipts_today}</strong>
        <small>{k.needs_reconciliation} need reconciliation</small>
      </div>
      <Link className="metric metric-link" href="/hitl">
        <div className="metric-label">PENDING HITL</div>
        <strong>{k.pending_hitl}</strong>
        <small>Open inbox</small>
      </Link>
      <div className="metric">
        <div className="metric-label">MEDIAN FIRST-MOVER LAG</div>
        <strong>{lag == null ? "—" : durationLabel(lag)}</strong>
        <small>
          p95 {durationLabel(data.first_mover.p95_seconds) || "—"} ·{" "}
          {data.first_mover.samples} samples
        </small>
      </div>
      <div className="metric">
        <div className="metric-label">CACHE HIT RATE</div>
        <strong>
          {k.cache_hit_rate == null
            ? "—"
            : `${Math.round(k.cache_hit_rate * 100)}%`}
        </strong>
        <small>Semantic cache</small>
      </div>
      <Link className="metric metric-link" href="/watchlist">
        <div className="metric-label">ACTIVE WATCHERS</div>
        <strong>{k.active_watchers}</strong>
        <small>ATS boards</small>
      </Link>
    </div>
  );
}

export function ActivityFeed() {
  const { events, connection } = useLiveEvents();
  const [filter, setFilter] = useState<FeedFilter>("all");
  const rows = useMemo(
    () =>
      events.filter(
        (event) =>
          event.type !== "resync" &&
          (filter === "all" || eventCategory(event) === filter),
      ),
    [events, filter],
  );
  return (
    <section className="panel" aria-labelledby="ops-feed-h">
      <div className="panel-header">
        <div>
          <h2 id="ops-feed-h">Live activity</h2>
          <p>
            Discoveries, skips, applies, HITL and mail reconciliation as they
            happen.
          </p>
        </div>
        <Badge tone={connection === "live" ? "green" : "amber"}>
          {connection === "live" ? "Streaming" : readable(connection)}
        </Badge>
      </div>
      <div className="panel-body stack">
        <div className="state-tabs" role="group" aria-label="Filter activity">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              className={`state-tab ${filter === key ? "active" : ""}`}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {rows.length === 0 ? (
          <p className="muted small-print">
            No {filter === "all" ? "" : `${filter} `}events yet this session.
          </p>
        ) : (
          <ol className="ops-feed" aria-live="polite">
            {rows.slice(0, 80).map((event, index) => (
              <li key={`${event.id ?? "x"}-${index}`}>
                <time dateTime={event.at}>
                  {new Date(event.at).toLocaleTimeString("en-IN")}
                </time>
                <Badge tone={CATEGORY_TONE[eventCategory(event)]}>
                  {event.type}
                </Badge>
                <span>{eventSummary(event)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

const BREAKER_TONE = {
  closed: "green",
  half_open: "amber",
  open: "red",
} as const;

function PortalCard({
  portal,
  rules,
}: {
  portal: PortalTelemetry;
  rules?: PortalRulesRead;
}) {
  const client = useQueryClient();
  const refresh = () => {
    client.invalidateQueries({ queryKey: TELEMETRY_KEY });
    client.invalidateQueries({ queryKey: RULES_KEY });
  };
  const reset = useMutation({
    mutationFn: () => post(`v2/portal-rules/${portal.platform}/breaker/reset`),
    onSuccess: refresh,
  });
  const paused =
    !!portal.paused_until &&
    new Date(portal.paused_until).getTime() > Date.now();
  const toggle = useMutation({
    mutationFn: () => {
      if (!rules) throw new Error("Portal rules not loaded yet");
      const until = paused
        ? null
        : new Date(Date.now() + 30 * 86400_000).toISOString();
      return patch(`v2/portal-rules/${portal.platform}`, {
        revision: rules.revision,
        paused_until: until,
      });
    },
    onSuccess: refresh,
  });
  const name = readable(portal.platform);
  return (
    <article
      className={`portal-status ops-portal ${portal.health}`}
      aria-label={`${name} portal`}
    >
      <div className="split">
        <h3>
          <span className={`ops-health ${portal.health}`} aria-hidden="true" />{" "}
          {name}
        </h3>
        <Badge tone={authTone(portal.auth_status)}>
          {portal.auth_status === "OK"
            ? "Session OK"
            : readable(portal.auth_status)}
        </Badge>
      </div>
      <div className="tag-list">
        <Badge tone={BREAKER_TONE[portal.breaker_state]}>
          Breaker {readable(portal.breaker_state)}
        </Badge>
        {!portal.enabled && <Badge>Disabled</Badge>}
        {paused && (
          <Badge tone="amber">Paused until {stamp(portal.paused_until)}</Badge>
        )}
        {!portal.auto_apply_enabled && portal.enabled && (
          <Badge>Inspect only</Badge>
        )}
      </div>
      {portal.breaker_reason && portal.breaker_state !== "closed" && (
        <p className="muted small-print">{portal.breaker_reason}</p>
      )}
      <QuotaBar
        label="Applied today"
        used={portal.applied_today}
        max={portal.daily_cap}
        hit={portal.applied_today >= portal.daily_cap}
      />
      <QuotaBar
        label="This hour"
        used={portal.applied_this_hour}
        max={portal.hourly_cap}
        hit={portal.applied_this_hour >= portal.hourly_cap}
      />
      <p className="muted small-print">
        Last sweep: {stamp(portal.last_sweep_at)}
      </p>
      <div className="actions">
        <Button
          variant="secondary"
          busy={toggle.isPending}
          disabled={!rules}
          onClick={() => toggle.mutate()}
          aria-label={`${paused ? "Resume" : "Pause"} ${name}`}
        >
          {paused ? "Resume" : "Pause"}
        </Button>
        {portal.breaker_state !== "closed" && (
          <Button
            variant="ghost"
            busy={reset.isPending}
            onClick={() => reset.mutate()}
            aria-label={`Reset ${name} circuit breaker`}
          >
            <RotateCcw size={14} /> Reset breaker
          </Button>
        )}
      </div>
      {(reset.isError || toggle.isError) && (
        <ErrorState error={reset.error ?? toggle.error} />
      )}
    </article>
  );
}

export function PortalGrid({ portals }: { portals: PortalTelemetry[] }) {
  const rules = useQuery({
    queryKey: RULES_KEY,
    queryFn: () => api<PortalRulesRead[]>("v2/portal-rules"),
  });
  const byPlatform = new Map(rules.data?.map((r) => [r.platform, r]));
  return (
    <section className="panel" id="portals" aria-labelledby="ops-portals-h">
      <div className="panel-header">
        <div>
          <h2 id="ops-portals-h">Portal control</h2>
          <p>
            Session freshness, circuit breakers, quotas and per-portal pause.
          </p>
        </div>
      </div>
      <div className="panel-body">
        {portals.length === 0 ? (
          <Empty description="No portals are configured yet." />
        ) : (
          <div className="ops-portal-grid">
            {portals.map((portal) => (
              <PortalCard
                key={portal.platform}
                portal={portal}
                rules={byPlatform.get(portal.platform)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

export function OpsOverview() {
  const telemetry = useTelemetry();
  return (
    <>
      <PageTitle
        eyebrow="MISSION CONTROL"
        title="Operations"
        description="Live worker state, first-mover speed and every portal at a glance. Anything uncertain lands in the HITL inbox."
        actions={
          <div className="actions">
            <GmailPermissionBadge />
            <Link href="/journey" className="external">
              Search journey <ArrowUpRight size={14} />
            </Link>
          </div>
        }
      />
      {telemetry.isPending ? (
        <Skeleton />
      ) : telemetry.isError ? (
        <ErrorState error={telemetry.error} retry={() => telemetry.refetch()} />
      ) : (
        <div className="stack">
          <Kpis data={telemetry.data} />
          <div className="ops-overview-grid">
            <ActivityFeed />
            <PortalGrid portals={telemetry.data.portals} />
          </div>
        </div>
      )}
    </>
  );
}
