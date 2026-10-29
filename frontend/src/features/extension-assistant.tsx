"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, ErrorState, External, Notice } from "@/components/ui";
import { api, post, readable, type Schema } from "@/lib/api";

// The native host and owner dashboard share this durable task. Opening Chrome,
// inspection and fill authorization remain separate extension gestures.
export type ExtensionTask = {
  id: string;
  version: number;
  application_id: string;
  job_id: string;
  company_name: string;
  job_title: string;
  packet_revision: number;
  profile_version: number;
  target_url: string;
  current_url: string;
  tab_id: number | null;
  tab_active: boolean;
  browser_connection: "connected" | "paused" | "disconnected" | "unverified";
  state: string;
  challenge_state:
    | "NONE"
    | "WIDGET_PRESENT_UNVERIFIED"
    | "CHALLENGE_BLOCKING"
    | "MANUALLY_RESOLVED_AND_SITE_VERIFIED"
    | "UNKNOWN";
  step: string | null;
  plan_id: string | null;
  authorization_id: string | null;
  field_answer_revisions: Record<string, number>;
  reason: string | null;
  next_action: string;
  mode: "ASSISTED_FILL";
  capabilities: {
    preview: boolean;
    assisted_fill: boolean;
    reviewed_submission: false;
    unattended_approved: false;
  };
  counts: {
    ready: number;
    completed: number;
    existing?: number;
    missing: number;
    manual: number;
    validation_errors: number;
  };
  updated_at: string;
};

const challengeMessages: Record<ExtensionTask["challenge_state"], string> = {
  NONE: "No challenge observed in the latest inspection.",
  WIDGET_PRESENT_UNVERIFIED:
    "Security widget present; completion is unverified. Proposals are read-only. Complete the check yourself, then inspect and review again.",
  CHALLENGE_BLOCKING:
    "Security challenge blocks filling. Complete it yourself on the employer page, then request a fresh inspection and review.",
  MANUALLY_RESOLVED_AND_SITE_VERIFIED:
    "Manual completion verified using supported site signals. A fresh inspection, answer review and fill authorization are still required.",
  UNKNOWN:
    "Security state could not be verified. Keep this form manual until a supported site check establishes its state.",
};

const closedTaskStates = new Set([
  "CANCELLED",
  "FAILED_FINAL",
  "SUBMISSION_UNKNOWN",
  "SUBMITTED_CONFIRMED",
]);
const closedPacketStates = new Set([
  "user_reported_submitted",
  "provider_confirmed_submitted",
  "submitting",
  "submission_unknown",
  "withdrawn",
  "abandoned",
]);

