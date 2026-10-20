"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { api, post, readable, type Schema } from "@/lib/api";
import { ResumeReview } from "./resume-review";

function timestamp(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "Not observed";
}

export function ResumeSync() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["resume-sync"],
    queryFn: () => api<Schema<"SyncStatus">>("dashboard/resume-sync"),
  });
  const [reviewId, setReviewId] = useState<string | null>(null),
    [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(""),
    [enabled, setEnabled] = useState(false),
    [interval, setInterval] = useState(24);
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["resume-sync"] });
    client.invalidateQueries({ queryKey: ["private-resumes"] });
    client.invalidateQueries({ queryKey: ["notifications"] });
  };
  const sync = useMutation({
    retry: false,
    mutationFn: () =>
      post("dashboard/resume-sync/sync", {
        expected_generation: query.data?.generation,
      }),
    onSuccess: refresh,
  });
  const save = useMutation({
    retry: false,
    mutationFn: () =>
      api("dashboard/resume-sync/source", {
        method: "PUT",
        body: JSON.stringify({
          canonical_url: url,
          expected_generation: query.data?.generation,
          sync_enabled: enabled,
          interval_hours: interval,
        }),
      }),
    onSuccess: () => {
      setEditing(false);
      setReviewId(null);
      refresh();
    },
  });
  if (query.isPending) return <Skeleton />;
  if (query.isError) return <ErrorState error={query.error} />;
  const state = query.data;
  return (
    <div className="stack spaced">
      <section className="panel">
        <div className="panel-header">
          <h2>Resume Sync</h2>
          <Badge tone={state.connected ? "green" : "amber"}>
            {state.connected
              ? "Fetched and validated"
              : "Awaiting successful validation"}
          </Badge>
        </div>
        <div className="panel-body stack">
          <p>Source: Google Drive · {state.file_name || "No PDF fetched"}</p>
          <External href={state.canonical_url}>Review source</External>
          <div className="form-grid">
            {[
              ["Last checked", timestamp(state.last_checked_at)],
              ["Last changed", timestamp(state.last_changed_at)],
              [
                "Latest downloaded version",
                state.latest
                  ? `${state.latest.sha256.slice(0, 12)} · ${timestamp(state.latest.downloaded_at)}`
                  : "None",
              ],
              [
                "Active approved Drive version",
                state.active
                  ? `${state.active.file_name} · ${state.active.sha256.slice(0, 12)}`
                  : "None approved",
              ],
              ["Sync status", readable(state.status)],
              [
                "Periodic checks",
                state.sync_enabled
                  ? `Enabled · every ${state.interval_hours} hours`
                  : "Disabled",
              ],
            ].map(([label, value]) => (
              <div className="evidence-item" key={label}>
                <strong>{label}</strong>
                <p>{value}</p>
              </div>
            ))}
          </div>
          <Notice>{state.scheduler_message}</Notice>
          <p>{state.metadata_note}</p>
          {state.last_error && (
            <p role="alert">
              The check failed: {readable(state.last_error)}. Review file
              sharing and source access, then try again. The last approved
              resume remains active.
            </p>
          )}
          {state.pending_changes && (
            <Notice>
              Pending changes need your review. Your current approved resume and
              verified facts remain active.
            </Notice>
          )}
          <div className="actions">
            <Button
              type="button"
              busy={sync.isPending}
              disabled={!state.canonical_url || editing}
              onClick={() => sync.mutate()}
            >
              Sync Now
            </Button>
            <Button
              type="button"
              disabled={
                !state.pending_changes || !state.latest || sync.isPending
              }
              onClick={() => setReviewId(state.latest?.id || null)}
            >
              Review Changes
            </Button>
            <Button
              type="button"
              onClick={() => {
                setUrl(state.canonical_url || "");
                setEnabled(state.sync_enabled);
                setInterval(state.interval_hours);
                setEditing(!editing);
              }}
            >
              Change Resume Source / Settings
            </Button>
          </div>
          {sync.isError && <ErrorState error={sync.error} />}
          {editing && (
            <form
              className="stack"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <p>
                Editing the same Drive file keeps its ID stable. A newly
                uploaded file normally has another ID: explicitly choose its URL
                here. Saving a new source keeps your current approved resume
                active and requires a fresh successful check.
              </p>
              <Field label="Canonical Google Drive resume URL">
                <Input
                  type="url"
                  required
                  maxLength={2048}
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </Field>
              <Field label="Check interval in hours">
                <Input
                  type="number"
                  min={1}
                  max={168}
                  required
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                />
              </Field>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                <span>
                  Enable periodic resume checks when the resume worker is
                  running. New facts always require my review.
                </span>
              </label>
              <Button type="submit" busy={save.isPending}>
                Save resume source settings
              </Button>
              {save.isError && <ErrorState error={save.error} />}
            </form>
          )}
          {!!state.history.length && (
            <details>
              <summary>
                Resume version history ({state.history.length}, latest 50)
              </summary>
              {state.history.map((version) => (
                <div className="evidence-item" key={version.id}>
                  <strong>
                    {version.file_name} · {version.sha256.slice(0, 12)}
                  </strong>
                  <p>
                    {timestamp(version.downloaded_at)} ·{" "}
                    {readable(version.review_status)}
                  </p>
                  <a
                    className="button"
                    href={`/api/backend/dashboard/resumes/${version.private_resume_id}`}
                  >
                    Download privately
                  </a>
                </div>
              ))}
            </details>
          )}
        </div>
      </section>
      {reviewId && (
        <ResumeReview
          key={reviewId}
          versionId={reviewId}
          onClose={() => setReviewId(null)}
        />
      )}
    </div>
  );
}
