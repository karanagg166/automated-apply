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
  inspectDiscoveryRead,
  paidDiscoverySource,
  prepareNextDiscoveryRead,
  readDiscoveryReadAttempt,
  recoverDiscoveryRead,
  type DiscoveryReadAttempt,
  type DiscoveryReadResult,
  type DiscoveryReadState,
} from "./job-discovery-read-attempt";
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
  paid_execution?: PaidPlan;
  manual_import?: { valid_records: number; rejected_records: number };
};

type PaidPlan = {
  ready: boolean;
  blocker?: string | null;
  run_cap_usd?: string;
  monthly_limit_usd?: string;
  estimated_usd?: string | null;
};
function paidPlan(source: SourceConfig | undefined): PaidPlan | undefined {
  const value = source?.configuration.native_execution;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as PaidPlan)
    : undefined;
}

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
  original_scope_available?: boolean;
  billing_final?: boolean;
  reservation?: {
    reserved_usd: string;
    accounting: string;
    billing_final: boolean;
  };
};

function generateIdempotencyKey(): string {
  const uuid =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).substring(2, 18);
  return `job_disc_${uuid}`.slice(0, 50);
}

function manualImportAvailable(source: SourceConfig | undefined): boolean {
  return Boolean(
    source?.enabled &&
    source.adapter_type === "manual" &&
    source.owner_run_supported === true &&
    source.operations.includes("manual_import"),
  );
}

