"use client";
// Persistent Mission Control strip (spec 3.1): worker state + controls, active task, HITL count,
// Telegram mute and per-portal health — driven by the SSE stream with telemetry polling fallback.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { BellOff, CircleAlert, Pause, Play, Radio } from "lucide-react";
import { post, readable } from "@/lib/api";
import { Button, Input, Modal } from "@/components/ui";
import { useLiveEvents, useTelemetry } from "@/lib/live-events";
import {
  TELEMETRY_KEY,
  type ActiveJob,
  type MuteRead,
  type OpsStatus,
  type PortalTelemetry,
  type TelegramTelemetry,
  type WorkerControl,
  type WorkerTelemetry,
} from "@/lib/ops-types";

const STATUS_LABEL: Record<OpsStatus, string> = {
  RUNNING: "Running",
  PAUSED: "Paused",
  DRY_RUN: "Dry-run",
  OFFLINE: "Offline",
};
const STATUS_TONE: Record<OpsStatus, string> = {
  RUNNING: "green",
  PAUSED: "amber",
  DRY_RUN: "amber",
  OFFLINE: "red",
};

export function clockLabel(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function telegramLabel(telegram: TelegramTelemetry, now = Date.now()) {
  if (!telegram.configured) return { label: "Telegram off", tone: "neutral" };
  if (telegram.muted_until && new Date(telegram.muted_until).getTime() > now)
    return {
      label: `Muted until ${clockLabel(telegram.muted_until)}`,
      tone: "amber",
    };
  if (telegram.quiet_hours_active)
    return { label: "Quiet hours", tone: "amber" };
  return { label: "Telegram active", tone: "green" };
}

export function durationLabel(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function useElapsed(job: ActiveJob | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!job) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job]);
  if (!job) return null;
  if (job.started_at) return (now - new Date(job.started_at).getTime()) / 1000;
  return job.elapsed_sec;
}

function useControl() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: { path: string; body?: Record<string, unknown> }) =>
      post<WorkerControl | MuteRead>(action.path, action.body ?? {}),
    onSuccess: () => client.invalidateQueries({ queryKey: TELEMETRY_KEY }),
  });
}

export function DryRunSwitch({ worker }: { worker: WorkerControl }) {
  const control = useControl();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const toggle = () => {
    if (worker.dry_run) {
      setTyped("");
      setOpen(true);
    } else
      control.mutate({ path: "v2/worker/dry-run", body: { dry_run: true } });
  };
  return (
    <>
      <button
        type="button"
        role="switch"
        aria-checked={worker.dry_run}
        aria-label="Dry-run mode"
        className={`ops-switch ${worker.dry_run ? "on" : ""}`}
        disabled={control.isPending}
        onClick={toggle}
      >
        <span aria-hidden="true" />
        Dry-run
      </button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Go live?"
        description="Turning dry-run off lets the worker click the final Submit on real applications."
      >
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (typed !== "LIVE") return;
            control.mutate(
              {
                path: "v2/worker/dry-run",
                body: { dry_run: false, confirm: "LIVE" },
              },
              { onSuccess: () => setOpen(false) },
            );
          }}
        >
          <label htmlFor="ops-live-confirm" className="small-print">
            Type <strong>LIVE</strong> to confirm.
          </label>
          <Input
            id="ops-live-confirm"
            autoFocus
            autoComplete="off"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          {control.isError && (
            <p className="form-error" role="alert">
              {control.error instanceof Error
                ? control.error.message
                : "Could not change dry-run"}
            </p>
          )}
          <div className="actions">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
            >
              Keep dry-run
            </Button>
            <Button
              type="submit"
              variant="danger"
              disabled={typed !== "LIVE"}
              busy={control.isPending}
            >
              Disable dry-run
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}

