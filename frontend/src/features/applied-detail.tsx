"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { ApiError, api, readable } from "@/lib/api";
import {
  Badge,
  Empty,
  ErrorState,
  External,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { stateTone } from "@/features/autopilot-forms";
import {
  APPLIED_REFRESH_MS,
  answerSourceLabel,
  istStamp,
  portalName,
  relativeTime,
  type AppliedDetail as Detail,
} from "@/features/applied-model";

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function AppliedDetail({ id }: { id: string }) {
  const detail = useQuery({
    queryKey: ["v2-applied-detail", id],
    queryFn: () => api<Detail>(`v2/applications/${id}`),
    refetchInterval: APPLIED_REFRESH_MS,
  });
  const back = (
    <Link className="external" href="/applied">
      <ArrowLeft size={13} />
      Back to applied
    </Link>
  );
  if (detail.isPending)
    return (
      <>
        {back}
        <div className="spaced">
          <Skeleton />
        </div>
      </>
    );
  if (detail.isError)
    return (
      <>
        {back}
        <div className="spaced">
          {detail.error instanceof ApiError && detail.error.status === 404 ? (
            <Empty
              title="Application not found"
              description="It may have been removed, or the link is incomplete."
            />
          ) : (
            <ErrorState error={detail.error} retry={() => detail.refetch()} />
          )}
        </div>
      </>
    );
  const d = detail.data;
  const r = d.receipt;
  const answers = r.answers ?? [];
  const timeline = [...(d.timeline ?? [])].reverse();
  return (
    <>
      {back}
      <div className="spaced">
        <PageTitle
          eyebrow={`${portalName(d.platform).toUpperCase()} · ${d.external_job_id}`}
          title={d.role_title || "Untitled role"}
          description={d.company_name || "Unknown company"}
          actions={
            <div className="tag-list">
              <Badge tone={stateTone(d.state)}>{readable(d.state)}</Badge>
              {r.verified ? (
                <Badge tone="green">Verified receipt</Badge>
              ) : d.state === "APPLIED" ? (
                <Badge tone="amber">No receipt source</Badge>
              ) : null}
            </div>
          }
        />
      </div>
      <div className="detail-grid">
        <section className="panel" aria-labelledby="answers-h">
          <div className="panel-header">
            <div>
              <h2 id="answers-h">Screening answers</h2>
              <p>
                {answers.length
                  ? `${answers.length} field${answers.length === 1 ? "" : "s"} filled${r.answers_source === "event" ? " during the last attempt" : " on the submitted form"}`
                  : "What the worker typed or picked on the form"}
              </p>
            </div>
          </div>
          <div className="panel-body">
            {answers.length === 0 ? (
              <p className="muted">
                No screening questions were recorded for this application
                (one-click apply, or the portal asked nothing).
              </p>
            ) : (
              <ol className="answer-list">
                {answers.map((a, i) => (
                  <li key={`${i}-${a.question}`}>
                    <p className="answer-q">{a.question}</p>
                    <p className="answer-a">{a.answer || "—"}</p>
                    {a.source && <Badge>{answerSourceLabel(a.source)}</Badge>}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
        <div className="applied-side">
          <section className="panel" aria-labelledby="submission-h">
            <div className="panel-header">
              <div>
                <h2 id="submission-h">Submission</h2>
                <p>From the stored receipt (no files or paths are exposed)</p>
              </div>
            </div>
            <div className="panel-body">
              <dl className="worker-facts">
                <Fact label="Applied">
                  {d.applied_at ? (
                    <>
                      {relativeTime(d.applied_at)}
                      <small className="muted block">
                        {istStamp(d.applied_at)}
                      </small>
                    </>
                  ) : (
                    "Not applied"
                  )}
                </Fact>
                <Fact label="Verified by">
                  {r.source ? readable(r.source) : "—"}
                </Fact>
                {r.ats && <Fact label="ATS">{readable(r.ats)}</Fact>}
                {r.portal_status && (
                  <Fact label="Portal status">{r.portal_status}</Fact>
                )}
                <Fact label="Apply clicked">
                  {r.clicked_apply === undefined || r.clicked_apply === null
                    ? "—"
                    : r.clicked_apply
                      ? "Yes"
                      : "No"}
                </Fact>
                <Fact label="Screenshot">
                  {r.has_screenshot ? "Saved on this Mac" : "None"}
                </Fact>
                {r.resume && <Fact label="Resume">{r.resume}</Fact>}
                <Fact label="Attempts">{d.attempts}</Fact>
                {d.reason && d.state !== "APPLIED" && (
                  <Fact label="Reason">{readable(d.reason)}</Fact>
                )}
              </dl>
              <div className="tag-list spaced">
                {d.job_url && <External href={d.job_url}>Job posting</External>}
                {r.confirmation_url && r.confirmation_url !== d.job_url && (
                  <External href={r.confirmation_url}>
                    Confirmation page
                  </External>
                )}
                {r.external_url && (
                  <External href={r.external_url}>Company application</External>
                )}
              </div>
            </div>
          </section>
          <section className="panel" aria-labelledby="timeline-h">
            <div className="panel-header">
              <div>
                <h2 id="timeline-h">State history</h2>
                <p>Newest first</p>
              </div>
            </div>
            <div className="panel-body">
              {timeline.length === 0 ? (
                <p className="muted">No state transitions recorded.</p>
              ) : (
                <ol className="timeline" aria-label="State history">
                  {timeline.map((e, i) => (
                    <li key={`${e.created_at}-${i}`}>
                      <strong>
                        {e.from_state ? `${readable(e.from_state)} → ` : ""}
                        {readable(e.to_state)}
                      </strong>{" "}
                      <span className="muted">· {readable(e.event_type)}</span>
                      <time dateTime={e.created_at ?? undefined}>
                        {istStamp(e.created_at)}
                      </time>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
