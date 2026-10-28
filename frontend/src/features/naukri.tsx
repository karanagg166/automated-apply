"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable } from "@/lib/api";
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
type Job = { id: string; title: string; job_url: string };
type Question = {
  id: string;
  execution_id: string;
  employer: string;
  role: string;
  question: string;
  state: string;
  answer: string | null;
  answer_type?: "availability" | "choice" | "text" | string;
  options?: string[];
  factual_context?: string;
  reuse_approved: boolean;
  answer_expires_at: string | null;
};
type Status = {
  configuration: Configuration;
  executions: Execution[];
  capabilities: Record<string, unknown>;
};

export function Naukri() {
  const client = useQueryClient();
  const [url, setUrl] = useState(""),
    [title, setTitle] = useState(""),
    [employer, setEmployer] = useState("");
  const [skills, setSkills] = useState(""),
    [minimum, setMinimum] = useState(""),
    [maximum, setMaximum] = useState("");
  const [requirement, setRequirement] = useState("unknown");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const [dashboardAnswers, setDashboardAnswers] = useState<
    Record<string, string>
  >({});
  const [availDates, setAvailDates] = useState<Record<string, string>>({});
  const [availTimes, setAvailTimes] = useState<Record<string, string>>({});
  const [availZones, setAvailZones] = useState<Record<string, string>>({});
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
          Account access and live Naukri forms have not been verified. Import a
          posting from your normal Naukri session or job alert. Preparation uses
          your saved candidate profile. Submission remains manual.
        </Notice>
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
                },
              ],
            }),
          );
        }}
      >
        <h2>Import job URL</h2>
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
            <a href={job.job_url} target="_blank" rel="noreferrer">
              {job.title}
            </a>
            <Button
              disabled={busy || status.data.configuration.mode === "OFF"}
              onClick={() =>
                act(() => post("execution/naukri/apply", { job_ids: [job.id] }))
              }
            >
              Prepare selected job
            </Button>
          </div>
        ))}
        {jobs.data?.jobs.length === 0 && <p>No imported jobs yet.</p>}
      </div>
      <div className="panel panel-body stack">
        <h2>Application status</h2>
        {status.data.executions.map((execution) => {
          const canResume = ["PAUSED", "NEEDS_INPUT"].includes(execution.state);
          return (
            <article key={execution.id} className="stack">
              <div className="split">
                <p>
                  <strong>{execution.employer || "Employer unknown"}</strong> —{" "}
                  {execution.role}
                </p>
                <Badge
                  tone={execution.state === "NEEDS_INPUT" ? "amber" : "neutral"}
                >
                  {readable(execution.state)}
                </Badge>
              </div>
              <p>Reference: {execution.id}</p>
              {execution.diagnostic && (
                <Notice>
                  <strong>Status diagnostic:</strong>{" "}
                  {readable(execution.diagnostic)}
                </Notice>
              )}
              {execution.packet_id && (
                <Link
                  href={"/applications/" + execution.packet_id}
                  className="button secondary"
                >
                  Review application and browser assistance
                </Link>
              )}
              <div className="actions">
                {canResume && (
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() =>
                      act(() =>
                        post("execution/" + execution.id + "/control", {
                          action: "resume",
                          expected_revision: execution.revision,
                        }),
                      )
                    }
                  >
                    Resume Application
                  </Button>
                )}
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
          );
        })}
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
          const isAvail = q.answer_type === "availability";
          const currentAnswer = dashboardAnswers[q.id] || "";
          const availDate = availDates[q.id] || "";
          const availTime = availTimes[q.id] || "10:00";
          const availZone = availZones[q.id] || "Asia/Kolkata";

          return (
            <article className="stack" key={q.id}>
              <div className="split">
                <p>
                  <strong>{q.employer}</strong> — {q.role}: {q.question}
                </p>
                {isPending ? (
                  <Badge tone="amber">Waiting for Your Answer</Badge>
                ) : (
                  <Badge tone="green">{readable(q.state)}</Badge>
                )}
              </div>
              <p>Application: {q.execution_id}</p>
              {q.answer && <p>Saved answer: {q.factual_context || q.answer}</p>}
              {q.answer_expires_at && (
                <p>
                  Reconfirm by: {new Date(q.answer_expires_at).toLocaleString()}
                </p>
              )}
              {isPending && (
                <div
                  className="panel panel-body stack spaced"
                  style={{
                    background: "var(--surface-sunken, rgba(0,0,0,0.02))",
                  }}
                >
                  <p>
                    <strong>Answer from Dashboard:</strong>
                  </p>
                  {isAvail ? (
                    <div className="filter-grid">
                      <Field label="Interview date">
                        <Input
                          type="date"
                          value={availDate}
                          onChange={(e) =>
                            setAvailDates((prev) => ({
                              ...prev,
                              [q.id]: e.target.value,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Interview time">
                        <Input
                          type="time"
                          value={availTime}
                          onChange={(e) =>
                            setAvailTimes((prev) => ({
                              ...prev,
                              [q.id]: e.target.value,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Time zone (IANA)">
                        <Select
                          value={availZone}
                          onChange={(e) =>
                            setAvailZones((prev) => ({
                              ...prev,
                              [q.id]: e.target.value,
                            }))
                          }
                        >
                          <option value="Asia/Kolkata">
                            Asia/Kolkata (IST)
                          </option>
                          <option value="UTC">UTC</option>
                          <option value="America/New_York">
                            America/New_York (EST)
                          </option>
                          <option value="America/Los_Angeles">
                            America/Los_Angeles (PST)
                          </option>
                          <option value="Europe/London">
                            Europe/London (GMT)
                          </option>
                        </Select>
                      </Field>
                    </div>
                  ) : q.options && q.options.length > 0 ? (
                    <Field label="Select option">
                      <Select
                        value={currentAnswer}
                        onChange={(e) =>
                          setDashboardAnswers((prev) => ({
                            ...prev,
                            [q.id]: e.target.value,
                          }))
                        }
                      >
                        <option value="">Choose an option…</option>
                        {q.options.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  ) : (
                    <Field label="Your verified answer">
                      <Input
                        value={currentAnswer}
                        placeholder="Enter your factual answer…"
                        onChange={(e) =>
                          setDashboardAnswers((prev) => ({
                            ...prev,
                            [q.id]: e.target.value,
                          }))
                        }
                      />
                    </Field>
                  )}
                  <div className="actions">
                    <Button
                      variant="primary"
                      disabled={
                        busy ||
                        (isAvail
                          ? !availDate || !availTime
                          : !currentAnswer.trim())
                      }
                      onClick={() => {
                        let finalAns = currentAnswer.trim();
                        if (isAvail) {
                          finalAns = `${availDate}T${availTime} ${availZone}`;
                          if (q.options && q.options.length > 0) {
                            finalAns = `${q.options[0]} | ${finalAns}`;
                          }
                        }
                        act(() =>
                          post("execution/questions/" + q.id + "/answer", {
                            answer: finalAns,
                          }),
                        );
                      }}
                    >
                      Submit Answer from Dashboard
                    </Button>
                  </div>
                </div>
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
