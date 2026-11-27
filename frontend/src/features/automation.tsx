"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable, ApiError } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Select,
  Skeleton,
} from "@/components/ui";

type Configuration = {
  enabled: boolean;
  sources: string[];
  interval_seconds: number;
  limit: number;
  approved_profile_id: string | null;
  approved_profile_version: number | null;
};
type Status = {
  state: string;
  version: number;
  configuration: Configuration;
  blockers: string[];
  next_run_at: string | null;
  last_run_at: string | null;
  worker_ready: boolean;
  profile: { id: string; version: number } | null;
  matching: string;
};
type Execution = {
  id: string;
  source: string;
  trigger_type: string;
  state: string;
  diagnostic: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  outcome: {
    counts?: Record<string, number>;
    job_ids?: string[];
    evidence_mode?: string;
    next_allowed_at?: string;
  };
};
type Plan = {
  provider_calls: number;
  matching: string;
  blockers: string[];
  sources: {
    source: string;
    minimum_interval_seconds: number;
    next_allowed_at: string | null;
    configured: boolean;
  }[];
};
const stamp = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "Not planned";

export function Automation() {
  const client = useQueryClient();
  const [draft, setDraft] = useState<Configuration | null>(null);
  const [filter, setFilter] = useState("");
  const status = useQuery({
    queryKey: ["automation"],
    queryFn: () => api<Status>("dashboard/automation"),
    refetchInterval: 15000,
  });
  const history = useQuery({
    queryKey: ["automation-history", filter],
    queryFn: () =>
      api<{ executions: Execution[] }>(
        `dashboard/automation/history${filter ? `?state=${filter}` : ""}`,
      ),
    refetchInterval: 15000,
  });
  const matches = useQuery({
    queryKey: ["automation-matches"],
    queryFn: () =>
      api<{
        matches: {
          job_id: string;
          match_score: number;
          profile_version: number;
          unknown_fields: string[];
        }[];
      }>("dashboard/automation/matches"),
    refetchInterval: 15000,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["automation"] });
    client.invalidateQueries({ queryKey: ["automation-history"] });
    client.invalidateQueries({ queryKey: ["automation-matches"] });
  };
  const save = useMutation({
    mutationFn: (configuration: Configuration) =>
      api<Status>("dashboard/automation", {
        method: "PUT",
        body: JSON.stringify({
          expected_version: status.data?.version,
          configuration,
        }),
      }),
    onSuccess: () => {
      setDraft(null);
      plan.reset();
      refresh();
    },
  });
  const plan = useMutation({
    mutationFn: () => post<Plan>("dashboard/automation/preview"),
  });
  const run = useMutation({
    // Milestone 2: the v1 queue row this used to create had no consumer; ask the v2 worker for one
    // bounded cycle instead (same control as Autopilot "Run once").
    mutationFn: () => post<{ desired_state: string }>("v2/worker/run-once"),
    onSuccess: refresh,
  });
  const pause = useMutation({
    mutationFn: async () => {
      const prefs = await api<Record<string, unknown>>(
        "dashboard/notification-preferences",
      );
      return api("dashboard/notification-preferences", {
        method: "PUT",
        body: JSON.stringify({ ...prefs, paused: true }),
      });
    },
  });
  if (status.isPending) return <Skeleton />;
  if (status.isError)
    return (
      <section className="panel panel-body stack">
        <h2>Discovery automation</h2>
        <Notice>
          {status.error instanceof ApiError && status.error.status >= 500
            ? "Blocked by missing production database or incompatible schema. Automation has not started."
            : "Automation status is unavailable."}
        </Notice>
        <ErrorState error={status.error} />
      </section>
    );
  const data = status.data,
    config = draft || data.configuration;
  const activationBlocked = data.blockers.includes(
    "operational_activation_required",
  );
  return (
    <section className="panel spaced" aria-label="Discovery automation">
      <div className="panel-header">
        <h2>Discovery automation</h2>
        <Badge>{readable(data.state)}</Badge>
      </div>
      <div className="panel-body stack">
        <Notice>
          Discovery and preparation remain owner controlled. Live automation
          requires separate operational approval.{" "}
          {activationBlocked
            ? "Operational activation is disabled."
            : "Operational gate configured."}
        </Notice>
        <p>
          Next planned run: {stamp(data.next_run_at)} · Last admitted run:{" "}
          {stamp(data.last_run_at)}
        </p>
        <p>
          Worker:{" "}
          {data.worker_ready
            ? "Heartbeat current"
            : "Stopped or heartbeat stale"}{" "}
          · Matching: {readable(data.matching)}
        </p>
        <div className="form-grid">
          <Field
            label="Discovery interval (seconds)"
            hint="At least 300 seconds; Remotive requires at least 21600 seconds."
          >
            <Input
              type="number"
              min={300}
              max={604800}
              value={config.interval_seconds}
              onChange={(e) =>
                setDraft({
                  ...config,
                  interval_seconds: Number(e.target.value),
                })
              }
            />
          </Field>
          <Field label="Maximum results per source">
            <Input
              type="number"
              min={1}
              max={50}
              value={config.limit}
              onChange={(e) =>
                setDraft({ ...config, limit: Number(e.target.value) })
              }
            />
          </Field>
        </div>
        <fieldset className="stack">
          <legend>Approved public sources</legend>
          {["hacker_news", "arbeitnow", "remotive", "greenhouse"].map(
            (source) => (
              <label className="check-label" key={source}>
                <input
                  type="checkbox"
                  checked={config.sources.includes(source)}
                  onChange={(e) =>
                    setDraft({
                      ...config,
                      sources: e.target.checked
                        ? [...config.sources, source]
                        : config.sources.filter((s) => s !== source),
                    })
                  }
                />
                {readable(source)}
                {source === "greenhouse" &&
                  " (owner-configured boards required)"}
              </label>
            ),
          )}
        </fieldset>
        <label className="check-label">
          <input
            type="checkbox"
            disabled={!data.profile}
            checked={
              !!data.profile &&
              config.approved_profile_id === data.profile.id &&
              config.approved_profile_version === data.profile.version
            }
            onChange={(e) =>
              setDraft({
                ...config,
                approved_profile_id: e.target.checked ? data.profile!.id : null,
                approved_profile_version: e.target.checked
                  ? data.profile!.version
                  : null,
              })
            }
          />
          I reviewed and approve saved profile version{" "}
          {data.profile?.version || "(missing)"} for automated matching.
        </label>
        <div className="tag-list">
          <Button busy={save.isPending} onClick={() => save.mutate(config)}>
            Save automation configuration
          </Button>
          <Button
            disabled={activationBlocked || !!draft}
            busy={save.isPending}
            onClick={() => save.mutate({ ...config, enabled: !config.enabled })}
          >
            {config.enabled ? "Disable automation" : "Enable automation"}
          </Button>
          <Button
            disabled={!!draft}
            busy={plan.isPending}
            onClick={() => plan.mutate()}
          >
            Preview saved automation plan
          </Button>
          <Button
            disabled={
              !data.configuration.enabled || activationBlocked || !!draft
            }
            busy={run.isPending}
            onClick={() => run.mutate()}
          >
            Run Now
          </Button>
          <Button busy={pause.isPending} onClick={() => pause.mutate()}>
            Pause notifications
          </Button>
        </div>
        {draft && (
          <Notice>Save configuration before previewing or running.</Notice>
        )}
        {[save, plan, run, pause].map((mutation, index) =>
          mutation.isError ? (
            <ErrorState key={index} error={mutation.error} />
          ) : null,
        )}
        {pause.isSuccess && (
          <Notice>
            Notifications paused.{" "}
            <Link href="/settings">Review notification settings</Link>
          </Notice>
        )}
        {run.isSuccess && (
          <Notice>
            Run-once requested from the v2 worker. Results appear in Autopilot;
            this is not provider success.{" "}
            <Button onClick={() => run.reset()}>
              Prepare another run request
            </Button>
          </Notice>
        )}
        {plan.data && (
          <div className="evidence-item">
            <h3>Saved automation plan</h3>
            <p>
              {plan.data.provider_calls} provider calls · Matching:{" "}
              {readable(plan.data.matching)}
            </p>
            {plan.data.sources.map((source) => (
              <p key={source.source}>
                {readable(source.source)} ·{" "}
                {source.configured ? "Configured" : "Awaiting configuration"} ·
                Minimum interval {source.minimum_interval_seconds}s · Next
                source access: {stamp(source.next_allowed_at)}
              </p>
            ))}
            <p>{plan.data.blockers.map(readable).join(" · ")}</p>
          </div>
        )}
        <div className="split">
          <h3>Execution history</h3>
          <Field label="Execution status filter">
            <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All executions</option>
              {[
                "pending",
                "running",
                "completed",
                "partial",
                "failed",
                "blocked",
              ].map((state) => (
                <option key={state} value={state}>
                  {readable(state)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {history.isError && <ErrorState error={history.error} />}
        {history.data?.executions.length === 0 && (
          <p>
            No executions recorded. No scheduled provider work has occurred.
          </p>
        )}
        {history.data?.executions.map((item) => (
          <div className="evidence-item" key={item.id}>
            <strong>
              {readable(item.source)} · {readable(item.state)}
            </strong>
            <p>
              {readable(item.trigger_type)} · Created {stamp(item.created_at)} ·
              Started {stamp(item.started_at)} · Finished{" "}
              {stamp(item.finished_at)}
            </p>
            <p>
              Execution {item.id} · {readable(item.diagnostic)} ·{" "}
              {readable(item.outcome.evidence_mode)}
            </p>
            <p>
              {Object.entries(item.outcome.counts || {})
                .map(([name, count]) => `${readable(name)}: ${count}`)
                .join(" · ")}
            </p>
            {item.outcome.next_allowed_at && (
              <p>Source cooldown until {stamp(item.outcome.next_allowed_at)}</p>
            )}
            {item.outcome.job_ids?.map((id) => (
              <p key={id}>
                <Link href={`/jobs/${id}`}>Review saved opportunity</Link>
              </p>
            ))}
          </div>
        ))}
        <h3>Approved profile matches</h3>
        {matches.isError && <ErrorState error={matches.error} />}
        {matches.data?.matches.length === 0 && (
          <p>No current approved match results.</p>
        )}
        {matches.data?.matches.map((match) => (
          <div className="evidence-item" key={match.job_id}>
            <Link href={`/jobs/${match.job_id}`}>
              Review opportunity · {match.match_score}% relevance
            </Link>
            <p>
              Profile version {match.profile_version} · Unknown evidence:{" "}
              {match.unknown_fields.map(readable).join(", ") || "None reported"}
            </p>
          </div>
        ))}
        <Link href="/jobs">
          Review saved jobs and prepare application packets
        </Link>
      </div>
    </section>
  );
}
