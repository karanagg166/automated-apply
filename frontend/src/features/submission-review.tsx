"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "@/lib/api";
import { Button, ErrorState, Notice } from "@/components/ui";

type Submission = {
  application_id: string;
  job_id: string;
  employer: string;
  job_title: string;
  application_url: string;
  request_url: string;
  origin: string;
  state: string;
  candidate_version: number;
  packet_revision: number;
  project_digest: string;
  pdf_digest: string;
  document_digest: string;
  review_digest: string;
  expires_at: string;
  nonce: string;
  campaign_revision: number;
  authorization: unknown;
  released: boolean;
  reason: string | null;
  evidence: {
    type: string;
    application_id: string;
    destination: string;
    timestamp: string;
    correlation_id: string;
  } | null;
};
const labels: Record<string, string> = {
  prepared: "Prepared",
  form_inspected: "Form inspected",
  form_filled: "Form filled",
  awaiting_submission_approval: "Awaiting approval",
  submitting: "Submitting",
  submitted: "Submitted with evidence",
  submission_uncertain: "Submission uncertain",
  manual_required: "Manual action required",
  failed: "Failed",
};
export function SubmissionReview({
  historyOnly = false,
}: {
  historyOnly?: boolean;
}) {
  const client = useQueryClient();
  const [reviewed, setReviewed] = useState<Record<string, string>>({});
  const items = useQuery({
    queryKey: ["submission-review"],
    queryFn: () => api<Submission[]>("browser/submissions"),
    refetchInterval: 3000,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["submission-review"] });
    client.invalidateQueries({ queryKey: ["agent-campaigns"] });
  };
  const approve = useMutation({
    mutationFn: (s: Submission) =>
      post(`browser/submissions/${s.application_id}/approve`, {
        nonce: s.nonce,
        review_digest: s.review_digest,
        campaign_revision: s.campaign_revision,
        application_ids: [s.application_id],
        maximum_count: 1,
        scope: "submit_application",
      }),
    onSuccess: refresh,
  });
  const execute = useMutation({
    mutationFn: (s: Submission) =>
      post(`browser/submissions/${s.application_id}/execute`),
    onSuccess: refresh,
  });
  const reconcile = useMutation({
    mutationFn: (s: Submission) =>
      post(`browser/submissions/${s.application_id}/reconcile`),
    onSuccess: refresh,
  });
  const stop = useMutation({
    mutationFn: () => post("browser/submissions/stop"),
    onSuccess: refresh,
  });
  return (
    <section className="stack" aria-labelledby="submission-review-title">
      <h2 id="submission-review-title">
        {historyOnly ? "Saved submission history" : "Submission review"}
      </h2>
      {!historyOnly && (
        <>
          <Notice>
            Submission requires your review and exact approval for each
            application. This release supports controlled localhost fixtures
            only. Real employer submission is unavailable. An uncertain result
            requires receipt verification before any further action.
          </Notice>
          <Button onClick={() => stop.mutate()} disabled={stop.isPending}>
            Stop the remaining submissions
          </Button>
        </>
      )}
      {[items, approve, execute, reconcile, stop].map(
        (r, i) => r.isError && <ErrorState key={i} error={r.error} />,
      )}
      {(Array.isArray(items.data) ? items.data : []).map((s) => (
        <article className="panel stack" key={s.application_id}>
          <h3>
            {s.employer} — {s.job_title}
          </h3>
          <p role="status">
            {s.state === "submitted" && !s.evidence
              ? "Saved as submitted · receipt unavailable"
              : labels[s.state] || s.state}
          </p>
          <p>Selected application: {s.application_id}</p>
          <p>Job: {s.job_id}</p>
          <p>Destination: {s.origin}</p>
          <p>Application URL: {s.application_url}</p>
          <p>Final request: {s.request_url}</p>
          <p>
            Profile version {s.candidate_version}; packet revision{" "}
            {s.packet_revision}. Maximum submissions: 1.
          </p>
          <details>
            <summary>Reviewed document and versions</summary>
            <p>Canonical PDF: {s.pdf_digest}</p>
            <p>Project context: {s.project_digest}</p>
            <p>Filled document: {s.document_digest}</p>
          </details>
          <p>Approval expires {new Date(s.expires_at).toLocaleString()}</p>
          {!historyOnly &&
            s.state === "awaiting_submission_approval" &&
            !s.authorization && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={reviewed[s.application_id] === s.review_digest}
                    onChange={(e) =>
                      setReviewed({
                        ...reviewed,
                        [s.application_id]: e.target.checked
                          ? s.review_digest
                          : "",
                      })
                    }
                  />{" "}
                  I reviewed the filled values, narratives, resume, employer and
                  exact destination for application {s.application_id}.
                </label>
                <Button
                  disabled={
                    approve.isPending ||
                    reviewed[s.application_id] !== s.review_digest ||
                    Date.parse(s.expires_at) <= Date.now()
                  }
                  onClick={() => approve.mutate(s)}
                >
                  Authorize this one application
                </Button>
              </>
            )}
          {!historyOnly &&
            s.state === "awaiting_submission_approval" &&
            !!s.authorization && (
              <Button
                disabled={
                  execute.isPending ||
                  s.released ||
                  Date.parse(s.expires_at) <= Date.now()
                }
                onClick={() => execute.mutate(s)}
              >
                {s.released
                  ? "Waiting for browser worker"
                  : "Submit this approved application"}
              </Button>
            )}
          {s.state === "submission_uncertain" && (
            <>
              <Notice>
                Do not submit again. The employer may already have received this
                application. Check read-only evidence or verify manually.
              </Notice>
              {!historyOnly && (
                <Button
                  disabled={reconcile.isPending}
                  onClick={() => reconcile.mutate(s)}
                >
                  Check receipt without resubmitting
                </Button>
              )}
            </>
          )}
          {s.evidence && (
            <p>
              Evidence: {s.evidence.type}; receipt {s.evidence.application_id};{" "}
              {s.evidence.destination}; {s.evidence.timestamp}; correlation{" "}
              {s.evidence.correlation_id}.
            </p>
          )}
          {s.reason && <p>{s.reason.replaceAll("_", " ")}</p>}
        </article>
      ))}
    </section>
  );
}
