"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bell,
  Check,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api, dateLabel, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
export function Notifications() {
  const client = useQueryClient();
  const history = useQuery({
    queryKey: ["notification-history"],
    queryFn: () =>
      api<{
        attempts: Array<{
          id: string;
          channel: string;
          status: string;
          attempt_count: number;
          last_error: string | null;
          created_at: string;
        }>;
      }>("dashboard/notification-delivery-history"),
  });
  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<Schema<"NotificationRead">[]>("dashboard/notifications"),
  });
  const sync = useMutation({
    mutationFn: () =>
      post<{ status: string; created: number }>("dashboard/notifications/sync"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["notifications"] });
      client.invalidateQueries({ queryKey: ["notification-history"] });
    },
  });
  const read = useMutation({
    mutationFn: (id: string) => post(`dashboard/notifications/${id}/read`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["notifications"] });
      client.invalidateQueries({ queryKey: ["notification-history"] });
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="THE THINGS WORTH YOUR ATTENTION"
        title="Stay in the loop."
        description="Private in-app updates, with space to focus."
        actions={
          <>
            <Link className="button" href="/settings">
              Preferences
            </Link>
            <Button
              variant="primary"
              onClick={() => sync.mutate()}
              busy={sync.isPending}
            >
              <RefreshCw size={13} />
              Check saved activity
            </Button>
          </>
        }
      />
      {sync.isError && <ErrorState error={sync.error} />}{" "}
      {sync.data && (
        <Notice>
          {readable(sync.data.status)} · {sync.data.created} new notifications.
          No external messages were delivered.
        </Notice>
      )}
      {read.isError && <ErrorState error={read.error} />}{" "}
      {notifications.isPending ? (
        <Skeleton />
      ) : notifications.isError ? (
        <ErrorState error={notifications.error} />
      ) : notifications.data.length ? (
        <section className="panel">
          {notifications.data.map((n) => (
            <article
              className={`notification-item ${n.read_at ? "read" : ""}`}
              key={n.id}
            >
              <span className="row-icon">
                <Bell size={16} />
              </span>
              <div>
                <div className="split">
                  <h3>{n.title}</h3>
                  <time>{dateLabel(n.created_at)}</time>
                </div>
                <p>{n.body}</p>
                <Badge>{readable(n.kind)}</Badge>
                <div className="actions">
                  <Link className="external" href={n.href}>
                    Review activity
                    <ArrowUpRight size={13} />
                  </Link>
                  {!n.read_at && (
                    <Button
                      variant="ghost"
                      busy={read.isPending}
                      onClick={() => read.mutate(n.id)}
                    >
                      <Check size={12} />
                      Mark read
                    </Button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <Empty
          title="A quieter kind of inbox."
          description="Check saved activity to collect high-match job alerts, application reviews, draft approvals and your daily summary. Quiet hours and pause preferences are respected."
        />
      )}
      <section className="panel spaced">
        <div className="panel-header">
          <h2>Channel activity & failure history</h2>
          <Badge>External delivery disabled</Badge>
        </div>
        <div className="panel-body">
          {history.isError ? (
            <ErrorState error={history.error} />
          ) : history.data?.attempts.length ? (
            history.data.attempts.map((a) => (
              <div className="evidence-item split" key={a.id}>
                <div>
                  <strong>
                    {readable(a.channel)} · {readable(a.status)}
                  </strong>
                  <p>
                    {a.last_error
                      ? `Failure: ${a.last_error}`
                      : "No failure recorded"}{" "}
                    · {dateLabel(a.created_at)}
                  </p>
                </div>
                <Badge>{a.attempt_count} attempt</Badge>
              </div>
            ))
          ) : (
            <p className="section-intro">
              No channel activity recorded. In-app availability is separate from
              an external delivery receipt. Uncertain external outcomes are
              never retried automatically.
            </p>
          )}
        </div>
      </section>
    </>
  );
}
export function Settings() {
  const client = useQueryClient(),
    [preferences, setPreferences] = useState<Schema<"NotificationPreferences">>(
      {
        in_app: true,
        paused: false,
        daily_digest: true,
        minimum_job_score: 75,
        minimum_startup_score: 70,
        automation_failures: true,
        quiet_start: 22,
        quiet_end: 8,
        timezone: "Asia/Kolkata",
        browser_push: false,
        telegram: false,
        whatsapp: false,
      },
    ),
    [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () =>
      api<Schema<"NotificationPreferences">>(
        "dashboard/notification-preferences",
      ),
  });
  useEffect(() => {
    if (query.data) setPreferences(query.data);
  }, [query.data]);
  const save = useMutation({
    mutationFn: () =>
      api<Schema<"NotificationPreferences">>(
        "dashboard/notification-preferences",
        { method: "PUT", body: JSON.stringify(preferences) },
      ),
    onSuccess: () => {
      setSaved(true);
      client.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="YOUR WORKSPACE, YOUR TERMS"
        title="A little more control."
        description="Choose when your workspace asks for attention."
      />
      <div className="detail-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Notification preferences</h2>
            <ShieldCheck size={17} className="muted" />
          </div>
          <div className="panel-body">
            {query.isPending ? (
              <Skeleton />
            ) : query.isError ? (
              <ErrorState error={query.error} />
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  save.mutate();
                }}
              >
                {[
                  [
                    "in_app",
                    "In-app notifications",
                    "Keep private updates inside this workspace.",
                  ],
                  [
                    "paused",
                    "Pause all notifications",
                    "Preserve preferences while taking a break.",
                  ],
                  [
                    "daily_digest",
                    "Daily summary",
                    "At most one digest per local calendar day, when you check saved activity.",
                  ],
                  [
                    "automation_failures",
                    "Discovery failure alerts",
                    "At most one alert per source per local day.",
                  ],
                ].map(([key, title, description]) => (
                  <label className="preference-row" key={key}>
                    <div>
                      <strong>{title}</strong>
                      <p>{description}</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={!!preferences[key as keyof typeof preferences]}
                      onChange={(e) => {
                        setPreferences({
                          ...preferences,
                          [key]: e.target.checked,
                        });
                        setSaved(false);
                      }}
                    />
                  </label>
                ))}
                <div className="form-grid spaced">
                  <Field label="Minimum job relevance score">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={preferences.minimum_job_score}
                      onChange={(e) =>
                        setPreferences({
                          ...preferences,
                          minimum_job_score: Number(e.target.value),
                        })
                      }
                    />
                  </Field>
                  <Field label="Minimum startup relevance score">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={preferences.minimum_startup_score}
                      onChange={(e) =>
                        setPreferences({
                          ...preferences,
                          minimum_startup_score: Number(e.target.value),
                        })
                      }
                    />
                  </Field>
                  <Field label="Quiet hours start (0–23)">
                    <Input
                      type="number"
                      min={0}
                      max={23}
                      value={preferences.quiet_start ?? 22}
                      onChange={(e) =>
                        setPreferences({
                          ...preferences,
                          quiet_start: Number(e.target.value),
                        })
                      }
                    />
                  </Field>
                  <Field label="Quiet hours end (0–23)">
                    <Input
                      type="number"
                      min={0}
                      max={23}
                      value={preferences.quiet_end ?? 8}
                      onChange={(e) =>
                        setPreferences({
                          ...preferences,
                          quiet_end: Number(e.target.value),
                        })
                      }
                    />
                  </Field>
                  <Field label="IANA timezone">
                    <Input
                      required
                      value={preferences.timezone || ""}
                      onChange={(e) =>
                        setPreferences({
                          ...preferences,
                          timezone: e.target.value,
                        })
                      }
                    />
                  </Field>
                </div>
                <Notice>
                  Quiet hours defer in-app generation. Set equal start/end hours
                  to disable quiet hours. Scheduled checks require a separately
                  activated discovery worker.
                </Notice>
                <Button type="submit" variant="primary" busy={save.isPending}>
                  Save preferences
                </Button>
                {save.isError && <ErrorState error={save.error} />}{" "}
                {saved && <Notice>Notification preferences saved.</Notice>}
              </form>
            )}
          </div>
        </section>
        <aside className="panel">
          <div className="panel-header">
            <h2>Delivery channels</h2>
          </div>
          <div className="panel-body stack">
            {[
              [
                "In-app",
                "Implemented",
                "Private, deduplicated notifications from saved activity.",
              ],
              [
                "Browser push",
                "Not configured",
                "Push subscriptions and a delivery worker are not implemented in this phase.",
              ],
              [
                "Telegram",
                "Not configured",
                "Requires separate owner opt-in, a private bot token and a future delivery adapter.",
              ],
              [
                "WhatsApp Cloud API",
                "Disabled · pricing review required",
                "Official API only. Business setup, recipient opt-in, approved templates, current pricing and a budget are required. Proactive alerts are not assumed free.",
              ],
            ].map(([title, state, description]) => (
              <div className="detail-section" key={title}>
                <div className="split">
                  <h3>{title}</h3>
                  <Badge>{state}</Badge>
                </div>
                <p className="spaced">{description}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </>
  );
}
