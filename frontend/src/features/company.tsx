"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, MapPin, Users } from "lucide-react";
import { api, dateLabel, readable } from "@/lib/api";
import {
  Badge,
  Empty,
  ErrorState,
  External,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import type { Startup } from "./startups";
import { JobTable, type Job } from "./jobs";
import { CompanyPeople } from "./people";
export function CompanyDetail({ id }: { id: string }) {
  const params = useSearchParams(),
    [tab, setTab] = useState(params?.get("tab") || "evidence");
  const company = useQuery({
    queryKey: ["company", id],
    queryFn: () => api<Startup>(`startups/${id}`),
  });
  const jobs = useQuery({
    queryKey: ["company-jobs", id],
    queryFn: () => api<{ jobs: Job[] }>(`startups/${id}/jobs`),
  });
  const evidence = useQuery({
    queryKey: ["company-evidence", id],
    queryFn: () =>
      api<{
        observations: Array<{
          id: string;
          source: string;
          source_url: string;
          observed_at: string;
          verification_status: string;
          stale: boolean;
          attributes: Record<string, unknown>;
        }>;
      }>(`startups/${id}/evidence`),
  });
  if (company.isPending) return <Skeleton />;
  if (company.isError) return <ErrorState error={company.error} />;
  const s = company.data;
  return (
    <>
      <Link className="external" href="/startups">
        <ArrowLeft size={13} />
        Back to explorer
      </Link>
      <div className="spaced">
        <PageTitle
          eyebrow="A CLOSER LOOK AT THE TEAM"
          title={s.company_name}
          description={
            s.attributes.description ||
            "Explore saved company, hiring and professional evidence."
          }
          actions={
            <External
              href={s.company_domain ? `https://${s.company_domain}` : null}
            >
              Open official site
            </External>
          }
        />
      </div>
      <div className="metrics">
        <div className="metric">
          <div className="metric-label">
            LOCATION
            <MapPin size={14} />
          </div>
          <p className="spaced">{s.attributes.location || "Unknown"}</p>
        </div>
        <div className="metric">
          <div className="metric-label">
            TEAM SIZE
            <Users size={14} />
          </div>
          <p className="spaced">
            {s.employee_count !== null &&
            ["source_reported", "human_confirmed"].includes(
              s.team_size_evidence_status,
            )
              ? `${s.employee_count} employees (${s.team_size_evidence_status === "human_confirmed" ? "human confirmed" : "source reported"})`
              : s.team_size_band && s.team_size_band !== "unknown"
                ? `${s.team_size_band} band`
                : "Size unknown"}
          </p>
          <small>Status: {readable(s.team_size_evidence_status)}</small>
        </div>
        <div className="metric">
          <div className="metric-label">
            CURRENT ROLES
            <Building2 size={14} />
          </div>
          <strong>{s.current_job_count}</strong>
          <small>{readable(s.hiring_status)}</small>
        </div>
        <div className="metric">
          <div className="metric-label">MATCH SCORE</div>
          <strong>{Math.round(s.startup_match_score)}</strong>
          <small>Evidence-based startup ranking</small>
        </div>
      </div>
      <div className="status-tabs">
        {[
          ["evidence", "Company & evidence"],
          ["jobs", "Open roles"],
          ["people", "Founders & contacts"],
        ].map(([key, label]) => (
          <button
            className={tab === key ? "selected" : ""}
            key={key}
            onClick={() => setTab(key)}
            aria-pressed={tab === key}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "jobs" ? (
        jobs.isPending ? (
          <Skeleton />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} />
        ) : jobs.data.jobs.length ? (
          <JobTable
            jobs={jobs.data.jobs.map((j) => ({
              ...j,
              company_name: s.company_name,
            }))}
          />
        ) : (
          <Empty
            title="No retained roles"
            description="The absence of saved jobs does not establish that this company is not hiring."
          />
        )
      ) : tab === "people" ? (
        <CompanyPeople companyId={id} />
      ) : (
        <div className="detail-grid">
          <section className="panel">
            <div className="panel-header">
              <h2>Source observations</h2>
              <Badge>PROVENANCE</Badge>
            </div>
            <div className="panel-body">
              {evidence.isPending ? (
                <Skeleton />
              ) : evidence.isError ? (
                <ErrorState error={evidence.error} />
              ) : evidence.data.observations.length ? (
                evidence.data.observations.map((o) => (
                  <div className="evidence-item" key={o.id}>
                    <div className="split">
                      <strong>{readable(o.source)}</strong>
                      <Badge tone={o.stale ? "amber" : "green"}>
                        {o.stale ? "Stale" : readable(o.verification_status)}
                      </Badge>
                    </div>
                    <p>Observed {dateLabel(o.observed_at)}</p>
                    <External href={o.source_url}>Inspect source</External>
                    <details className="spaced">
                      <summary>Observed attributes</summary>
                      <pre className="source-text">
                        {JSON.stringify(o.attributes, null, 2)}
                      </pre>
                    </details>
                  </div>
                ))
              ) : (
                <Empty
                  title="Company evidence is incomplete"
                  description="Job-led discovery can identify a company without establishing its team size, location, funding or technology stack."
                />
              )}
            </div>
          </section>
          <aside className="panel">
            <div className="panel-header">
              <h2>What the evidence says</h2>
            </div>
            <div className="panel-body stack">
              <div className="tag-list">
                {(s.attributes.technology_stack || []).map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
              </div>
              <div className="detail-section">
                <h3>Matching roles</h3>
                <p>{`${s.matching_roles} matching open roles`}</p>
              </div>
              <div className="detail-section">
                <h3>Hiring signals</h3>
                {s.hiring_evidence.map((e, i) => (
                  <div className="evidence-item" key={`${e.job_id}-${i}`}>
                    <strong>{e.title}</strong>
                    <p>
                      {e.fresh ? "Recent evidence" : "Stale evidence"} ·{" "}
                      {dateLabel(e.observed_at)}
                    </p>
                    <External href={e.evidence_url}>Job source</External>
                  </div>
                ))}
              </div>
              <div className="detail-section">
                <h3>Missing information</h3>
                <ul>
                  {(s.missing_information || []).map((m) => (
                    <li key={m}>{readable(m)}</li>
                  ))}
                </ul>
              </div>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
