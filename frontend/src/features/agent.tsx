"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  Skeleton,
} from "@/components/ui";

import { BrowserPlans } from "./browser-plans";
import { SubmissionReview } from "./submission-review";

type Campaign = Schema<"Campaign">;
type Status = {
  worker_ready: boolean;
  native_worker_online?: boolean;
  native_worker_mode?: string;
  browser_worker_ready?: boolean;
  state: string;
  local_requests_remaining: number | null;
  owner_text_authorized: boolean;
  candidate_data_authorized: boolean;
};
const terminal = ["completed", "partially_completed", "failed", "cancelled"];

export function Agent({ nativeRuntime = false }: { nativeRuntime?: boolean }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const request = useRef<{ text: string; request_id: string } | null>(null);
  const history = useQuery({
    queryKey: ["agent-campaigns"],
    queryFn: () => api<Campaign[]>("agent/campaigns"),
    refetchInterval: 3000,
  });
  const status = useQuery({
    queryKey: ["agent-status"],
    queryFn: () => api<Status>("agent/status"),
    refetchInterval: 15000,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["agent-campaigns"] });
    client.invalidateQueries({ queryKey: ["agent-status"] });
  };
  const send = useMutation({
    mutationFn: () => {
      // Preserve intake identity across a lost response. A new text creates a new command.
      if (!request.current || request.current.text !== text)
        request.current = { text, request_id: crypto.randomUUID() };
      return post<Campaign>("agent/commands", request.current);
    },
    onSuccess: () => {
      setText("");
      request.current = null;
      refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: (id: string) => post(`agent/campaigns/${id}/cancel`),
    onSuccess: refresh,
  });
  const approve = useMutation({
    mutationFn: (campaign: Campaign) =>
      post(`agent/campaigns/${campaign.id}/approve`, {
        expected_revision: campaign.revision,
        nonce: campaign.approval_nonce,
        scope: "prepare",
        platforms: [
          "employer_forms",
          "google_forms",
          "naukri",
          "wellfound",
          "instahyre",
          "work_at_a_startup",
          "internshala",
        ],
        maximum_applications: campaign.plan.selected_jobs?.length || 1,
      }),
    onSuccess: refresh,
  });
  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <h1>Agent</h1>
          {nativeRuntime ? (
            <Link className="button primary" href="/workflow">
              Open agent workflow
            </Link>
          ) : (
            <p>
              Find jobs and prepare application drafts through the same
              workspace as Telegram.
            </p>
          )}
        </div>
      </div>
      <BrowserPlans />
      <SubmissionReview historyOnly={nativeRuntime} />
      {!nativeRuntime && (
        <Notice>
          Fixture submissions require exact approval in Submission review.
        </Notice>
      )}
      <section
        className="panel panel-body stack"
        aria-label="Agent availability"
      >
        {nativeRuntime ? (
          <Badge tone={status.data?.native_worker_online ? "green" : "amber"}>
            {status.data?.native_worker_online
              ? `Workflow worker online · ${status.data.native_worker_mode?.toLowerCase() || "mode unknown"}`
              : "Workflow worker unavailable"}
          </Badge>
        ) : (
          <Badge tone={status.data?.worker_ready ? "green" : "amber"}>
            {status.data?.worker_ready
              ? "Command worker available"
              : "Pending · command worker unavailable"}
          </Badge>
        )}
        <Badge tone={status.data?.browser_worker_ready ? "green" : "amber"}>
          {status.data?.browser_worker_ready
            ? nativeRuntime
              ? "Connected browser worker available"
              : "Chrome worker available"
            : nativeRuntime
              ? "Connected browser worker unavailable"
              : "Chrome worker unavailable"}
        </Badge>
        <p>
          Cohere: {readable(status.data?.state)}.{" "}
          {typeof status.data?.local_requests_remaining === "number"
            ? `${status.data.local_requests_remaining} local requests remaining.`
            : status.data
              ? "Local request limit unavailable."
              : "Checking local limits…"}{" "}
          Provider account quota is unverified.
        </p>
        <p>
          Cloud command consent:{" "}
          {status.data?.owner_text_authorized ? "enabled" : "off"}. Candidate
          data consent:{" "}
          {status.data?.candidate_data_authorized ? "enabled" : "off"}.
        </p>
        {status.error && <ErrorState error={status.error} />}
      </section>
      {!nativeRuntime && (
        <form
          className="panel panel-body stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (text.trim()) send.mutate();
          }}
        >
          <Field
            label="Command"
            hint="Try: Find backend jobs in India. Then: Only show startups. Prepare applications for the first three."
          >
            <Input
              value={text}
              onChange={(event) => setText(event.target.value)}
              maxLength={2000}
              required
              placeholder="Find backend jobs in India"
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            busy={send.isPending}
            disabled={!text.trim()}
          >
            Send command
          </Button>
        </form>
      )}
      {(send.error || cancel.error || approve.error) && (
        <ErrorState error={send.error || cancel.error || approve.error} />
      )}
      {history.isLoading && <Skeleton />}
      {history.error && <ErrorState error={history.error} />}
      {nativeRuntime && <h2>Saved campaign history</h2>}
      {history.data?.length === 0 && <p>No campaigns yet.</p>}
      {history.data?.map((campaign) => (
        <article className="panel panel-body stack" key={campaign.id}>
          <div className="page-heading">
            <h2>{campaign.message}</h2>
            <Badge tone={campaign.state === "failed" ? "red" : "neutral"}>
              {readable(campaign.state)}
            </Badge>
          </div>
          <p style={{ whiteSpace: "pre-line" }}>
            {campaign.reply
              .split("\n")
              .filter((line) => !/^\d+\. /.test(line))
              .join("\n")}
          </p>
          {campaign.ranked_jobs && campaign.ranked_jobs.length > 0 && (
            <ol>
              {campaign.ranked_jobs.map((raw) => {
                const job = raw as {
                  job_id: string;
                  title: string;
                  company?: string;
                  evidence_url?: string;
                  source?: string;
                  ranking?: { match_score?: number; unknown_fields?: string[] };
                };
                return (
                  <li key={job.job_id}>
                    <External href={job.evidence_url}>{job.title}</External> ·{" "}
                    {job.company || "Company unknown"} · Match{" "}
                    {job.ranking?.match_score ?? "unknown"}
                  </li>
                );
              })}
            </ol>
          )}
          {Object.entries(campaign.applications || {}).map(([jobId, raw]) => {
            const draft = raw as {
              packet_id?: string;
              status?: string;
              missing_information?: string[];
            };
            return (
              <div key={jobId}>
                {draft.packet_id && (
                  <Link href={`/applications/${draft.packet_id}`}>
                    Review application draft
                  </Link>
                )}
                <p>{readable(draft.status)}</p>
                {draft.missing_information?.map((missing) => (
                  <p key={missing}>{missing}</p>
                ))}
              </div>
            );
          })}
          {!nativeRuntime && campaign.state === "awaiting_approval" && (
            <Button
              busy={approve.isPending}
              onClick={() => approve.mutate(campaign)}
            >
              Approve {campaign.plan.selected_jobs?.length} local drafts only
            </Button>
          )}
          {!nativeRuntime && !terminal.includes(campaign.state) && (
            <Button
              variant="danger"
              busy={cancel.isPending}
              onClick={() => cancel.mutate(campaign.id)}
            >
              Cancel campaign
            </Button>
          )}
          <details>
            <summary>Plan and execution history</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(
                {
                  filters: campaign.plan.filters,
                  actions: campaign.plan.actions,
                  results: campaign.results,
                  history: campaign.history,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </article>
      ))}
    </div>
  );
}
