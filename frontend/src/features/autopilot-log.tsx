"use client";
import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Select,
  Skeleton,
} from "@/components/ui";
import {
  APPLICATION_STATES,
  stamp,
  stateTone,
} from "@/features/autopilot-forms";

type Page = Schema<"ApplicationPage">;
type Application = Schema<"ApplicationRead">;
type StateEvent = Schema<"StateEventRead">;

export const APPLICATIONS_LIMIT = 50;

export function applicationsPath(platform: string, state: string) {
  const params = new URLSearchParams({ limit: String(APPLICATIONS_LIMIT) });
  if (platform) params.set("platform", platform);
  if (state) params.set("state", state);
  return `v2/applications?${params}`;
}

function payloadSummary(payload?: Record<string, unknown>) {
  if (!payload || Object.keys(payload).length === 0) return "";
  const text = JSON.stringify(payload);
  return text.length > 400 ? `${text.slice(0, 400)}…` : text;
}

function Events({ id }: { id: string }) {
  const events = useQuery({
    queryKey: ["v2-application-events", id],
    queryFn: () => api<StateEvent[]>(`v2/applications/${id}/events`),
  });
  if (events.isPending)
    return (
      <p className="muted" role="status">
        Loading state history…
      </p>
    );
  if (events.isError)
    return <ErrorState error={events.error} retry={() => events.refetch()} />;
  if (!events.data.length)
    return <p className="muted">No state transitions recorded.</p>;
  return (
    <ol className="event-list">
      {events.data.map((event, index) => {
        const payload = payloadSummary(event.payload);
        return (
          <li key={`${event.created_at}-${index}`}>
            <strong>
              {event.from_state ? `${event.from_state} → ` : ""}
              {event.to_state}
            </strong>{" "}
            <span className="muted">
              · {readable(event.event_type)} · {stamp(event.created_at, "—")}
            </span>
            {payload && <code className="event-payload">{payload}</code>}
          </li>
        );
      })}
    </ol>
  );
}

function ApplicationRow({ item }: { item: Application }) {
  const [open, setOpen] = useState(false);
  const eventsId = `events-${item.id}`;
  return (
    <Fragment>
      <tr>
        <td>
          <strong>{item.role_title || "Untitled role"}</strong>
          <small>
            {item.company_name || "Unknown company"} · {item.external_job_id}
          </small>
          {item.job_url && (
            <External href={item.job_url} className="small-print">
              Open posting
            </External>
          )}
        </td>
        <td>{readable(item.platform)}</td>
        <td>
          <Badge tone={stateTone(item.state)}>{readable(item.state)}</Badge>
          {item.attempts > 0 && (
            <small>
              {item.attempts} attempt{item.attempts === 1 ? "" : "s"}
            </small>
          )}
        </td>
        <td className="reason-cell">
          {item.reason || <span className="muted">—</span>}
          {item.retry_after && (
            <small>Retry after {stamp(item.retry_after)}</small>
          )}
        </td>
        <td>
          <small>
            {item.applied_at
              ? `Applied ${stamp(item.applied_at)}`
              : stamp(item.updated_at || item.created_at, "—")}
          </small>
        </td>
        <td>
          <Button
            variant="ghost"
            aria-expanded={open}
            aria-controls={open ? eventsId : undefined}
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide events" : "Show events"}
          </Button>
        </td>
      </tr>
      {open && (
        <tr className="events-row">
          <td colSpan={6} id={eventsId}>
            <Events id={item.id} />
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function ApplicationsLog({ platforms }: { platforms: string[] }) {
  const [platform, setPlatform] = useState("");
  const [state, setState] = useState("");
  const page = useQuery({
    queryKey: ["v2-applications", platform, state],
    queryFn: () => api<Page>(applicationsPath(platform, state)),
    refetchInterval: 15000,
  });
  return (
    <section className="spaced" aria-labelledby="log-heading">
      <div className="split log-toolbar">
        <div className="section-heading">
          <h2 id="log-heading">Recent applications</h2>
          <p className="muted">
            {page.data
              ? `Showing ${page.data.items.length} of ${page.data.total} · newest first`
              : "Every job the worker saw, with the reason it was skipped or failed."}
          </p>
        </div>
        <div className="actions">
          <Field label="Portal">
            <Select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="">All portals</option>
              {platforms.map((name) => (
                <option key={name} value={name}>
                  {readable(name)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="State">
            <Select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">All states</option>
              {APPLICATION_STATES.map((value) => (
                <option key={value} value={value}>
                  {readable(value)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
      {page.isPending ? (
        <Skeleton />
      ) : page.isError ? (
        <ErrorState error={page.error} retry={() => page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <p className="muted spaced">
          {platform || state
            ? "No applications match these filters."
            : "No applications recorded yet. They appear once the worker discovers jobs."}
        </p>
      ) : (
        <div className="table-wrap spaced">
          <table>
            <caption className="visually-hidden">
              Recent applications with state, reason and state history
            </caption>
            <thead>
              <tr>
                <th scope="col">JOB</th>
                <th scope="col">PORTAL</th>
                <th scope="col">STATE</th>
                <th scope="col">REASON</th>
                <th scope="col">UPDATED</th>
                <th scope="col">
                  <span className="visually-hidden">History</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {page.data.items.map((item) => (
                <ApplicationRow key={item.id} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
