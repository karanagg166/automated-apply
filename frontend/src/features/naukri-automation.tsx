"use client";

import { useState } from "react";
import { Button, Field, Input, Notice, Select } from "@/components/ui";
import { api, post, readable } from "@/lib/api";

type Policy = {
  profile_version: number;
  resume_resource_id: string;
  resume_version: string;
  allowed_roles: string[];
  allowed_locations: string[];
  excluded_companies: string[];
  experience_min: number;
  experience_max: number;
  minimum_match_score: number;
  interval_seconds: number;
  max_preparations_per_day: number;
  telegram_questions: boolean;
  source?: string;
  gmail_account_id?: string | null;
  gmail_policy_version?: number | null;
};
export type NaukriAutomationStatus = {
  state: string;
  revision: number;
  policy: Policy | null;
  scope: string;
  source: string;
  worker_online: boolean;
  worker_heartbeat_at: string | null;
  last_check_at?: string;
  next_check_at?: string;
  last_observation: string | null;
  chrome_profile: {
    label: string;
    status: string;
    commands_enabled: boolean;
    last_heartbeat: string;
  } | null;
  blockers: string[];
  counts: Record<string, number>;
  stages: Record<string, string>;
  policy_context: {
    profile_version: number | null;
    resume: {
      resource_id: string;
      resource_version: string;
      label: string;
    } | null;
  };
  decisions: {
    id: string;
    title: string;
    reason: string;
    evaluated_at: string;
    last_observation: string | null;
    source: string;
  }[];
  alert_candidates?: {
    id: string;
    url: string;
    requisition_id: string;
    state: string;
    reason: string;
  }[];
  source_last_check_at?: string | null;
  source_next_at?: string | null;
  chrome_channel_available?: boolean;
};

const when = (s?: string | null) =>
  s ? new Date(s).toLocaleString() : "Never observed";
const list = (s: string) =>
  s
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

