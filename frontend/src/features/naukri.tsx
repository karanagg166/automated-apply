"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExecutionQuestionAnswer,
  type ExecutionQuestion,
} from "@/features/execution-question-answer";
import { api, post, readable } from "@/lib/api";
import {
  NaukriAutomation,
  type NaukriAutomationStatus,
} from "@/features/naukri-automation";
import { ApplicationQueue } from "@/features/application-queue";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  Select,
  Skeleton,
} from "@/components/ui";

type Configuration = {
  mode: string;
  interval_seconds: number;
  source: string;
  destinations: string[];
  submission_permission: boolean;
};
type Execution = {
  role: string;
  employer: string | null;
  id: string;
  job_id: string;
  packet_id: string | null;
  state: string;
  revision: number;
  diagnostic: string | null;
};
type Job = {
  id: string;
  title: string;
  job_url: string;
  employer?: string | null;
  vacancy_review?: string;
  state?: string;
  reason?: string;
  profile_version?: number | null;
  match?: {
    match_score: number;
    matched_skills: string[];
    missing_skills: string[];
    explanation: string;
    unknown_fields: string[];
    negative_factors: string[];
  } | null;
};
type Question = ExecutionQuestion & {
  factual_context?: string;
  reuse_approved: boolean;
};
type Status = {
  automation?: NaukriAutomationStatus;
  configuration: Configuration;
  executions: Execution[];
  capabilities: Record<string, unknown>;
  account_session?: {
    state: string;
    last_verification_time: string | null;
    evidence_type: string;
  };
};

