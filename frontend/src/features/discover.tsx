"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Compass, Search } from "lucide-react";
import { api, post, readable } from "@/lib/api";
import { Automation } from "@/features/automation";
import { JobDiscovery } from "@/features/job-discovery";
import { SearchPreferencesEditor } from "@/features/search-preferences";
import { ApifySourceManagement } from "@/features/apify-sources";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";

type Source = {
  provider: string;
  modes: string[];
  availability: string;
  configured: boolean;
  authorized: boolean;
  pricing: string;
  minimum_interval_seconds?: number;
};

type Preview = {
  source: Source;
  effective_roles: string[];
  effective_locations: string[];
  provider_calls: number;
  message: string;
};

type Run = {
  id: string;
  status: string;
  errors: string[];
  counts: Record<string, number>;
};

export function Discover() {
  const [tab, setTab] = useState<"jobs" | "startups" | "apify">("jobs");

  // Preserved startup discovery state & logic
  const client = useQueryClient();
  const [source, setSource] = useState("hacker_news");
  const [keywords, setKeywords] = useState("");
  const [locations, setLocations] = useState("");
  const [consent, setConsent] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [key, setKey] = useState("");

  const sources = useQuery({
    queryKey: ["startup-sources"],
    queryFn: () => api<{ sources: Source[] }>("startups/sources"),
  });

  const body = {
    source,
    mode: "job_led",
    idempotency_key: key || "preview_only",
    query: {
      keywords: keywords
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      locations: locations
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      limit: 20,
    },
    filters: { use_profile: false, max_employees: null },
    permission_confirmed: consent,
    allow_paid: false,
  };

  const preview = useMutation({
    mutationFn: () => post<Preview>("startups/discovery/preview", body),
  });

  const execute = useMutation({
    mutationFn: () => post<Run>("startups/discovery/runs", body),
    onSuccess: (r) => {
      setRun(r);
      setConsent(false);
      setKey("");
      client.invalidateQueries({ queryKey: ["startups"] });
      client.invalidateQueries({ queryKey: ["jobs"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const current = sources.data?.sources.find((s) => s.provider === source);

  return (
    <>
      <PageTitle
        eyebrow="DISCOVER WITH INTENTION"
        title="A fresh set of possibilities."
        description="Run a bounded search using an approved public API. Preview first, then choose to proceed."
      />
      <SearchPreferencesEditor />

      <div
        className="status-tabs"
        aria-label="Discovery workflow"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          id="tab-job-discovery"
          aria-controls="panel-job-discovery"
          aria-selected={tab === "jobs"}
          className={tab === "jobs" ? "selected" : ""}
          onClick={() => setTab("jobs")}
        >
          Job discovery
        </button>
        <button
          type="button"
          role="tab"
          id="tab-startup-discovery"
          aria-controls="panel-startup-discovery"
          aria-selected={tab === "startups"}
          className={tab === "startups" ? "selected" : ""}
          onClick={() => setTab("startups")}
        >
          Startup discovery
        </button>
        <button
          type="button"
          role="tab"
          id="tab-apify-sources"
          aria-controls="panel-apify-sources"
          aria-selected={tab === "apify"}
          className={tab === "apify" ? "selected" : ""}
          onClick={() => setTab("apify")}
        >
          Apify & sources
        </button>
      </div>

      {tab === "jobs" ? (
        <div
          id="panel-job-discovery"
          role="tabpanel"
          aria-labelledby="tab-job-discovery"
        >
          <JobDiscovery />
        </div>
      ) : tab === "startups" ? (
        <div
          id="panel-startup-discovery"
          role="tabpanel"
          aria-labelledby="tab-startup-discovery"
        >
          <div className="detail-grid">
            <section className="panel">
              <div className="panel-header">
                <h2>Public-source discovery</h2>
                <Compass size={19} className="muted" />
              </div>
              <div className="panel-body stack">
                {sources.isPending ? (
                  <Skeleton />
                ) : sources.isError ? (
                  <ErrorState error={sources.error} />
                ) : (
                  <>
                    <Field label="Source">
                      <Select
                        value={source}
                        onChange={(e) => {
                          setSource(e.target.value);
                          preview.reset();
                          setConsent(false);
                        }}
                      >
                        {sources.data.sources
                          .filter(
                            (s) =>
                              s.pricing === "free" &&
                              s.modes.includes("job_led"),
                          )
                          .map((s) => (
                            <option key={s.provider} value={s.provider}>
                              {readable(s.provider)} ·{" "}
                              {readable(s.availability)}
                            </option>
                          ))}
                      </Select>
                    </Field>
                    <Field
                      label="Titles / technologies"
                      hint="Comma-separated. Public APIs may return limited geographic coverage."
                    >
                      <Input
                        value={keywords}
                        onChange={(e) => {
                          setKeywords(e.target.value);
                          preview.reset();
                          setConsent(false);
                        }}
                        placeholder="Python, Backend Engineer"
                      />
                    </Field>
                    <Field label="Locations">
                      <Input
                        value={locations}
                        onChange={(e) => {
                          setLocations(e.target.value);
                          preview.reset();
                          setConsent(false);
                        }}
                        placeholder="India, Bengaluru"
                      />
                    </Field>
                    <div className="tag-list">
                      <Badge tone="green">Public API</Badge>
                      <Badge>Maximum 20 results</Badge>
                      <Badge>No paid execution</Badge>
                      <Badge>
                        Minimum interval{" "}
                        {current?.minimum_interval_seconds || "—"}s
                      </Badge>
                    </div>
                    <Button
                      onClick={() => {
                        setKey(crypto.randomUUID());
                        preview.mutate();
                      }}
                      busy={preview.isPending}
                    >
                      <Search size={14} />
                      Preview discovery plan
                    </Button>
                  </>
                )}
                {preview.isError && <ErrorState error={preview.error} />}
                {preview.data && (
                  <div className="evidence-item">
                    <strong>Review your discovery plan</strong>
                    <p>{preview.data.message}</p>
                    <p>
                      Source: {readable(source)} · configured:{" "}
                      {String(current?.configured)} · public access authorized:{" "}
                      {String(current?.authorized)}
                    </p>
                    <p>
                      Keywords: {keywords || "Source defaults"} · Locations:{" "}
                      {locations || "Any"}
                    </p>
                    <Notice>
                      Preview performs no provider calls. Execution respects the
                      existing source interval, budget and permissions. Public
                      feeds do not promise India-only or complete coverage.
                    </Notice>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={consent}
                        onChange={(e) => setConsent(e.target.checked)}
                      />
                      Run this bounded public-source search now.
                    </label>
                    <Button
                      variant="primary"
                      className="spaced"
                      disabled={
                        !consent || !current?.configured || !current?.authorized
                      }
                      busy={execute.isPending}
                      onClick={() => execute.mutate()}
                    >
                      Run approved discovery
                      <ArrowUpRight size={14} />
                    </Button>
                  </div>
                )}
                {execute.isError && <ErrorState error={execute.error} />}
                {run && (
                  <Notice>
                    <strong>Run result: {readable(run.status)}</strong>
                    <p>
                      {Object.entries(run.counts || {})
                        .map(([k, v]) => `${readable(k)}: ${v}`)
                        .join(" · ")}
                    </p>
                    {run.errors?.map((e) => (
                      <p key={e}>{e}</p>
                    ))}
                    <Link className="external" href="/startups">
                      Review saved results
                      <ArrowUpRight size={13} />
                    </Link>
                  </Notice>
                )}
              </div>
            </section>
            <aside className="panel">
              <div className="panel-header">
                <h2>Clear boundaries</h2>
              </div>
              <div className="panel-body stack">
                <div className="detail-section">
                  <h3>Saved searches are free of provider calls</h3>
                  <p>
                    Changing filters queries saved data. Fresh discovery is a
                    separate, explicit action.
                  </p>
                </div>
                <div className="detail-section">
                  <h3>India + a small team</h3>
                  <p>
                    Company size and location need independent evidence. A job
                    feed alone may not establish either. Unknown sizes remain
                    labeled.
                  </p>
                </div>
                <div className="detail-section">
                  <h3>Paid sources stay gated</h3>
                  <p>
                    Apify, Serper, Apollo and SignalHire require credentials,
                    rights review, account-specific budgets and separate
                    consent.
                  </p>
                  <div className="spaced">
                    <Link className="external" href="/connections">
                      Review account readiness
                      <ArrowUpRight size={13} />
                    </Link>
                  </div>
                </div>
              </div>
            </aside>
          </div>
        </div>
      ) : (
        <div
          id="panel-apify-sources"
          role="tabpanel"
          aria-labelledby="tab-apify-sources"
        >
          <ApifySourceManagement />
        </div>
      )}

      <Automation />
    </>
  );
}