function WorkerControls({ data }: { data: WorkerTelemetry }) {
  const control = useControl();
  const running = data.worker.desired_state === "RUNNING";
  return (
    <div className="ops-group">
      <span
        className={`ops-badge ${STATUS_TONE[data.status]}`}
        role="status"
        aria-label={`Worker ${STATUS_LABEL[data.status]}`}
      >
        <span className="ops-dot" aria-hidden="true" />
        {STATUS_LABEL[data.status]}
      </span>
      <Button
        variant="ghost"
        className="ops-mini"
        busy={control.isPending}
        aria-label={running ? "Pause worker" : "Resume worker"}
        onClick={() =>
          control.mutate({
            path: running ? "v2/worker/pause" : "v2/worker/start",
          })
        }
      >
        {running ? <Pause size={14} /> : <Play size={14} />}
        {running ? "Pause" : "Resume"}
      </Button>
      <DryRunSwitch worker={data.worker} />
    </div>
  );
}

function ActiveTask({ job }: { job: ActiveJob | null }) {
  const elapsed = useElapsed(job);
  if (!job) return <span className="ops-pill muted">Idle</span>;
  const who = [job.company, job.title].filter(Boolean).join(" — ");
  const step = job.step ? `Step: ${job.step} · ` : "";
  return (
    <span className="ops-pill" title={who}>
      Applying: {who || readable(job.platform)} ({step}
      {durationLabel(elapsed) || "0s"})
    </span>
  );
}

function TelegramPill({ telegram }: { telegram: TelegramTelemetry }) {
  const control = useControl();
  const { label, tone } = telegramLabel(telegram);
  const mute = (minutes: number | null) =>
    control.mutate({ path: "v2/telegram/mute", body: { minutes } });
  return (
    <div className="ops-group" role="group" aria-label="Telegram notifications">
      <span className={`ops-badge ${tone}`}>
        <BellOff size={12} aria-hidden="true" />
        {label}
      </span>
      {telegram.configured && (
        <>
          <button
            className="ops-chip"
            onClick={() => mute(60)}
            disabled={control.isPending}
          >
            Mute 1h
          </button>
          <button
            className="ops-chip"
            onClick={() => mute(120)}
            disabled={control.isPending}
          >
            2h
          </button>
          <button
            className="ops-chip"
            onClick={() => mute(null)}
            disabled={control.isPending}
          >
            Off
          </button>
        </>
      )}
    </div>
  );
}

export function portalTooltip(portal: PortalTelemetry) {
  const parts = [
    readable(portal.platform),
    `auth ${readable(portal.auth_status)}`,
    `breaker ${portal.breaker_state}`,
    `${portal.applied_today}/${portal.daily_cap} today`,
  ];
  if (portal.breaker_reason) parts.push(portal.breaker_reason);
  return parts.join(" · ");
}

function PortalDots({ portals }: { portals: PortalTelemetry[] }) {
  return (
    <ul className="ops-dots" aria-label="Portal health">
      {portals.map((portal) => (
        <li key={portal.platform}>
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <Link
                href="/#portals"
                className={`ops-health ${portal.health}`}
                aria-label={portalTooltip(portal)}
              />
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content className="ops-tooltip" sideOffset={6}>
                {portalTooltip(portal)}
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        </li>
      ))}
    </ul>
  );
}

export function OpsStatusBar() {
  const telemetry = useTelemetry();
  const { connection } = useLiveEvents();
  const data = telemetry.data;
  return (
    <section className="ops-bar" aria-label="Operations status">
      <span
        className={`ops-stream ${connection}`}
        title={`Live stream: ${connection}`}
      >
        <Radio size={12} aria-hidden="true" />
        <span className="visually-hidden">Live stream </span>
        {connection === "live"
          ? "Live"
          : connection === "polling"
            ? "Polling"
            : "Connecting"}
      </span>
      {!data ? (
        <span className="ops-badge red" role="status">
          <CircleAlert size={12} aria-hidden="true" />
          {telemetry.isError ? "Worker offline" : "Loading worker…"}
        </span>
      ) : (
        <>
          <WorkerControls data={data} />
          <ActiveTask job={data.active_job} />
          <Link
            href="/hitl"
            className={`ops-hitl ${data.kpis.pending_hitl ? "pending" : ""}`}
            aria-label={`${data.kpis.pending_hitl} pending HITL requests`}
          >
            HITL <strong>{data.kpis.pending_hitl}</strong>
          </Link>
          <TelegramPill telegram={data.telegram} />
          <PortalDots portals={data.portals} />
        </>
      )}
    </section>
  );
}