export function NaukriAutomation({
  data,
  busy,
  act,
  reviewAlert,
}: {
  data: NaukriAutomationStatus;
  busy: boolean;
  act: (work: () => Promise<unknown>) => Promise<void>;
  reviewAlert?: (id: string, url: string) => void;
}) {
  const [roles, setRoles] = useState(
    data.policy?.allowed_roles.join(", ") || "",
  );
  const [locations, setLocations] = useState(
    data.policy?.allowed_locations.join(", ") || "",
  );
  const [excluded, setExcluded] = useState(
    data.policy?.excluded_companies.join(", ") || "",
  );
  const [minimum, setMinimum] = useState(data.policy?.experience_min ?? 0);
  const [maximum, setMaximum] = useState(data.policy?.experience_max ?? 3);
  const [score, setScore] = useState(data.policy?.minimum_match_score ?? 80);
  const [cadence, setCadence] = useState(
    (data.policy?.interval_seconds ?? 21600) / 60,
  );
  const [daily, setDaily] = useState(
    data.policy?.max_preparations_per_day ?? 5,
  );
  const [telegram, setTelegram] = useState(
    data.policy?.telegram_questions ?? false,
  );
  const [source, setSource] = useState(
    data.policy?.source || "saved_owner_imports",
  );
  const [accountId, setAccountId] = useState(
    data.policy?.gmail_account_id || "",
  );
  const [gmailVersion, setGmailVersion] = useState(
    data.policy?.gmail_policy_version || 1,
  );
  const { profile_version: version, resume } = data.policy_context;
  return (
    <section className="panel panel-body stack" aria-label="Naukri automation">
      <h2>Automation control</h2>
      <Notice>
        Partial capability: recurring preparation of owner-supplied records. New
        vacancy discovery requires an approved source and factual review.
        Browser filling needs separate permission and exact field approval.
        Automated submission is unavailable. Only an existing approved local
        Gmail alert policy may supply email candidates. The separate legacy
        Gmail adapter remains disabled.
      </Notice>
      <p>
        Persisted state: <strong>{data.state}</strong> · {readable(data.scope)}
      </p>
      <div className="actions">
        {(["start", "pause", "stop"] as const).map((action) => (
          <Button
            key={action}
            disabled={
              busy ||
              (action === "start" && (!data.policy || data.state === "RUNNING"))
            }
            onClick={() =>
              act(() =>
                post("execution/naukri/automation/control", {
                  action,
                  expected_revision: data.revision,
                }),
              )
            }
          >
            {action.toUpperCase()} AUTOMATION
          </Button>
        ))}
      </div>
      <p>
        Start schedules bounded preparation. Pause and Stop fence pending work;
        starting again preserves individually paused applications.
      </p>
      <p>
        Selected Chrome profile: {data.chrome_profile?.label || "None selected"}{" "}
        · {data.chrome_profile?.status || "Not connected"}
      </p>
      <p>
        Extension heartbeat: {when(data.chrome_profile?.last_heartbeat)} ·
        Command channel:{" "}
        {data.chrome_channel_available && data.chrome_profile?.commands_enabled
          ? "Profile opted in"
          : "Not enabled"}
      </p>
      <p>
        Worker: {data.worker_online ? "Online" : "Offline"} · Last database
        heartbeat: {when(data.worker_heartbeat_at)}
      </p>
      <p>
        Source: {readable(data.source)} · Last observation:{" "}
        {when(data.last_observation)}
      </p>
      {data.source === "gmail_job_alerts" && (
        <p>
          Last email check: {when(data.source_last_check_at)} · Next email
          check:{" "}
          {data.state === "RUNNING" ? when(data.source_next_at) : "Inactive"}.
          Email leads need factual review; no linked pages are fetched.
        </p>
      )}
      <p>
        Last discovery/preparation check: {when(data.last_check_at)} · Next
        scheduled check:{" "}
        {data.state === "RUNNING"
          ? data.next_check_at
            ? when(data.next_check_at)
            : "Due on next worker tick"
          : "Inactive"}
      </p>
      <dl>
        {Object.entries({
          matching: "Matching jobs found",
          prepared: "Applications prepared",
          naukri_recorded:
            "Naukri-recorded applications (retained UI evidence)",
          installed_worker_recorded:
            "Applications recorded from recurring worker",
          employer_acknowledged: "Independent employer acknowledgments",
          failed: "Failed jobs",
          unknown: "Unknown submission outcomes",
          manual_required: "Manual-required items",
        }).map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{data.counts[key] ?? 0}</dd>
          </div>
        ))}
      </dl>
      <p>Blocks to full automation:</p>
      <ul>
        {data.blockers.map((reason) => (
          <li key={reason}>{readable(reason)}</li>
        ))}
      </ul>
      <details>
        <summary>Execution stages</summary>
        <dl>
          {Object.entries(data.stages).map(([stage, value]) => (
            <div key={stage}>
              <dt>{stage}</dt>
              <dd>{readable(value)}</dd>
            </div>
          ))}
        </dl>
      </details>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (!version || !resume) return;
          void act(() =>
            api("execution/naukri/automation/policy", {
              method: "PUT",
              body: JSON.stringify({
                expected_revision: data.revision,
                policy: {
                  profile_version: version,
                  resume_resource_id: resume.resource_id,
                  resume_version: resume.resource_version,
                  allowed_roles: list(roles),
                  allowed_locations: list(locations),
                  excluded_companies: list(excluded),
                  experience_min: minimum,
                  experience_max: maximum,
                  minimum_match_score: score,
                  interval_seconds: cadence * 60,
                  max_preparations_per_day: daily,
                  telegram_questions: telegram,
                  source,
                  ...(source === "gmail_job_alerts"
                    ? {
                        gmail_account_id: accountId,
                        gmail_policy_version: gmailVersion,
                      }
                    : {}),
                },
              }),
            }),
          );
        }}
      >
        <h3>Bounded preparation policy</h3>
        <Field label="Discovery input source">
          <Select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="saved_owner_imports">Owner-supplied postings</option>
            <option value="gmail_job_alerts" disabled>
              Legacy Gmail job-alert adapter (unavailable)
            </option>
          </Select>
        </Field>
        {source === "gmail_job_alerts" && (
          <>
            <Notice>
              Configure official alerts in your own Naukri account. Separately
              approve one Gmail read-only account, body access and an exact
              Naukri sender allowlist. Email monitoring also requires explicit
              deployment activation. This policy does not grant mailbox access.
            </Notice>
            <Field label="Approved Gmail read account UUID">
              <Input
                required
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              />
            </Field>
            <Field label="Approved Gmail read policy version">
              <Input
                type="number"
                required
                min={1}
                value={gmailVersion}
                onChange={(e) => setGmailVersion(Number(e.target.value))}
              />
            </Field>
          </>
        )}
        <p>
          Confirmed profile:{" "}
          {version ? `v${version}` : "Review current profile first"} · Approved
          primary resume:{" "}
          {resume?.label || "Select and confirm a primary resume first"}
        </p>
        <Field label="Allowed exact role titles (comma separated)">
          <Input
            required
            value={roles}
            onChange={(e) => setRoles(e.target.value)}
          />
        </Field>
        <Field label="Allowed exact locations (comma separated)">
          <Input
            required
            value={locations}
            onChange={(e) => setLocations(e.target.value)}
          />
        </Field>
        <Field label="Excluded companies (comma separated)">
          <Input
            value={excluded}
            onChange={(e) => setExcluded(e.target.value)}
          />
        </Field>
        <Field label="Minimum experience years">
          <Input
            type="number"
            min={0}
            max={60}
            step="0.5"
            value={minimum}
            onChange={(e) => setMinimum(Number(e.target.value))}
          />
        </Field>
        <Field label="Maximum experience years">
          <Input
            type="number"
            min={minimum}
            max={60}
            step="0.5"
            value={maximum}
            onChange={(e) => setMaximum(Number(e.target.value))}
          />
        </Field>
        <Field label="Minimum match score">
          <Input
            type="number"
            min={80}
            max={100}
            value={score}
            onChange={(e) => setScore(Number(e.target.value))}
          />
        </Field>
        <Field label="Check interval in minutes">
          <Input
            type="number"
            min={15}
            max={10080}
            value={cadence}
            onChange={(e) => setCadence(Number(e.target.value))}
          />
        </Field>
        <Field label="Maximum preparations per UTC day">
          <Input
            type="number"
            min={1}
            max={25}
            value={daily}
            onChange={(e) => setDaily(Number(e.target.value))}
          />
        </Field>
        <label>
          <input
            type="checkbox"
            checked={telegram}
            onChange={(e) => setTelegram(e.target.checked)}
          />{" "}
          Queue factual questions through the already approved Telegram channel
        </label>
        <p>
          Platform: Naukri. Preapproved action: PREPARATION only. Maximum
          employer submissions per day: 0. All required skills must match
          verified facts; uncertain vacancies and answers require review. Saving
          stops existing work and pins the current profile and resume. Telegram
          delivery remains separately configured.
        </p>
        <Button disabled={busy || !version || !resume}>
          Save bounded preparation policy
        </Button>
      </form>
      {Boolean(data.alert_candidates?.length) && (
        <div className="stack">
          <h3>Job-alert candidates requiring input</h3>
          <p>
            Email links identify a requisition, not an active or verified
            vacancy. Review sender authenticity, employer, title, required
            skills, experience and current availability before preparation.
          </p>
          {data.alert_candidates?.map((alert) => (
            <article key={alert.id}>
              <p>
                {alert.requisition_id} · {readable(alert.state)} ·{" "}
                {readable(alert.reason)}
              </p>
              <p>{alert.url}</p>
              {alert.state === "NEEDS_INPUT" && (
                <Button
                  disabled={busy}
                  onClick={() => reviewAlert?.(alert.id, alert.url)}
                >
                  Review alert facts
                </Button>
              )}
            </article>
          ))}
        </div>
      )}
      <details>
        <summary>Recorded decisions and source observations</summary>
        {data.decisions.map((d) => (
          <article key={d.id}>
            <p>
              {d.title} — {readable(d.reason)}
            </p>
            <p>
              Source: {readable(d.source)} · Observed:{" "}
              {when(d.last_observation)} · Evaluated: {when(d.evaluated_at)}
            </p>
          </article>
        ))}
      </details>
    </section>
  );
}