export function Naukri() {
  const client = useQueryClient();
  const [url, setUrl] = useState(""),
    [title, setTitle] = useState(""),
    [employer, setEmployer] = useState("");
  const [alertId, setAlertId] = useState<string | null>(null);
  const [skills, setSkills] = useState(""),
    [minimum, setMinimum] = useState(""),
    [maximum, setMaximum] = useState("");
  const [requirement, setRequirement] = useState("unknown");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [applicationUrl, setApplicationUrl] = useState("");
  const [postingStatus, setPostingStatus] = useState("unknown");
  const [validThrough, setValidThrough] = useState("");
  const [postedAt, setPostedAt] = useState("");
  const [remoteType, setRemoteType] = useState("unknown");
  const [employmentType, setEmploymentType] = useState("");
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const status = useQuery({
    queryKey: ["naukri"],
    queryFn: () => api<Status>("execution/naukri"),
    refetchInterval: 10000,
  });
  const jobs = useQuery({
    queryKey: ["naukri-jobs"],
    queryFn: () => api<{ jobs: Job[] }>("execution/naukri/jobs"),
  });
  const questions = useQuery({
    queryKey: ["naukri-questions"],
    queryFn: () => api<Question[]>("execution/questions"),
    refetchInterval: 10000,
  });
  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      await Promise.all([
        client.invalidateQueries({ queryKey: ["naukri"] }),
        client.invalidateQueries({ queryKey: ["naukri-jobs"] }),
        client.invalidateQueries({ queryKey: ["naukri-questions"] }),
      ]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (status.isPending) return <Skeleton />;
  if (status.isError) return <ErrorState error={status.error} />;
  return (
    <section className="stack" aria-label="Naukri preparation">
      <div className="panel panel-body stack">
        <h1>Naukri</h1>
        <Notice>
          {status.data.account_session?.state === "browser_session_observed"
            ? "A local browser sign-in indicator was observed. This does not verify account identity or a Naukri API connection. "
            : "Account access and live Naukri forms have not been verified. "}
          Import a posting from your normal Naukri session or job alert.
          Preparation uses your saved candidate profile. Submission remains
          manual.
        </Notice>
        {status.data.account_session?.last_verification_time && (
          <p>
            Session last observed:{" "}
            {new Date(
              status.data.account_session.last_verification_time,
            ).toLocaleString()}
            . This is a past observation; confirm your current Naukri tab before
            proceeding.
          </p>
        )}
        <Field label="Automation mode">
          <Select
            aria-label="Automation mode"
            disabled={busy}
            value={status.data.configuration.mode}
            onChange={(e) =>
              act(() =>
                api("execution/naukri", {
                  method: "PUT",
                  body: JSON.stringify({
                    ...status.data.configuration,
                    mode: e.target.value,
                  }),
                }),
              )
            }
          >
            <option value="OFF">Off</option>
            <option value="ON_DEMAND">On demand</option>
            <option value="WATCH_AND_NOTIFY">
              Watch saved imports and notify
            </option>
          </Select>
        </Field>
        <p>
          Watching checks saved imports only. It needs an awake local worker or
          a separately approved always-on worker. Automated Naukri submission is
          unavailable.
        </p>
        {error ? <ErrorState error={error} /> : null}
      </div>
      <ApplicationQueue />
      {status.data.automation && (
        <NaukriAutomation
          data={status.data.automation}
          busy={busy}
          act={act}
          reviewAlert={(id, alertUrl) => {
            setAlertId(id);
            setUrl(alertUrl);
            setTitle("");
            setEmployer("");
            setSkills("");
            setDescription("");
            setApplicationUrl("");
            setMinimum("");
            setMaximum("");
            setRequirement("unknown");
            setLocation("");
            setPostingStatus("unknown");
            setValidThrough("");
            setPostedAt("");
            setRemoteType("unknown");
            setEmploymentType("");
          }}
        />
      )}
      <form
        className="panel panel-body stack"
        onSubmit={(e) => {
          e.preventDefault();
          act(() =>
            post("execution/naukri/import", {
              jobs: [
                {
                  url,
                  title,
                  employer,
                  ...(alertId ? { alert_candidate_id: alertId } : {}),
                  ...(skills
                    ? {
                        required_skills: skills
                          .split(",")
                          .map((x) => x.trim())
                          .filter(Boolean),
                      }
                    : {}),
                  ...(minimum ? { experience_min: Number(minimum) } : {}),
                  ...(maximum ? { experience_max: Number(maximum) } : {}),
                  ...(requirement !== "unknown"
                    ? { experience_requirement: requirement }
                    : {}),
                  ...(location ? { location } : {}),
                  ...(description ? { description } : {}),
                  ...(applicationUrl
                    ? { application_url: applicationUrl }
                    : {}),
                  ...(postingStatus !== "unknown"
                    ? {
                        posting_status: postingStatus,
                        observed_at: new Date().toISOString(),
                      }
                    : {}),
                  ...(validThrough ? { valid_through: validThrough } : {}),
                  ...(postedAt ? { posted_at: `${postedAt}T00:00:00Z` } : {}),
                  ...(remoteType !== "unknown"
                    ? { remote_type: remoteType }
                    : {}),
                  ...(employmentType
                    ? { employment_type: employmentType }
                    : {}),
                },
              ],
            }),
          );
        }}
      >
        <h2>Import job URL</h2>
        {alertId && (
          <Notice>
            Reviewing alert {alertId}. Supply verified posting facts; the email
            alone does not establish current availability.
          </Notice>
        )}
        <Field label="Naukri posting URL">
          <Input
            aria-label="Naukri posting URL"
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </Field>
        <Field label="Role from the posting">
          <Input
            aria-label="Role from the posting"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label="Employer from the posting">
          <Input
            aria-label="Employer from the posting"
            required
            value={employer}
            onChange={(e) => setEmployer(e.target.value)}
          />
        </Field>
        <details>
          <summary>Listing criteria for matching</summary>
          <div className="stack">
            <Field label="Description copied from the reviewed posting">
              <textarea
                className="input"
                value={description}
                maxLength={30000}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            <Field label="Reviewed external employer application URL (optional)">
              <Input
                type="url"
                value={applicationUrl}
                onChange={(e) => setApplicationUrl(e.target.value)}
              />
            </Field>
            <Field label="Status you just observed on Naukri">
              <Select
                value={postingStatus}
                onChange={(e) => setPostingStatus(e.target.value)}
              >
                <option value="unknown">Not checked / unknown</option>
                <option value="active">Active posting observed</option>
                <option value="closed">
                  Closed / expired posting observed
                </option>
                <option value="already_applied">
                  Already applied indicator observed
                </option>
              </Select>
            </Field>
            <Field label="Posting expiry date, if shown">
              <Input
                type="date"
                value={validThrough}
                onChange={(e) => setValidThrough(e.target.value)}
              />
            </Field>
            <Field label="Posting publication date, if known">
              <Input
                type="date"
                value={postedAt}
                onChange={(e) => setPostedAt(e.target.value)}
              />
            </Field>
            <Field label="Advertised work mode">
              <Select
                value={remoteType}
                onChange={(e) => setRemoteType(e.target.value)}
              >
                <option value="unknown">Unknown</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">On site</option>
              </Select>
            </Field>
            <Field label="Advertised employment type">
              <Select
                value={employmentType}
                onChange={(e) => setEmploymentType(e.target.value)}
              >
                <option value="">Unknown</option>
                <option value="full_time">Full time</option>
                <option value="part_time">Part time</option>
                <option value="contract">Contract</option>
                <option value="internship">Internship</option>
              </Select>
            </Field>
            <p>
              These are your observations, not provider verification. Active
              evidence becomes stale after 24 hours.
            </p>
            <Field label="Required technical skills">
              <Input
                aria-label="Required technical skills"
                value={skills}
                onChange={(e) => setSkills(e.target.value)}
                placeholder="Comma-separated skills from the posting"
              />
            </Field>
            <Field label="Minimum experience years">
              <Input
                aria-label="Minimum experience years"
                type="number"
                min="0"
                max="60"
                step="0.5"
                value={minimum}
                onChange={(e) => setMinimum(e.target.value)}
              />
            </Field>
            <Field label="Maximum experience years">
              <Input
                aria-label="Maximum experience years"
                type="number"
                min="0"
                max="60"
                step="0.5"
                value={maximum}
                onChange={(e) => setMaximum(e.target.value)}
              />
            </Field>
            <Field label="Experience requirement">
              <Select
                aria-label="Experience requirement"
                value={requirement}
                onChange={(e) => setRequirement(e.target.value)}
              >
                <option value="unknown">Unknown</option>
                <option value="required">Required by posting</option>
                <option value="preferred">Preferred by posting</option>
              </Select>
            </Field>
            <Field label="Job location">
              <Input
                aria-label="Job location"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </Field>
          </div>
        </details>
        <p>
          Owner-supplied facts remain unverified. Unknown skills or experience
          pause preparation for review. Re-import updated listing criteria, then
          Resume to check them again.
        </p>
        <Button disabled={busy}>Import posting</Button>
      </form>
      <div className="panel panel-body stack">
        <h2>Find jobs</h2>
        <Button disabled={busy} onClick={() => act(() => jobs.refetch())}>
          Find saved Naukri jobs
        </Button>
        {jobs.isError ? <ErrorState error={jobs.error} /> : null}
        {jobs.data?.jobs.map((job) => (
          <div key={job.id} className="stack">
            <External href={job.job_url}>{job.title}</External>
            {job.vacancy_review && (
              <p>
                Vacancy: {readable(job.vacancy_review)} · {readable(job.state)}{" "}
                — {readable(job.reason)}
              </p>
            )}
            {job.match && (
              <div>
                <p>
                  Profile v{job.profile_version} · Match:{" "}
                  {job.match.match_score}/100
                </p>
                <p>{job.match.explanation}</p>
                <p>
                  Matched skills:{" "}
                  {job.match.matched_skills.join(", ") || "None verified"}
                </p>
                <p>
                  Missing skills:{" "}
                  {job.match.missing_skills.join(", ") || "None identified"}
                </p>
                <p>
                  Unknown:{" "}
                  {job.match.unknown_fields.join(", ") || "None identified"}
                </p>
                {job.match.negative_factors.map((reason) => (
                  <p key={reason}>{reason}</p>
                ))}
              </div>
            )}
            <Button
              disabled={
                busy ||
                status.data.configuration.mode === "OFF" ||
                job.state === "REJECTED"
              }
              onClick={() =>
                act(() => post("execution/naukri/apply", { job_ids: [job.id] }))
              }
            >
              Prepare selected job
            </Button>
          </div>
        ))}
        {jobs.data?.jobs.length === 0 && <p>No imported jobs yet.</p>}
        <p>
          This reads saved imports only. A match score cannot establish that a
          vacancy is active or authorize filling. Preparation queues a review
          draft; it does not start a worker or send Telegram questions.
        </p>
      </div>
      <div className="panel panel-body stack">
        <h2>Application status</h2>
        {status.data.executions.map((execution) => (
          <article key={execution.id} className="stack">
            <p>
              {execution.employer || "Employer unknown"} — {execution.role}
            </p>
            <Badge>{readable(execution.state)}</Badge>
            <p>Reference: {execution.id}</p>
            {execution.diagnostic && <p>{readable(execution.diagnostic)}</p>}
            {execution.packet_id && (
              <Link href={"/applications/" + execution.packet_id}>
                Review application and browser assistance
              </Link>
            )}
            <div className="actions">
              {(["pause", "resume", "cancel"] as const).map((action) => (
                <Button
                  key={action}
                  disabled={
                    busy ||
                    [
                      "FAILED_FINAL",
                      "REJECTED",
                      "SUBMITTED_CONFIRMED",
                      "SUBMISSION_UNKNOWN",
                    ].includes(execution.state) ||
                    (action === "resume" &&
                      !["PAUSED", "NEEDS_INPUT"].includes(execution.state))
                  }
                  onClick={() =>
                    act(() =>
                      post("execution/" + execution.id + "/control", {
                        action,
                        expected_revision: execution.revision,
                      }),
                    )
                  }
                >
                  {readable(action)}
                </Button>
              ))}
            </div>
          </article>
        ))}
        {status.data.executions.length === 0 && <p>No execution requested.</p>}
      </div>
      <div className="panel panel-body stack">
        <h2>Telegram questions</h2>
        <p>
          Reply to the exact bot question message or answer directly below.
          Dates need a time and time zone (for example Asia/Kolkata). Answers
          expire and require review before filling.
        </p>
        {questions.isError ? <ErrorState error={questions.error} /> : null}
        {questions.data?.map((q) => {
          const isPending = q.state === "pending" || q.state === "sent";
          return (
            <article className="stack" key={q.id}>
              <div className="split">
                <p>
                  <strong>{q.employer}</strong> — {q.role}: {q.question}
                </p>
                {isPending ? (
                  <Badge tone="amber">Waiting for Your Answer</Badge>
                ) : (
                  <Badge tone={q.state === "answered" ? "green" : "amber"}>
                    {readable(q.state)}
                  </Badge>
                )}
              </div>
              <p>Application: {q.execution_id}</p>
              {q.state === "delivery_unknown" && (
                <Notice>
                  Telegram delivery outcome is unknown. Check your private chat;
                  this prompt will not be automatically resent.
                </Notice>
              )}
              {q.answer && <p>Saved answer: {q.factual_context || q.answer}</p>}
              {q.answer_expires_at && (
                <p>
                  Reconfirm by: {new Date(q.answer_expires_at).toLocaleString()}
                </p>
              )}
              {isPending && (
                <ExecutionQuestionAnswer
                  key={`${q.id}:${q.packet_revision}`}
                  question={q}
                  onSaved={() => {
                    void act(async () => {});
                  }}
                />
              )}
              {q.state === "answered" && (
                <Button
                  disabled={busy || q.reuse_approved}
                  onClick={() =>
                    act(() =>
                      post("execution/questions/" + q.id + "/approve-reuse"),
                    )
                  }
                >
                  {q.reuse_approved
                    ? "Reuse approved for compatible context"
                    : "Approve reuse for this exact context"}
                </Button>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
