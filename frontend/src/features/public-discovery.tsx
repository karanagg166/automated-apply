"use client";
import { useEffect, useState } from "react";
type Platform = "himalayas" | "we_work_remotely";
interface Schedule {
  policy: { revision: number; enabled: Platform[] };
  last_status: { error_code: string | null } | null;
  application_dispatch: false;
}
interface Feed {
  batch_token: string;
  jobs: Array<{
    source_id: string;
    title: string;
    company_name: string | null;
    source_url: string;
    application_url: string;
    description: string;
    description_truncated: boolean;
  }>;
}
export type WorkflowRequest = <T>(
  path: string,
  method?: string,
  body?: unknown,
) => Promise<T>;
const sources: Array<[Platform, string]> = [
  ["himalayas", "Himalayas"],
  ["we_work_remotely", "We Work Remotely"],
];
export function PublicDiscovery({ request }: { request: WorkflowRequest }) {
  const [schedule, setSchedule] = useState<Schedule | null>(null),
    [enabled, setEnabled] = useState<Platform[]>([]);
  const [feeds, setFeeds] = useState<Partial<Record<Platform, Feed>>>({});
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function refresh() {
    const value = await request<Schedule>("discovery/schedule");
    setSchedule(value);
    setEnabled(value.policy.enabled);
  }
  useEffect(() => {
    void refresh().catch(() => setError("Discovery settings are unavailable."));
  }, []);
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery could not finish.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Public job discovery">
      <h2>Find remote jobs</h2>
      <p>
        Save listings for review. Application settings and approval remain
        separate.
      </p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {schedule?.last_status?.error_code && (
        <p role="status">
          The last discovery check could not finish. Refresh to check its
          status.
        </p>
      )}
      <fieldset disabled={busy || !schedule}>
        <legend>Discover automatically while the worker is running</legend>
        {sources.map(([id, label]) => (
          <label key={id}>
            <input
              type="checkbox"
              checked={enabled.includes(id)}
              onChange={(e) =>
                setEnabled(
                  e.target.checked
                    ? [...enabled, id]
                    : enabled.filter((p) => p !== id),
                )
              }
            />
            {label}
          </label>
        ))}
        <button
          type="button"
          onClick={() =>
            void perform(async () => {
              const saved = await request<Schedule>(
                "discovery/schedule",
                "PUT",
                { expected_revision: schedule!.policy.revision, enabled },
              );
              setSchedule(saved);
              setEnabled(saved.policy.enabled);
              setMessage("Discovery settings saved.");
            })
          }
        >
          Save discovery settings
        </button>
      </fieldset>
      <button
        type="button"
        disabled={busy}
        onClick={() => void perform(refresh)}
      >
        Refresh discovery status
      </button>
      {sources.map(([id, label]) => (
        <section key={id} aria-label={`${label} listings`}>
          <h3>{label}</h3>
          <button
            type="button"
            disabled={busy || !schedule}
            onClick={() =>
              void perform(async () => {
                const batch = await request<Feed>(
                  `platforms/${id}/discover`,
                  "POST",
                  { limit: 20 },
                );
                setFeeds((previous) => ({ ...previous, [id]: batch }));
              })
            }
          >
            Find jobs on {label}
          </button>
          {feeds[id] && (
            <>
              <p>These listings still need eligibility review.</p>
              <button
                type="button"
                disabled={busy || !feeds[id]?.batch_token}
                onClick={() =>
                  void perform(async () => {
                    const result = await request<{
                      inserted_count: number;
                      duplicate_count: number;
                      expired_count: number;
                    }>(`platforms/${id}/ingest`, "POST", {
                      batch_token: feeds[id]!.batch_token,
                    });
                    setMessage(
                      `Saved ${result.inserted_count} new listings; ${result.duplicate_count} already saved; ${result.expired_count} expired.`,
                    );
                  })
                }
              >
                Save {label} listings for review
              </button>
              <ul>
                {feeds[id]!.jobs.map((job) => (
                  <li key={job.source_id}>
                    <a
                      href={job.application_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {job.title}
                    </a>
                    {job.company_name && <span> — {job.company_name}</span>}
                    <p>
                      {job.description.replace(/<[^>]*>/g, " ")}
                      {job.description_truncated ? " … (preview)" : ""}
                    </p>
                    <a
                      href={job.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Source: {label}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ))}
    </section>
  );
}