export function ExtensionAssistant({
  packet,
  hasUnsavedAnswers = false,
}: {
  packet: Schema<"PacketRead">;
  hasUnsavedAnswers?: boolean;
}) {
  const client = useQueryClient();
  const queryKey = ["extension-task", packet.id];
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      api<ExtensionTask | null>(
        `browser/extension-tasks/application/${packet.id}`,
        { signal },
      ),
    retry: false,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const task = query.data;
  const identityMatches =
    task?.application_id === packet.id && task?.job_id === packet.job_id;
  const stale = task?.packet_revision !== packet.revision;
  const current = task && identityMatches ? task : null;
  const control = useMutation({
    mutationFn: ({
      task,
      action,
    }: {
      task: ExtensionTask;
      action: "pause" | "resume" | "cancel";
    }) =>
      post<ExtensionTask>(`browser/extension-tasks/${task.id}/control`, {
        action,
        expected_version: task.version,
      }),
    onSuccess: (updated, { task }) => {
      if (
        updated.id === task.id &&
        updated.application_id === task.application_id &&
        updated.job_id === task.job_id
      )
        client.setQueryData(["extension-task", task.application_id], updated);
      void client.invalidateQueries({
        queryKey: ["extension-task", task.application_id],
      });
    },
    onError: () => {
      void client.invalidateQueries({ queryKey });
    },
  });
  const terminal = current && closedTaskStates.has(current.state);
  const resumeBlocked =
    stale ||
    hasUnsavedAnswers ||
    closedPacketStates.has(packet.lifecycle_state);

  return (
    <section className="panel" aria-label="Chrome extension assistant">
      <div className="panel-header">
        <h2>Chrome extension assistant</h2>
        <Badge
          tone={
            query.isError
              ? "amber"
              : current?.browser_connection === "connected"
                ? "green"
                : "neutral"
          }
        >
          {query.isError
            ? "Connection unverified"
            : current
              ? readable(current.browser_connection)
              : "No tab associated"}
        </Badge>
      </div>
      <div className="panel-body stack">
        <p>
          Use Automated Apply in Chrome to open this exact packet, inspect the
          current step, prepare answers, review them, and fill approved fields.
        </p>
        {query.isPending && <p role="status">Loading saved extension task…</p>}
        {query.isError && (
          <ErrorState error={query.error} retry={() => void query.refetch()} />
        )}
        {task && !identityMatches && (
          <Notice>
            The extension task does not match this job and packet. Refresh its
            status and associate the correct packet in Chrome before continuing.
          </Notice>
        )}
        {!query.isPending && !query.isError && !task && (
          <Notice>
            Next action: open Automated Apply in Chrome, enter this saved
            application ID and choose Open Application. No browser connection
            has been verified for this packet.
          </Notice>
        )}
        <p>
          <strong>Saved application ID:</strong> <code>{packet.id}</code> ·
          Revision {packet.revision}
        </p>
        {current && (
          <>
            <div className="split">
              <div>
                <h3>
                  {current.company_name} · {current.job_title}
                </h3>
                <p>
                  <Badge
                    tone={
                      terminal || current.state === "CHALLENGE_REQUIRED"
                        ? "amber"
                        : "neutral"
                    }
                  >
                    {readable(current.state)}
                  </Badge>
                </p>
                <p>
                  Packet revision {current.packet_revision} · Profile version{" "}
                  {current.profile_version}
                </p>
                <p>
                  Current step:{" "}
                  {current.step || "Inspect this page to identify its step"}
                </p>
                <p>
                  Application tab:{" "}
                  {current.tab_id === null
                    ? "Closed or not associated"
                    : current.tab_id}
                  {current.tab_id !== null &&
                    (current.tab_active
                      ? " · Active"
                      : " · Another tab is active")}
                </p>
              </div>
              <div>
                <h3>Exact destination</h3>
                <External href={current.target_url}>
                  {current.target_url}
                </External>
                {current.current_url &&
                  current.current_url !== current.target_url && (
                    <p>
                      Observed page:{" "}
                      <External href={current.current_url}>
                        {current.current_url}
                      </External>
                    </p>
                  )}
                <small>
                  Last synchronized:{" "}
                  {new Date(current.updated_at).toLocaleString()}
                  {query.isFetching ? " · Checking…" : ""}
                </small>
              </div>
            </div>
            {stale && (
              <Notice>
                This task belongs to packet revision {current.packet_revision}.
                The current revision is {packet.revision}. Inspect the current
                packet and review fresh answers before filling.
              </Notice>
            )}
            {hasUnsavedAnswers && (
              <Notice>
                Save your edited answers before resuming this application.
              </Notice>
            )}
            <dl className="detail-grid" aria-label="Inspected field status">
              <div>
                <dt>Ready to fill</dt>
                <dd>{current.counts.ready}</dd>
              </div>
              <div>
                <dt>Website retained value</dt>
                <dd>{current.counts.completed}</dd>
              </div>
              <div>
                <dt>Already completed before filling</dt>
                <dd>{current.counts.existing ?? 0}</dd>
              </div>
              <div>
                <dt>Missing answers</dt>
                <dd>{current.counts.missing}</dd>
              </div>
              <div>
                <dt>Manual-only fields</dt>
                <dd>{current.counts.manual}</dd>
              </div>
              <div>
                <dt>Validation errors</dt>
                <dd>{current.counts.validation_errors}</dd>
              </div>
            </dl>
            <div>
              <h3>Security challenge</h3>
              <p>
                {challengeMessages[current.challenge_state] ||
                  challengeMessages.UNKNOWN}
              </p>
            </div>
            {current.reason && <Notice>{readable(current.reason)}</Notice>}
            <p role="status">
              <strong>Next action:</strong>{" "}
              {query.isError
                ? "Reconnect and refresh saved status before continuing in Chrome."
                : current.next_action}
            </p>
            <div className="actions">
              <Button
                onClick={() => void query.refetch()}
                disabled={query.isFetching}
              >
                Refresh extension status
              </Button>
              <Button
                disabled={
                  control.isPending || !!terminal || current.state === "PAUSED"
                }
                onClick={() =>
                  control.mutate({ task: current, action: "pause" })
                }
              >
                Pause
              </Button>
              <Button
                disabled={
                  control.isPending ||
                  query.isError ||
                  !!terminal ||
                  current.state !== "PAUSED" ||
                  resumeBlocked
                }
                onClick={() =>
                  control.mutate({ task: current, action: "resume" })
                }
              >
                Resume
              </Button>
              <Button
                variant="danger"
                disabled={control.isPending || !!terminal}
                onClick={() =>
                  control.mutate({ task: current, action: "cancel" })
                }
              >
                Cancel
              </Button>
              <a className="button" href="/profile">
                Review saved answers
              </a>
            </div>
            {control.isError && <ErrorState error={control.error} />}
            <p className="muted">
              Preview generated means proposed answers only. A verified fill
              receipt records retained field values; it does not confirm an
              application submission. Existing answers and manual edits are
              preserved. Review field details and manual reasons in Chrome.
            </p>
            <ul aria-label="Application mode capabilities">
              <li>
                Preview only:{" "}
                {current.capabilities.preview ? "available" : "unavailable"}
              </li>
              <li>
                Assisted fill:{" "}
                {current.capabilities.assisted_fill
                  ? "requires exact field review and authorization in Chrome"
                  : "disabled for this task"}
              </li>
              <li>Reviewed submission: disabled</li>
              <li>Unattended approved: disabled</li>
            </ul>
          </>
        )}
        <p className="muted">
          Submission remains owner-operated on the employer website. This panel
          never fills or submits the form.
        </p>
      </div>
    </section>
  );
}
