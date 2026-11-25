"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Modal,
  Notice,
  Skeleton,
} from "@/components/ui";
import {
  ageLabel,
  authTone,
  quotaPercent,
  stamp,
} from "@/features/autopilot-forms";
import { TelegramStatusBadge } from "@/features/autopilot-hitl";

type Status = Schema<"AutomationStatus">;
type Worker = Schema<"WorkerControlRead">;
type PortalStatus = Schema<"PortalStatus">;
type WorkerAction =
  { kind: "start"; dryRun: boolean } | { kind: "pause" | "stop" | "run-once" };

export const STATUS_KEY = ["v2-status"] as const;

function actionLabel(action: WorkerAction) {
  if (action.kind === "start")
    return action.dryRun
      ? "Start requested in dry-run mode (stops before the final Submit)."
      : "Start requested in LIVE mode — real applications will be submitted.";
  if (action.kind === "pause") return "Pause requested.";
  if (action.kind === "stop") return "Stop requested.";
  return "One cycle requested.";
}

export function QuotaBar({
  label,
  used,
  max,
  hit,
}: {
  label: string;
  used: number;
  max: number;
  hit: boolean;
}) {
  const percent = quotaPercent(used, max);
  const tone = hit || percent >= 100 ? "red" : percent >= 80 ? "amber" : "";
  return (
    <div className="quota">
      <div className="quota-label">
        <span>{label}</span>
        <strong>
          {used} / {max}
          {hit ? " · limit reached" : ""}
        </strong>
      </div>
      <div
        className={`quota-bar ${tone}`}
        role="progressbar"
        aria-label={`${label}: ${used} of ${max}`}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(used, max)}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function PortalStatusCard({ portal }: { portal: PortalStatus }) {
  return (
    <div
      className="portal-status"
      aria-label={`${readable(portal.platform)} status`}
    >
      <div className="split">
        <h3>{readable(portal.platform)}</h3>
        <Badge tone={authTone(portal.auth_status)}>
          {portal.auth_status === "OK"
            ? "Session OK"
            : portal.auth_status === "AUTH_REQUIRED"
              ? "Login required"
              : "Session unknown"}
        </Badge>
      </div>
      {portal.auth_status === "AUTH_REQUIRED" && (
        <p className="portal-hint">
          Run <code>login-setup</code> for this portal, then reply{" "}
          <code>/resume {portal.platform}</code> in Telegram. Other portals keep
          running.
        </p>
      )}
      <div className="tag-list">
        <Badge tone={portal.enabled ? "green" : "neutral"}>
          {portal.enabled ? "Enabled" : "Disabled"}
        </Badge>
        <Badge tone={portal.auto_apply_enabled ? "green" : "neutral"}>
          {portal.auto_apply_enabled ? "Auto-apply on" : "Auto-apply off"}
        </Badge>
        <Badge tone={portal.within_active_hours ? "green" : "neutral"}>
          {portal.within_active_hours
            ? "Within active hours"
            : "Outside active hours"}
        </Badge>
        {portal.waiting_for_user > 0 && (
          <Badge tone="amber">{portal.waiting_for_user} waiting for you</Badge>
        )}
        {portal.portal_limit_hit_today && (
          <Badge tone="red">Portal limit hit today</Badge>
        )}
      </div>
      <QuotaBar
        label="Applied today"
        used={portal.applied_today}
        max={portal.max_applies_per_day}
        hit={portal.daily_limit_hit}
      />
      <QuotaBar
        label="Applied this hour"
        used={portal.applied_this_hour}
        max={portal.max_applies_per_hour}
        hit={portal.hourly_limit_hit}
      />
    </div>
  );
}

export function WorkerStatusPanel() {
  const client = useQueryClient();
  const [confirmLive, setConfirmLive] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const status = useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => api<Status>("v2/status"),
    refetchInterval: 10000,
  });
  const control = useMutation({
    mutationFn: (action: WorkerAction) =>
      action.kind === "start"
        ? post<Worker>("v2/worker/start", { dry_run: action.dryRun })
        : post<Worker>(`v2/worker/${action.kind}`),
    onSuccess: (worker) => {
      client.setQueryData<Status>(STATUS_KEY, (current) =>
        current ? { ...current, worker } : current,
      );
      client.invalidateQueries({ queryKey: STATUS_KEY });
      setConfirmLive(false);
      setAcknowledged(false);
    },
  });
  if (status.isPending) return <Skeleton />;
  if (status.isError)
    return <ErrorState error={status.error} retry={() => status.refetch()} />;
  const { worker, portals, waiting_for_user } = status.data;
  const busy = control.isPending;
  return (
    <section className="panel" aria-labelledby="worker-heading">
      <div className="panel-header">
        <div>
          <h2 id="worker-heading">Live worker &amp; queue</h2>
          <p>
            Refreshes every 10 seconds · Updated{" "}
            {stamp(status.data.generated_at)}
          </p>
        </div>
        <div className="tag-list">
          <Badge
            tone={
              worker.desired_state === "RUNNING"
                ? "green"
                : worker.desired_state === "PAUSED"
                  ? "amber"
                  : "neutral"
            }
          >
            Desired: {worker.desired_state}
          </Badge>
          <Badge tone={worker.dry_run ? "amber" : "red"}>
            {worker.dry_run ? "Dry run" : "Live submissions"}
          </Badge>
          <TelegramStatusBadge />
        </div>
      </div>
      <div className="panel-body stack">
        {worker.stale && (
          <div className="notice warn" role="alert">
            Worker process not running — no heartbeat for{" "}
            {worker.heartbeat_at
              ? ageLabel(worker.heartbeat_age_sec).replace(" ago", "")
              : "any cycle yet"}
            . Controls are saved but nothing runs until the worker process is
            started on the Mac.
          </div>
        )}
        <dl className="worker-facts">
          <div>
            <dt>Observed state</dt>
            <dd>{readable(worker.observed_state)}</dd>
          </div>
          <div>
            <dt>Heartbeat</dt>
            <dd>{ageLabel(worker.heartbeat_age_sec)}</dd>
          </div>
          <div>
            <dt>Current portal</dt>
            <dd>
              {worker.current_platform
                ? readable(worker.current_platform)
                : "Idle"}
            </dd>
          </div>
          <div>
            <dt>Last cycle</dt>
            <dd>{stamp(worker.last_cycle_at)}</dd>
          </div>
          <div>
            <dt>Waiting for you</dt>
            <dd>{waiting_for_user}</dd>
          </div>
          {worker.run_once_requested_at && (
            <div>
              <dt>Run-once requested</dt>
              <dd>{stamp(worker.run_once_requested_at)}</dd>
            </div>
          )}
        </dl>
        {worker.last_error && (
          <div className="notice warn">
            <strong>Last error:</strong> {worker.last_error}
          </div>
        )}
        <div className="actions">
          <Button
            variant="primary"
            busy={busy}
            onClick={() => control.mutate({ kind: "start", dryRun: true })}
          >
            Start dry run
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              control.reset();
              setAcknowledged(false);
              setConfirmLive(true);
            }}
          >
            Start live…
          </Button>
          <Button
            busy={busy}
            disabled={worker.desired_state === "PAUSED"}
            onClick={() => control.mutate({ kind: "pause" })}
          >
            Pause
          </Button>
          <Button
            busy={busy}
            disabled={worker.desired_state === "STOPPED"}
            onClick={() => control.mutate({ kind: "stop" })}
          >
            Stop
          </Button>
          <Button
            busy={busy}
            onClick={() => control.mutate({ kind: "run-once" })}
          >
            Run one cycle
          </Button>
        </div>
        <p className="muted small-print">
          Dry run walks every step but stops before the final Submit/Apply
          click. Pause keeps the queue; Stop ends the loop after the current
          job. Every application is reserved before clicking and never replayed.
        </p>
        {control.isSuccess && control.variables && (
          <Notice>
            {actionLabel(control.variables)} The worker applies it on its next
            heartbeat.
          </Notice>
        )}
        {control.isError && !confirmLive && (
          <ErrorState error={control.error} />
        )}
        <h3>Portals</h3>
        {portals.length === 0 ? (
          <p className="muted">No portals are configured yet.</p>
        ) : (
          <div className="portal-grid">
            {portals.map((portal) => (
              <PortalStatusCard key={portal.platform} portal={portal} />
            ))}
          </div>
        )}
      </div>
      <Modal
        open={confirmLive}
        onOpenChange={(open) => {
          setConfirmLive(open);
          if (!open) setAcknowledged(false);
        }}
        title="Start live applications?"
        description="Live mode clicks the final Submit/Apply button on real job portals. Submitted applications cannot be withdrawn from here."
      >
        <div className="stack">
          <label className="check-label">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            I understand this submits real applications under my name, within
            the portal caps and rules saved below.
          </label>
          {control.isError && <ErrorState error={control.error} />}
          <div className="actions">
            <Button
              variant="danger"
              disabled={!acknowledged}
              busy={busy}
              onClick={() => control.mutate({ kind: "start", dryRun: false })}
            >
              Start live applications
            </Button>
            <Button variant="ghost" onClick={() => setConfirmLive(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