function sourceAvailable(source: SourceConfig | undefined): boolean {
  if (manualImportAvailable(source)) return true;
  return Boolean(
    source?.enabled &&
    source.owner_run_supported !== false &&
    ((source.pricing === "free" && source.adapter_type === "direct_api") ||
      (source.pricing === "paid" &&
        source.adapter_type === "apify" &&
        source.owner_run_supported === true &&
        paidPlan(source)?.ready === true)) &&
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
  const [allowPaid, setAllowPaid] = useState(false);
  const [listing, setListing] = useState({
    url: "",
    title: "",
    employer: "",
    employerUrl: "",
  });

  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");
  const [runResult, setRunResult] = useState<JobDiscoveryRun | null>(null);
  const [attempt, setAttempt] = useState<DiscoveryAttempt | null>(null);
  const [attemptLoaded, setAttemptLoaded] = useState(false);
  const [attemptError, setAttemptError] = useState<unknown>(null);
  const [readAttempt, setReadAttempt] = useState<DiscoveryReadAttempt | null>(
    null,
  );
  const [readResult, setReadResult] = useState<DiscoveryReadResult | null>(
    null,
  );
  const [readConsent, setReadConsent] = useState(false);

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

  const allSources = sourcesQuery.data?.sources || [];
  const currentSourceConfig = allSources.find((s) => s.id === selectedSource);
  const paidSource = currentSourceConfig?.adapter_type === "apify";
  const manualSource = manualImportAvailable(currentSourceConfig);
  const listingReady = listing.title.trim() && listing.url.trim();

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
    allow_paid: paidSource && allowPaid,
    use_profile: useProfile,
    manual_jobs:
      manualSource && listingReady
        ? [
            {
              source_name: selectedSource,
              original_url: listing.url.trim(),
              title: listing.title.trim(),
              company_name: listing.employer.trim() || null,
              ...(selectedSource === "hiringcafe" && listing.employerUrl.trim()
                ? { application_url: listing.employerUrl.trim() }
                : {}),
            },
          ]
        : [],
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

  const applyReadState = (data: DiscoveryReadState) => {
    setRunResult(data.run);
    setReadAttempt(data.attempt);
    setReadResult(data.read);
    setAttempt(readDiscoveryAttempt());
    setSelectedSource(data.run.source);
    client.invalidateQueries({ queryKey: ["jobs"] });
  };
  const inspectReadMutation = useMutation({
    mutationFn: inspectDiscoveryRead,
    onSuccess: applyReadState,
  });
  const recoverReadMutation = useMutation({
    mutationFn: (mayRead: boolean) => recoverDiscoveryRead(mayRead),
    onSuccess: applyReadState,
    onSettled: () => {
      setReadConsent(false);
      try {
        setReadAttempt(readDiscoveryReadAttempt());
      } catch (error) {
        setAttemptError(error);
      }
    },
  });
  const nextReadMutation = useMutation({
    mutationFn: prepareNextDiscoveryRead,
    onSuccess: (pointer) => {
      setReadAttempt(pointer);
      setReadResult(null);
      setReadConsent(false);
      inspectReadMutation.reset();
      recoverReadMutation.reset();
    },
  });
  const inspectMutation = useMutation({
    mutationFn: inspectDiscovery,
    onSuccess: (data) => {
      setRunResult(data);
      client.invalidateQueries({ queryKey: ["jobs"] });
      try {
        if (
          paidDiscoverySource(data.source) &&
          data.original_scope_available === true &&
          (readDiscoveryReadAttempt() ||
            typeof data.usage.last_read_request_id === "string")
        )
          inspectReadMutation.mutate();
      } catch (error) {
        setAttemptError(error);
      }
    },
  });

  const requestPending =
    !attemptLoaded ||
    previewMutation.isPending ||
    executeMutation.isPending ||
    inspectMutation.isPending ||
    inspectReadMutation.isPending ||
    recoverReadMutation.isPending ||
    nextReadMutation.isPending;
  const savedAdmissionMissing =
    inspectMutation.error instanceof ApiError &&
    inspectMutation.error.status === 404;
  const criteriaLocked =
    Boolean(attempt && !savedAdmissionMissing) ||
    Boolean(!attempt && readAttempt);
  const terminalReviewed =
    runResult?.local_intake_complete === true &&
    runResult.rankings_complete === true &&
    Boolean(runResult.finished_at);
  useEffect(() => {
    try {
      const saved = readDiscoveryAttempt();
      const savedRead = readDiscoveryReadAttempt();
      setReadAttempt(savedRead);
      setAttempt(saved);
      if (saved) {
        setSelectedSource(saved.source);
        inspectMutation.mutate();
      } else if (savedRead) {
        inspectReadMutation.mutate();
      }
    } catch (error) {
      setAttemptError(error);
    }
    setAttemptLoaded(true);
    // Mount performs a saved GET only. New dispatch requires its own explicit action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCriteriaChange = (clearPaid = true) => {
    if (clearPaid) setAllowPaid(false);
    if (!attempt) inspectMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
    setConsentConfirmed(false);
    setRunResult(null);
    setIdempotencyKey("");
  };

  const handlePreview = () => {
    if (manualSource && !listingReady) return;
    const key = idempotencyKey || generateIdempotencyKey();
    if (!idempotencyKey) {
      setIdempotencyKey(key);
    }
    setConsentConfirmed(false);
    setRunResult(null);
    previewMutation.mutate(key);
  };

  const handleExecute = () => {
    if (
      !idempotencyKey ||
      !consentConfirmed ||
      (manualSource && !listingReady) ||
      (manualSource &&
        previewMutation.data?.manual_import?.valid_records !== 1) ||
      (paidSource &&
        (!allowPaid || previewMutation.data?.paid_execution?.ready !== true))
    )
      return;
    executeMutation.mutate(true);
  };

  const handleRetry = () => {
    executeMutation.mutate(false);
  };

  const handleReset = async () => {
    try {
      if (!attempt && readAttempt)
        throw new Error(
          "Recover the linked original search before clearing its saved read.",
        );
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
    setReadAttempt(null);
    setReadResult(null);
    setReadConsent(false);
    inspectReadMutation.reset();
    recoverReadMutation.reset();
    nextReadMutation.reset();
    setAttemptError(null);
    inspectMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
    setConsentConfirmed(false);
    setRunResult(null);
    setIdempotencyKey("");
    setAllowPaid(false);
    setListing({ url: "", title: "", employer: "", employerUrl: "" });
  };

  const isCurrentSourceAvailable = sourceAvailable(currentSourceConfig);
  const nativePaid = Boolean(
    runResult?.original_scope_available === true &&
    paidDiscoverySource(runResult.source),
  );
  const acknowledged = Boolean(
    runResult &&
    typeof runResult.provider_run_id === "string" &&
    /^[A-Za-z0-9_-]{1,100}$/.test(runResult.provider_run_id),
  );
  const needsRead =
    nativePaid &&
    !terminalReviewed &&
    runResult?.usage.finding_retained !== true;
  const nextReadAt =
    typeof runResult?.usage.read_next_allowed_at === "string"
      ? runResult.usage.read_next_allowed_at
      : null;
  const mayPrepareNext = Boolean(
    readResult &&
    !readResult.finding_retained &&
    !readResult.local_merge_available &&
    readResult.expires_at &&
    Date.parse(readResult.expires_at) <= Date.now() &&
    nextReadAt &&
    Number.isFinite(Date.parse(nextReadAt)) &&
    Date.parse(nextReadAt) <= Date.now() &&
    typeof runResult?.usage.read_rounds_admitted === "number" &&
    runResult.usage.read_rounds_admitted < 3,
  );

  return (
    <div className="detail-grid">
      <section className="panel" aria-label="Job discovery controls">
        <div className="panel-header">
          <h2>Job discovery</h2>
          <Briefcase size={19} className="muted" />
        </div>
        <div className="panel-body stack">
          <p className="muted">
            Search public job feeds and configured paid providers. Preview the
            search plan first, then explicitly run discovery to ingest listings.
          </p>
          {attemptError != null && <ErrorState error={attemptError} />}
          {inspectReadMutation.isError && (
            <ErrorState error={inspectReadMutation.error} />
          )}
          {recoverReadMutation.isError && (
            <ErrorState error={recoverReadMutation.error} />
          )}
          {nextReadMutation.isError && (
            <ErrorState error={nextReadMutation.error} />
          )}
          {readAttempt && !runResult && (
            <Notice>
              A saved read is retained with its original search.
              <Button
                disabled={requestPending}
                onClick={() => inspectReadMutation.mutate()}
              >
                Refresh saved read
              </Button>
            </Notice>
          )}
          {attempt && (
            <Notice>
              A saved search is retained for recovery. Refresh and review its
              result before preparing another search.
              <Button
                disabled={requestPending}
                onClick={() => inspectMutation.mutate()}
              >
                Recover saved discovery
              </Button>
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
                hint="Public feeds and reviewed paid sources are selectable when ready."
              >
                <Select
                  aria-label="Discovery source provider"
                  disabled={
                    requestPending || Boolean(attempt) || Boolean(readAttempt)
                  }
                  value={selectedSource}
                  onChange={(e) => {
                    setSelectedSource(e.target.value);
                    handleCriteriaChange();
                  }}
                >
                  <optgroup label="Available Free Providers">
                    {allSources
                      .filter(
                        (s) =>
                          sourceAvailable(s) && s.adapter_type === "direct_api",
                      )
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.display_name} (Free · Available)
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="Import a saved listing">
                    {allSources.filter(manualImportAvailable).map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.display_name}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Reviewed paid providers">
                    {allSources
                      .filter(
                        (s) => sourceAvailable(s) && s.adapter_type === "apify",
                      )
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.display_name} (Paid · Reviewed)
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
                  <optgroup label="Paid providers requiring setup">
                    {allSources
                      .filter(
                        (s) =>
                          (s.pricing !== "free" ||
                            s.adapter_type === "apify") &&
                          !sourceAvailable(s),
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
                  <Badge>
                    {manualSource
                      ? "Owner-supplied listing"
                      : "Read-only discovery"}
                  </Badge>
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

              {manualSource && (
                <div className="stack">
                  {selectedSource === "hiringcafe" && (
                    <a
                      href="https://hiringcafe.com/jobs"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Browse HiringCafe listings
                    </a>
                  )}
                  <Field
                    label="Listing URL"
                    hint="Use the HTTPS address of the job listing you reviewed."
                  >
                    <Input
                      aria-label="Listing URL"
                      type="url"
                      value={listing.url}
                      maxLength={2048}
                      disabled={requestPending || criteriaLocked}
                      onChange={(event) => {
                        setListing({ ...listing, url: event.target.value });
                        handleCriteriaChange();
                      }}
                    />
                  </Field>
                  <Field label="Listing title">
                    <Input
                      aria-label="Listing title"
                      value={listing.title}
                      maxLength={255}
                      disabled={requestPending || criteriaLocked}
                      onChange={(event) => {
                        setListing({ ...listing, title: event.target.value });
                        handleCriteriaChange();
                      }}
                    />
                  </Field>
                  <Field label="Employer (optional)">
                    <Input
                      aria-label="Employer"
                      value={listing.employer}
                      maxLength={255}
                      disabled={requestPending || criteriaLocked}
                      onChange={(event) => {
                        setListing({
                          ...listing,
                          employer: event.target.value,
                        });
                        handleCriteriaChange();
                      }}
                    />
                  </Field>
                  {selectedSource === "hiringcafe" && (
                    <Field
                      label="Employer application URL (optional)"
                      hint="Use the link for this role from Greenhouse, Lever, Ashby or SmartRecruiters."
                    >
                      <Input
                        aria-label="Employer application URL"
                        type="url"
                        value={listing.employerUrl}
                        maxLength={2048}
                        disabled={requestPending || criteriaLocked}
                        onChange={(event) => {
                          setListing({
                            ...listing,
                            employerUrl: event.target.value,
                          });
                          handleCriteriaChange();
                        }}
                      />
                    </Field>
                  )}
                </div>
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

              {paidSource && (
                <label className="check-label">
                  <input
                    type="checkbox"
                    aria-label="Allow this paid discovery"
                    disabled={requestPending || criteriaLocked}
                    checked={allowPaid}
                    onChange={(e) => {
                      handleCriteriaChange(false);
                      setAllowPaid(e.target.checked);
                    }}
                  />
                  Authorize this paid discovery using the saved run and monthly
                  limits.
                  {paidPlan(currentSourceConfig)?.run_cap_usd && (
                    <span>
                      {" "}
                      Run cap: ${paidPlan(currentSourceConfig)?.run_cap_usd};
                      monthly limit: $
                      {paidPlan(currentSourceConfig)?.monthly_limit_usd}.
                    </span>
                  )}
                </label>
              )}

              <Button
                onClick={handlePreview}
                busy={previewMutation.isPending}
                disabled={
                  !isCurrentSourceAvailable ||
                  (manualSource && !listingReady) ||
                  (paidSource && !allowPaid) ||
                  requestPending ||
                  criteriaLocked ||
                  attemptError != null
                }
              >
                <Search size={14} />
                {manualSource
                  ? "Preview listing import"
                  : "Preview discovery plan"}
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
              {previewMutation.data.manual_import?.rejected_records ? (
                <Notice>
                  Check the listing URL and title for this source.
                </Notice>
              ) : null}
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
                    : previewMutation.data.source.pricing === "free"
                      ? "Free ($0.00)"
                      : "Unavailable; review the saved paid limits"}
                </li>
                <li>
                  <strong>Provider calls in preview:</strong>{" "}
                  {previewMutation.data.provider_calls}
                </li>
              </ul>

              {previewMutation.data.paid_execution && (
                <Notice>
                  Run cap: $
                  {previewMutation.data.paid_execution.run_cap_usd ??
                    "unavailable"}
                  ; monthly limit: $
                  {previewMutation.data.paid_execution.monthly_limit_usd ??
                    "unavailable"}
                  .
                  {previewMutation.data.paid_execution.ready !== true && (
                    <span>
                      {" "}
                      Paid discovery is blocked:{" "}
                      {readable(
                        previewMutation.data.paid_execution.blocker ??
                          "configuration required",
                      )}
                      .
                    </span>
                  )}
                  The full cap stays reserved after an uncertain start. Final
                  provider billing is not verified.
                </Notice>
              )}

              <Notice>
                Preview performs no external network calls or database writes.
                {manualSource
                  ? "Imported listings are saved for review."
                  : "Executing discovery calls the upstream provider, extracts job postings, and stores new records locally."}
              </Notice>

              <label className="check-label" htmlFor={consentId}>
                <input
                  id={consentId}
                  type="checkbox"
                  checked={consentConfirmed}
                  onChange={(e) => setConsentConfirmed(e.target.checked)}
                />
                {manualSource ? (
                  "Approve saving this listing."
                ) : (
                  <>
                    Run this approved job discovery on{" "}
                    {previewMutation.data.source.display_name} now.
                  </>
                )}
              </label>

              <div className="actions">
                <Button
                  variant="primary"
                  disabled={
                    !consentConfirmed ||
                    requestPending ||
                    (manualSource &&
                      previewMutation.data.manual_import?.valid_records !==
                        1) ||
                    (paidSource &&
                      (!allowPaid ||
                        previewMutation.data?.paid_execution?.ready !== true))
                  }
                  busy={executeMutation.isPending}
                  onClick={handleExecute}
                >
                  {manualSource
                    ? "Save approved listing"
                    : "Run approved discovery"}
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

              {runResult.reservation && (
                <Notice>
                  Retained reservation: ${runResult.reservation.reserved_usd}.
                  The full cap remains reserved; final provider billing is not
                  verified.
                </Notice>
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
          {(needsRead || readResult) && (
            <div
              className="evidence-item stack"
              aria-label="Acknowledged run read recovery"
            >
              <strong>Read recovery</strong>
              {readResult && (
                <Notice>
                  Read round {readResult.round}/3: {readable(readResult.status)}
                  . Observed requests: {readResult.http_attempts}; responses:{" "}
                  {readResult.http_responses}.
                  {readResult.http_counts_are_minimum &&
                    " These are minimum counts; the last read outcome is uncertain."}
                  {readResult.provider_status && (
                    <span>
                      {" "}
                      Provider status: {readable(readResult.provider_status)}.
                    </span>
                  )}
                </Notice>
              )}
              {needsRead && !acknowledged && (
                <Notice>
                  The original paid start has no acknowledged run. Its full
                  reservation stays held; another start is not authorized
                  through recovery.
                </Notice>
              )}
              {needsRead && acknowledged && (
                <>
                  <p className="muted">
                    Read the original acknowledged run without starting or
                    aborting an actor. Each of three read rounds permits up to
                    four requests within 45 seconds, with five minutes between
                    rounds.
                  </p>
                  <Button
                    disabled={requestPending}
                    onClick={() => inspectReadMutation.mutate()}
                  >
                    Refresh saved read
                  </Button>
                  {!readResult && (
                    <>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          aria-label="Allow bounded acknowledged run read"
                          checked={readConsent}
                          disabled={
                            requestPending ||
                            paidPlan(currentSourceConfig)?.ready !== true
                          }
                          onChange={(event) =>
                            setReadConsent(event.target.checked)
                          }
                        />
                        Allow a bounded read of this acknowledged run.
                      </label>
                      <Button
                        disabled={
                          requestPending ||
                          !readConsent ||
                          paidPlan(currentSourceConfig)?.ready !== true
                        }
                        onClick={() => recoverReadMutation.mutate(true)}
                      >
                        Read acknowledged run
                      </Button>
                    </>
                  )}
                  {readResult &&
                    !readResult.local_merge_available &&
                    !readResult.finding_retained && (
                      <>
                        {nextReadAt &&
                          Number.isFinite(Date.parse(nextReadAt)) && (
                            <p className="muted">
                              Next read can be prepared after{" "}
                              {new Date(nextReadAt).toLocaleString()} when
                              allowance remains.
                            </p>
                          )}
                        <Button
                          disabled={requestPending || !mayPrepareNext}
                          onClick={() =>
                            nextReadMutation.mutate(readResult.read_request_id)
                          }
                        >
                          Review result and prepare next read
                        </Button>
                      </>
                    )}
                </>
              )}
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
            <h3>Paid discovery limits</h3>
            <p>
              Paid sources require a configured token, reviewed actor and build,
              saved spending limits and explicit opt-in. An uncertain start
              keeps its reservation and cannot be started again through
              recovery.
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
