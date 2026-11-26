"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, post, readable } from "@/lib/api";
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
import {
  inspectStartup,
  prepareStartup,
  recoverStartup,
  reviewStartupChild,
  startupAttempt,
  startupComplete,
  type StartupAttempt,
  type StartupRun,
} from "./startup-discovery-attempt";
type Source = {
  provider: string;
  modes: string[];
  availability: string;
  configured: boolean;
  authorized: boolean;
  pricing: string;
  native_execution_implemented?: boolean;
  native_execution?: {
    ready: boolean;
    run_cap_usd?: string;
    monthly_limit_usd?: string;
  };
};
type Preview = {
  source: Source;
  query: { keywords: string[]; locations: string[] };
  provider_calls: number;
  writes: number;
  job_led_available: boolean;
  message: string;
  paid_execution?: {
    ready: boolean;
    run_cap_usd?: string;
    monthly_limit_usd?: string;
    estimated_usd?: string | null;
    blocker?: string | null;
  };
};
function available(s: Source) {
  return (
    s.native_execution_implemented === true &&
    s.configured &&
    s.authorized &&
    s.availability === "available" &&
    s.modes.includes("job_led") &&
    (s.pricing !== "paid" || s.native_execution?.ready === true)
  );
}
export function StartupDiscovery({
  onReviewChild,
}: {
  onReviewChild: () => void;
}) {
  const client = useQueryClient();
  const [source, setSource] = useState("hacker_news"),
    [keywords, setKeywords] = useState(""),
    [locations, setLocations] = useState("");
  const [useProfile, setUseProfile] = useState(false),
    [paid, setPaid] = useState(false),
    [consent, setConsent] = useState(false),
    [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState<StartupAttempt | null>(null),
    [run, setRun] = useState<StartupRun | null>(null),
    [error, setError] = useState<unknown>(null);
  const sources = useQuery({
    queryKey: ["startup-sources"],
    queryFn: () => api<{ sources: Source[] }>("startups/sources"),
  });
  const current = sources.data?.sources.find((s) => s.provider === source);
  const isPaid = current?.pricing === "paid";
  const body = {
    source,
    mode: "job_led",
    idempotency_key: null,
    query: {
      keywords: keywords
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      locations: locations
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      limit: 20,
      max_age_days: null,
    },
    filters: {
      use_profile: useProfile,
      max_employees: null,
      include_unknown_size: true,
      application_status: "all",
    },
    permission_confirmed: false,
    allow_paid: Boolean(isPaid && paid),
  };
  const accept = (r: StartupRun) => {
    setRun(r);
    setConsent(false);
    client.invalidateQueries({ queryKey: ["startups"] });
    client.invalidateQueries({ queryKey: ["jobs"] });
  };
  const inspect = useMutation({
    mutationFn: inspectStartup,
    onSuccess: accept,
  });
  const execute = useMutation({
    mutationFn: (mayStart: boolean) => recoverStartup(body, mayStart),
    onSuccess: accept,
    onSettled: () => {
      try {
        setAttempt(startupAttempt());
      } catch (e) {
        setError(e);
      }
    },
  });
  const preview = useMutation({
    mutationFn: () => post<Preview>("startups/discovery/preview", body),
  });
  const child = useMutation({
    mutationFn: reviewStartupChild,
    onSuccess: onReviewChild,
  });
  const release = useMutation({
    mutationFn: prepareStartup,
    onSuccess: () => {
      setAttempt(null);
      setRun(null);
      setConsent(false);
      setPaid(false);
      inspect.reset();
      execute.reset();
      preview.reset();
      setError(null);
    },
  });
  const pending =
    !loaded ||
    inspect.isPending ||
    execute.isPending ||
    preview.isPending ||
    child.isPending ||
    release.isPending;
  const admissionMissing =
    inspect.error instanceof ApiError && inspect.error.status === 404;
  const locked = Boolean(attempt && !admissionMissing);
  useEffect(() => {
    try {
      const saved = startupAttempt();
      setAttempt(saved);
      if (saved) {
        setSource(saved.source);
        inspect.mutate();
      }
    } catch (e) {
      setError(e);
    }
    setLoaded(true);
    // Saved GET only on mount; every execution action remains explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const changed = (clearPaid = true) => {
    preview.reset();
    execute.reset();
    setConsent(false);
    setRun(null);
    if (clearPaid) setPaid(false);
  };
  return (
    <div className="detail-grid">
      <section className="panel" aria-label="Startup discovery controls">
        <div className="panel-header">
          <h2>Startup discovery</h2>
        </div>
        <div className="panel-body stack">
          <p className="muted">
            Discover companies through original job observations. Unknown
            company size, location and startup claims remain unverified.
          </p>
          {error != null && <ErrorState error={error} />}
          {attempt && (
            <Notice>
              A saved startup search is retained. Refresh and review it before
              another search.
              <Button disabled={pending} onClick={() => inspect.mutate()}>
                Refresh saved startup search
              </Button>
            </Notice>
          )}
          {sources.isPending ? (
            <Skeleton />
          ) : sources.isError ? (
            <ErrorState error={sources.error} />
          ) : (
            <>
              <Field label="Startup source">
                <Select
                  aria-label="Startup source"
                  disabled={pending || Boolean(attempt)}
                  value={source}
                  onChange={(e) => {
                    setSource(e.target.value);
                    changed();
                  }}
                >
                  {sources.data?.sources
                    .filter((s) => s.modes.includes("job_led"))
                    .map((s) => (
                      <option
                        key={s.provider}
                        value={s.provider}
                        disabled={!available(s)}
                      >
                        {readable(s.provider)} · {readable(s.pricing)} ·{" "}
                        {available(s) ? "Ready" : "Setup required"}
                      </option>
                    ))}
                </Select>
              </Field>
              <Field label="Titles / technologies">
                <Input
                  aria-label="Startup role keywords"
                  disabled={pending || locked}
                  value={keywords}
                  onChange={(e) => {
                    setKeywords(e.target.value);
                    changed();
                  }}
                  placeholder="Python, Backend Engineer"
                />
              </Field>
              <Field label="Locations">
                <Input
                  aria-label="Startup search locations"
                  disabled={pending || locked}
                  value={locations}
                  onChange={(e) => {
                    setLocations(e.target.value);
                    changed();
                  }}
                  placeholder="India, Bengaluru"
                />
              </Field>
              <label className="check-label">
                <input
                  type="checkbox"
                  aria-label="Use saved profile for startup discovery"
                  checked={useProfile}
                  disabled={pending || locked}
                  onChange={(e) => {
                    setUseProfile(e.target.checked);
                    changed();
                  }}
                />
                Use saved profile preferences
              </label>
              {isPaid && (
                <label className="check-label">
                  <input
                    type="checkbox"
                    aria-label="Allow paid startup discovery"
                    checked={paid}
                    disabled={pending || locked}
                    onChange={(e) => {
                      changed(false);
                      setPaid(e.target.checked);
                    }}
                  />
                  Authorize paid discovery with run cap $
                  {current?.native_execution?.run_cap_usd ?? "unavailable"} and
                  monthly limit $
                  {current?.native_execution?.monthly_limit_usd ??
                    "unavailable"}
                  .
                </label>
              )}
              <Button
                disabled={
                  pending ||
                  locked ||
                  error != null ||
                  !current ||
                  !available(current) ||
                  Boolean(isPaid && !paid)
                }
                busy={preview.isPending}
                onClick={() => {
                  setConsent(false);
                  preview.mutate();
                }}
              >
                Preview startup discovery
              </Button>
            </>
          )}
          {preview.isError && <ErrorState error={preview.error} />}
          {preview.data && (
            <div className="evidence-item stack">
              <strong>Review your startup discovery plan</strong>
              <p>{preview.data.message}</p>
              <p>
                Provider calls: {preview.data.provider_calls} · Writes:{" "}
                {preview.data.writes} · Maximum 20 listings
              </p>
              <p>
                Effective keywords:{" "}
                {preview.data.query?.keywords.join(", ") || "Provider defaults"}{" "}
                · Locations: {preview.data.query?.locations.join(", ") || "Any"}
              </p>
              {preview.data.paid_execution && (
                <Notice>
                  Run cap: $
                  {preview.data.paid_execution.run_cap_usd ?? "unavailable"};
                  estimated cost:{" "}
                  {preview.data.paid_execution.estimated_usd
                    ? `$${preview.data.paid_execution.estimated_usd}`
                    : "unavailable"}
                  . The full cap remains reserved after an uncertain start;
                  final billing is unverified.
                  {preview.data.paid_execution.blocker && (
                    <p>{readable(preview.data.paid_execution.blocker)}</p>
                  )}
                </Notice>
              )}
              <label className="check-label">
                <input
                  type="checkbox"
                  aria-label="Run this bounded startup search"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                Run this bounded startup search now.
              </label>
              <Button
                disabled={
                  pending ||
                  !consent ||
                  preview.data.job_led_available !== true ||
                  Boolean(
                    isPaid &&
                    (!paid || preview.data.paid_execution?.ready !== true),
                  )
                }
                busy={execute.isPending}
                onClick={() => execute.mutate(true)}
              >
                Run approved startup discovery
              </Button>
            </div>
          )}
          {inspect.isError && <ErrorState error={inspect.error} />}
          {execute.isError && <ErrorState error={execute.error} />}
          {child.isError && <ErrorState error={child.error} />}
          {release.isError && <ErrorState error={release.error} />}
          {run && (
            <div
              className="evidence-item stack"
              aria-label="Startup discovery result"
            >
              <strong>Run result: {readable(run.status)}</strong>
              <div className="tag-list">
                {Object.entries(run.counts).map(([k, n]) => (
                  <Badge key={k}>
                    {readable(k)}: {n}
                  </Badge>
                ))}
              </div>
              {run.errors.map((s, i) => (
                <p key={i}>{readable(s)}</p>
              ))}
              {run.child_run?.reservation && (
                <Notice>
                  Retained child reservation: $
                  {run.child_run.reservation.reserved_usd}; final billing is
                  unverified.
                </Notice>
              )}
              {!startupComplete(run) && (
                <Notice>
                  The original child remains{" "}
                  {readable(run.child_run?.status ?? "pending")}. Saved refresh
                  does not repeat provider acquisition.
                </Notice>
              )}
              {run.child_run && (
                <Button disabled={pending} onClick={() => child.mutate(run.id)}>
                  Review original child discovery
                </Button>
              )}
              <Link className="external" href="/startups">
                Review saved companies
              </Link>
              <Button
                disabled={pending || !startupComplete(run)}
                onClick={() => release.mutate(run.id)}
              >
                Review result and prepare new startup search
              </Button>
            </div>
          )}
        </div>
      </section>
      <aside className="panel">
        <div className="panel-header">
          <h2>Discovery evidence</h2>
        </div>
        <div className="panel-body stack">
          <p>
            Company results come from the original child job's saved company IDs
            and selected catalog evidence. Name similarity alone does not
            establish identity or team size.
          </p>
          <p>
            Paid child reads require separate consent in the original job
            discovery. Unknown starts stay held. Discovery does not submit
            applications or send messages.
          </p>
          <Link href="/connections">Review connection readiness</Link>
        </div>
      </aside>
    </div>
  );
}
