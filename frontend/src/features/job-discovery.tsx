"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  Briefcase,
  CheckCircle2,
  Compass,
  FileSearch,
  RefreshCw,
  Search,
  Shield,
  ZapOff,
} from "lucide-react";
import { api, ApiError, post, readable } from "@/lib/api";
import {
  inspectDiscovery,
  prepareNewDiscovery,
  readDiscoveryAttempt,
  recoverDiscovery,
  type DiscoveryAttempt,
} from "./job-discovery-attempt";
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

export type SourceConfig = {
  id: string;
  display_name: string;
  adapter_type: "direct_api" | "apify" | "manual" | "restricted" | "gmail";
  operations: string[];
  authentication: string;
  availability:
    | "available"
    | "configuration_required"
    | "authorization_required"
    | "manual_import_only"
    | "unsupported"
    | "temporarily_unavailable";
  pricing: "free" | "paid" | "account_dependent";
  enabled: boolean;
  read_only: boolean;
  mutation_capabilities: string[];
  configuration: Record<string, unknown>;
  live_verified: boolean;
  owner_run_supported?: boolean;
};

export type JobDiscoveryPreview = {
  source: SourceConfig;
  query: {
    keywords: string[];
    locations: string[];
    remote_preference: "remote" | "hybrid" | "onsite" | "any" | null;
    employment_types: string[];
    page: number;
    limit: number;
    max_age_days: number | null;
  };
  jobs: unknown[];
  provider_calls: number;
  estimated_usd: number | null;
  estimate_only: boolean;
  message: string;
};

export type JobDiscoveryRun = {
  id: string;
  source: string;
  status: string;
  counts: {
    discovered?: number;
    inserted?: number;
    updated?: number;
    duplicate?: number;
    rejected?: number;
    failed?: number;
    skipped?: number;
  };
  errors: string[];
  started_at: string;
  finished_at: string | null;
  provider_run_id: string | null;
  usage: Record<string, unknown>;
  rankings: unknown[];
  job_ids: string[];
  local_intake_complete?: boolean | null;
  rankings_complete?: boolean | null;
};

function generateIdempotencyKey(): string {
  const uuid =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).substring(2, 18);
  return `job_disc_${uuid}`.slice(0, 50);
}

function sourceAvailable(source: SourceConfig | undefined): boolean {
  return Boolean(
    source?.enabled &&
    source.owner_run_supported !== false &&
    source.pricing === "free" &&
    source.adapter_type === "direct_api" &&
    source.read_only &&
    source.operations.includes("jobs") &&
    source.availability === "available",
  );
}

export function JobDiscovery() {
  const client = useQueryClient();
  const consentId = useId();

  const [selectedSource, setSelectedSource] = useState("arbeitnow");
  const [keywords, setKeywords] = useState("");
  const [locations, setLocations] = useState("");
  const [remotePreference, setRemotePreference] = useState<
    "any" | "remote" | "hybrid" | "onsite"
  >("any");
  const [limit, setLimit] = useState(20);
  const [useProfile, setUseProfile] = useState(true);

  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");
  const [runResult, setRunResult] = useState<JobDiscoveryRun | null>(null);
  const [attempt, setAttempt] = useState<DiscoveryAttempt | null>(null);
  const [attemptLoaded, setAttemptLoaded] = useState(false);
  const [attemptError, setAttemptError] = useState<unknown>(null);

  const sourcesQuery = useQuery({
    queryKey: ["discovery-sources"],
    queryFn: () =>
      api<{
        sources: SourceConfig[];
        people_search?: Record<string, unknown>;
      }>("discovery/sources"),
  });

  const parsedKeywords = keywords
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);

  const parsedLocations = locations
    .split(",")
    .map((l) => l.trim())
    .filter(Boolean);

  const runPayload = {
    source: selectedSource,
    query: {
      keywords: parsedKeywords,
      locations: parsedLocations,
      remote_preference: remotePreference === "any" ? null : remotePreference,
      employment_types: [],
      page: 1,
      limit,
      max_age_days: null,
    },
    idempotency_key: idempotencyKey || null,
    allow_paid: false,
    use_profile: useProfile,
    manual_jobs: [],
  };

  const previewMutation = useMutation({
    mutationFn: (key: string) =>
      post<JobDiscoveryPreview>("discovery/preview", {
        ...runPayload,
        idempotency_key: key,
      }),
  });

  const executeMutation = useMutation({
    mutationFn: (mayStart: boolean) =>
      recoverDiscovery(
        {
          ...runPayload,
          idempotency_key: idempotencyKey || null,
        },
        mayStart,
      ),
    onSettled: () => {
      try {
        setAttempt(readDiscoveryAttempt());
      } catch (error) {
        setAttemptError(error);
      }
    },
    onSuccess: (data) => {
      setRunResult(data);
      setConsentConfirmed(false);
      client.invalidateQueries({ queryKey: ["jobs"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const inspectMutation = useMutation({
    mutationFn: inspectDiscovery,
    onSuccess: (data) => {
      setRunResult(data);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const requestPending =
    !attemptLoaded ||
    previewMutation.isPending ||
    executeMutation.isPending ||
    inspectMutation.isPending;
  const savedAdmissionMissing =
    inspectMutation.error instanceof ApiError &&
    inspectMutation.error.status === 404;
  const criteriaLocked = Boolean(attempt && !savedAdmissionMissing);
  const terminalReviewed =
    runResult?.local_intake_complete === true &&
    runResult.rankings_complete === true &&
    Boolean(runResult.finished_at);
  useEffect(() => {
    try {
      const saved = readDiscoveryAttempt();
      setAttempt(saved);
      if (saved) {
        setSelectedSource(saved.source);
        inspectMutation.mutate();
      }
    } catch (error) {
      setAttemptError(error);
    }
    setAttemptLoaded(true);
    // Mount performs a saved GET only. New dispatch and local completion require their own actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCriteriaChange = () => {
    if (!attempt) inspectMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
    setConsentConfirmed(false);
    setRunResult(null);
    setIdempotencyKey("");
  };

  const handlePreview = () => {
    const key = idempotencyKey || generateIdempotencyKey();
    if (!idempotencyKey) {
      setIdempotencyKey(key);
    }
    setConsentConfirmed(false);
    setRunResult(null);
    previewMutation.mutate(key);
  };

  const handleExecute = () => {
    if (!idempotencyKey || !consentConfirmed) return;
    executeMutation.mutate(true);
  };

  const handleRetry = () => {
    executeMutation.mutate(false);
  };

  const handleReset = async () => {
    try {
      if (attempt) {
        if (!runResult)
          throw new Error(
            "Recover the saved discovery before preparing another search.",
          );
        await prepareNewDiscovery(runResult.id);
      }
    } catch (error) {
      setAttemptError(error);
      return;
    }
    setAttempt(null);
    setAttemptError(null);
    inspectMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
    setConsentConfirmed(false);
    setRunResult(null);
    setIdempotencyKey("");
  };

  const allSources = sourcesQuery.data?.sources || [];
  const currentSourceConfig = allSources.find((s) => s.id === selectedSource);

  const isCurrentSourceAvailable = sourceAvailable(currentSourceConfig);

  return (
    <div className="detail-grid">
      <section className="panel" aria-label="Job discovery controls">
        <div className="panel-header">
          <h2>Job discovery</h2>
          <Briefcase size={19} className="muted" />
        </div>
        <div className="panel-body stack">
          <p className="muted">
            Search genuine job listings from legitimately free public APIs.
            Preview the search plan first, then explicitly run discovery to
            ingest listings.
          </p>
          {attemptError != null && <ErrorState error={attemptError} />}
          {attempt && (
            <Notice>
              A saved search is retained for recovery. Refresh its result or
              complete its saved observations before preparing another search.
              <Button
                disabled={requestPending}
                onClick={() => inspectMutation.mutate()}
              >
                Recover saved discovery
              </Button>
              {runResult?.usage.finding_retained === true &&
                !terminalReviewed && (
                  <Button disabled={requestPending} onClick={handleRetry}>
                    Complete saved discovery
                  </Button>
                )}
            </Notice>
          )}
          {inspectMutation.isError && !runResult && (
            <ErrorState error={inspectMutation.error} />
          )}

          {sourcesQuery.isPending ? (
            <Skeleton />
          ) : sourcesQuery.isError ? (
            <ErrorState
              error={sourcesQuery.error}
              retry={() => sourcesQuery.refetch()}
            />
          ) : (
            <>
              <Field
                label="Discovery source provider"
                hint="Free public providers are selectable. Paid and unconfigured providers remain disabled."
              >
                <Select
                  aria-label="Discovery source provider"
                  disabled={requestPending || Boolean(attempt)}
                  value={selectedSource}
                  onChange={(e) => {
                    setSelectedSource(e.target.value);
                    handleCriteriaChange();
                  }}
                >
                  <optgroup label="Available Free Providers">
                    {allSources.filter(sourceAvailable).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.display_name} (Free · Available)
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Configuration Required">
                    {allSources
                      .filter(
                        (s) =>
                          s.pricing === "free" &&
                          s.availability === "configuration_required",
                      )
                      .map((s) => (
                        <option key={s.id} value={s.id} disabled>
                          {s.display_name} (Configuration required)
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="Paid / Apify Providers (Disabled)">
                    {allSources
                      .filter(
                        (s) =>
                          s.pricing !== "free" || s.adapter_type === "apify",
                      )
                      .map((s) => (
                        <option key={s.id} value={s.id} disabled>
                          {s.display_name} ({readable(s.pricing)} ·{" "}
                          {readable(s.adapter_type)})
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="Other unavailable sources">
                    {allSources
                      .filter(
                        (source) =>
                          !sourceAvailable(source) &&
                          source.pricing === "free" &&
                          source.adapter_type !== "apify" &&
                          source.availability !== "configuration_required",
                      )
                      .map((source) => (
                        <option key={source.id} value={source.id} disabled>
                          {source.display_name} (Unavailable for public
                          discovery)
                        </option>
                      ))}
                  </optgroup>
                </Select>
              </Field>

              {currentSourceConfig && (
                <div className="tag-list" aria-label="Source capabilities">
                  <Badge
                    tone={
                      currentSourceConfig.pricing === "free" ? "green" : "amber"
                    }
                  >
                    {readable(currentSourceConfig.pricing)} provider
                  </Badge>
                  <Badge
                    tone={
                      currentSourceConfig.availability === "available"
                        ? "green"
                        : "amber"
                    }
                  >
                    {readable(currentSourceConfig.availability)}
                  </Badge>
                  <Badge>{readable(currentSourceConfig.adapter_type)}</Badge>
                  <Badge>Read-only discovery</Badge>
                </div>
              )}

              {currentSourceConfig?.configuration?.board_allowlist_required &&
                !currentSourceConfig?.configuration?.boards_configured && (
                  <Notice>
                    Company board allowlist required: Configure permitted
                    company board identifiers in your environment before
                    discovery from {currentSourceConfig.display_name}.
                  </Notice>
                )}

              <Field
                label="Role / Technology keywords"
                hint="Comma-separated titles or tech stacks. Leave empty to use saved profile defaults."
              >
                <Input
                  aria-label="Role or technology keywords"
                  disabled={requestPending || criteriaLocked}
                  placeholder="e.g. Backend Engineer, Python, React"
                  value={keywords}
                  onChange={(e) => {
                    setKeywords(e.target.value);
                    handleCriteriaChange();
                  }}
                />
              </Field>

              <Field
                label="Locations"
                hint="Comma-separated target locations. Public APIs offer varying regional coverage."
              >
                <Input
                  aria-label="Search locations"
                  disabled={requestPending || criteriaLocked}
                  placeholder="e.g. Berlin, Remote, India"
                  value={locations}
                  onChange={(e) => {
                    setLocations(e.target.value);
                    handleCriteriaChange();
                  }}
                />
              </Field>

              <div className="filter-grid">
                <Field label="Workplace / Remote preference">
                  <Select
                    aria-label="Workplace preference"
                    disabled={requestPending || criteriaLocked}
                    value={remotePreference}
                    onChange={(e) => {
                      setRemotePreference(
                        e.target.value as
                          "any" | "remote" | "hybrid" | "onsite",
                      );
                      handleCriteriaChange();
                    }}
                  >
                    <option value="any">Any workplace</option>
                    <option value="remote">Remote only</option>
                    <option value="hybrid">Hybrid</option>
                    <option value="onsite">On-site</option>
                  </Select>
                </Field>

                <Field label="Result limit">
                  <Select
                    aria-label="Result limit"
                    disabled={requestPending || criteriaLocked}
                    value={String(limit)}
                    onChange={(e) => {
                      setLimit(Number(e.target.value));
                      handleCriteriaChange();
                    }}
                  >
                    <option value="10">10 jobs</option>
                    <option value="20">20 jobs (Default)</option>
                    <option value="50">50 jobs</option>
                  </Select>
                </Field>
              </div>

              <label className="check-label">
                <input
                  type="checkbox"
                  aria-label="Incorporate preferences from saved profile"
                  disabled={requestPending || criteriaLocked}
                  checked={useProfile}
                  onChange={(e) => {
                    setUseProfile(e.target.checked);
                    handleCriteriaChange();
                  }}
                />
                Incorporate target preferences from saved profile
              </label>

              <Button
                onClick={handlePreview}
                busy={previewMutation.isPending}
                disabled={
                  !isCurrentSourceAvailable ||
                  requestPending ||
                  criteriaLocked ||
                  attemptError != null
                }
              >
                <Search size={14} />
                Preview discovery plan
              </Button>
            </>
          )}

          {previewMutation.isError && (
            <ErrorState error={previewMutation.error} retry={handlePreview} />
          )}

          {previewMutation.data && (
            <div
              className="evidence-item"
              aria-label="Discovery preview details"
            >
              <div className="panel-header">
                <strong>Review your job discovery plan</strong>
                <FileSearch size={16} className="muted" />
              </div>
              <p>{previewMutation.data.message}</p>
              <ul className="meta-list">
                <li>
                  <strong>Provider:</strong>{" "}
                  {previewMutation.data.source.display_name} (
                  {readable(previewMutation.data.source.pricing)})
                </li>
                <li>
                  <strong>Effective keywords:</strong>{" "}
                  {previewMutation.data.query.keywords.length
                    ? previewMutation.data.query.keywords.join(", ")
                    : "Provider defaults / All roles"}
                </li>
                <li>
                  <strong>Effective locations:</strong>{" "}
                  {previewMutation.data.query.locations.length
                    ? previewMutation.data.query.locations.join(", ")
                    : "Any location"}
                </li>
                <li>
                  <strong>Workplace:</strong>{" "}
                  {readable(
                    previewMutation.data.query.remote_preference || "any",
                  )}
                </li>
                <li>
                  <strong>Max limit:</strong> {previewMutation.data.query.limit}{" "}
                  listings
                </li>
                <li>
                  <strong>Estimated cost:</strong>{" "}
                  {previewMutation.data.estimated_usd !== null
                    ? `$${previewMutation.data.estimated_usd.toFixed(2)}`
                    : "Free ($0.00)"}
                </li>
                <li>
                  <strong>Provider calls in preview:</strong>{" "}
                  {previewMutation.data.provider_calls}
                </li>
              </ul>

              <Notice>
                Preview performs no external network calls or database writes.
                Executing discovery calls the upstream provider, extracts job
                postings, and stores new records locally.
              </Notice>

              <label className="check-label" htmlFor={consentId}>
                <input
                  id={consentId}
                  type="checkbox"
                  checked={consentConfirmed}
                  onChange={(e) => setConsentConfirmed(e.target.checked)}
                />
                Run this approved job discovery on{" "}
                {previewMutation.data.source.display_name} now.
              </label>

              <div className="actions">
                <Button
                  variant="primary"
                  disabled={!consentConfirmed || requestPending}
                  busy={executeMutation.isPending}
                  onClick={handleExecute}
                >
                  Run approved discovery
                  <ArrowUpRight size={14} />
                </Button>
                <Button
                  disabled={
                    requestPending || Boolean(attempt && !terminalReviewed)
                  }
                  onClick={handleReset}
                >
                  Cancel plan
                </Button>
              </div>
            </div>
          )}

          {executeMutation.isError && (
            <div className="stack">
              <ErrorState error={executeMutation.error} />
              <div className="actions">
                <Button
                  variant="primary"
                  busy={executeMutation.isPending}
                  onClick={handleRetry}
                >
                  <RefreshCw size={13} />
                  Recover interrupted discovery
                </Button>
                <Button
                  disabled={
                    requestPending || Boolean(attempt && !terminalReviewed)
                  }
                  onClick={handleReset}
                >
                  Change search criteria
                </Button>
              </div>
            </div>
          )}

          {runResult && (
            <div
              className="evidence-item"
              aria-label="Discovery execution result"
            >
              <div className="panel-header">
                <strong>Discovery Run Result</strong>
                <Badge
                  tone={
                    runResult.status === "success"
                      ? "green"
                      : runResult.status === "partial"
                        ? "amber"
                        : "red"
                  }
                >
                  {readable(runResult.status)}
                </Badge>
              </div>

              {runResult.status === "running" && (
                <Notice>
                  Discovery is still running. Refresh the saved run status to
                  inspect progress; no additional provider request is started.
                </Notice>
              )}
              {runResult.status === "recovery_required" && (
                <Notice>
                  This discovery run was interrupted. Review its saved status
                  and messages before starting a new search. Refreshing or
                  retrying the same key does not restart discovery.
                </Notice>
              )}
              {runResult.status === "no_results" && (
                <Notice>
                  <AlertTriangle size={15} />
                  <span>
                    No jobs matching your criteria were found by{" "}
                    {readable(runResult.source)}. Try broadening your keywords
                    or expanding location settings.
                  </span>
                </Notice>
              )}

              {runResult.status === "source_unavailable" && (
                <Notice>
                  <ZapOff size={15} />
                  <span>
                    The provider source is currently unavailable or unreachable.
                    Please try again later.
                  </span>
                </Notice>
              )}

              {runResult.status === "rate_limited" && (
                <Notice>
                  <AlertTriangle size={15} />
                  <span>
                    Provider rate limit reached. The upstream service has
                    temporarily throttled requests. The saved run remains
                    retained; a new search must respect the provider cooldown.
                  </span>
                </Notice>
              )}

              {runResult.status === "configuration_required" && (
                <Notice>
                  <Shield size={15} />
                  <span>
                    Provider configuration is required before running discovery.
                    Configure your credentials or source boards in connections.
                  </span>
                </Notice>
              )}

              <div className="tag-list" aria-label="Ingestion counts">
                <Badge>Discovered: {runResult.counts?.discovered ?? 0}</Badge>
                <Badge tone="green">
                  Saved (New): {runResult.counts?.inserted ?? 0}
                </Badge>
                <Badge>Duplicate: {runResult.counts?.duplicate ?? 0}</Badge>
                <Badge tone="neutral">
                  Rejected: {runResult.counts?.rejected ?? 0}
                </Badge>
                {(runResult.counts?.failed ?? 0) > 0 && (
                  <Badge tone="red">Failed: {runResult.counts?.failed}</Badge>
                )}
              </div>

              {runResult.errors && runResult.errors.length > 0 && (
                <div className="error-list">
                  <strong>Provider messages:</strong>
                  {runResult.errors.map((err, i) => (
                    <p key={i} className="muted">
                      {err}
                    </p>
                  ))}
                </div>
              )}

              {inspectMutation.isError && (
                <ErrorState error={inspectMutation.error} />
              )}
              <div className="actions spaced">
                <Button
                  busy={inspectMutation.isPending}
                  disabled={executeMutation.isPending}
                  onClick={() => inspectMutation.mutate()}
                >
                  <RefreshCw size={13} />
                  Refresh saved run status
                </Button>
                <Link href="/jobs" className="button primary">
                  View discovered jobs
                  <ArrowUpRight size={13} />
                </Link>
                <Button
                  disabled={
                    requestPending || Boolean(attempt && !terminalReviewed)
                  }
                  onClick={handleReset}
                >
                  Start new search
                </Button>
              </div>
            </div>
          )}
        </div>
      </section>

      <aside className="panel" aria-label="Job discovery boundaries">
        <div className="panel-header">
          <h2>Clear discovery boundaries</h2>
          <Shield size={18} className="muted" />
        </div>
        <div className="panel-body stack">
          <div className="detail-section">
            <h3>Legitimately free sources</h3>
            <p>
              Arbeitnow, Remotive, Hacker News, and configured Greenhouse direct
              integrations do not consume credits or incur API fees.
            </p>
          </div>
          <div className="detail-section">
            <h3>Stable idempotency key</h3>
            <p>
              A saved search survives page reloads. Recovering it reads the
              original result or completes saved observations. Prepare a new
              search after reviewing the completed result.
            </p>
          </div>
          <div className="detail-section">
            <h3>No automated applications</h3>
            <p>
              Discovery only identifies and stores listings for your manual
              review. It never creates application submissions or emails
              employers without explicit owner actions.
            </p>
          </div>
          <div className="detail-section">
            <h3>Paid portals remain gated</h3>
            <p>
              Scrapers and paid portals (Naukri, Indeed, Glassdoor) require
              independent API tokens, explicit budget opt-in, and compliance
              review.
            </p>
            <div className="spaced">
              <Link className="external" href="/connections">
                Review connection readiness
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
