"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowUpRight,
  Bookmark,
  Building2,
  CheckCircle2,
  Clock,
  ExternalLink,
  Eye,
  FileCheck2,
  FilePlus2,
  Filter,
  Info,
  MapPin,
  RefreshCw,
  Search,
  Shield,
  ShieldCheck,
  SlidersHorizontal,
  X,
  XCircle,
} from "lucide-react";
import { api, dateLabel, patch, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Field,
  Input,
  Modal,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";

export type SourceMetadata = {
  id: string;
  display_name?: string | null;
  adapter_type?: string | null;
  availability?: string | null;
  pricing?: string | null;
  enabled?: boolean | null;
  read_only?: boolean | null;
  live_verified?: boolean | null;
};

export const FALLBACK_SOURCE_OPTIONS = [
  { id: "simplify_jobs", label: "Simplify Jobs" },
  { id: "lever", label: "Lever" },
  { id: "ashby", label: "Ashby" },
  { id: "greenhouse", label: "Greenhouse" },
  { id: "smartrecruiters", label: "SmartRecruiters" },
  { id: "workday", label: "Workday" },
  { id: "gmail_alert", label: "Gmail Job Alerts" },
  { id: "arbeitnow", label: "Arbeitnow" },
  { id: "remotive", label: "Remotive" },
  { id: "hacker_news", label: "Hacker News" },
] as const;

export function getSourceDetails(
  sourceId: string,
  metadata?: SourceMetadata[],
): {
  displayName: string;
  adapterType: string;
  availability: string;
  readOnly: boolean;
  liveVerified: boolean;
  pricing: string;
} {
  const meta = metadata?.find((m) => m.id === sourceId);
  if (meta) {
    return {
      displayName: meta.display_name || readable(sourceId),
      adapterType: meta.adapter_type || "direct_api",
      availability: meta.availability || "available",
      readOnly: meta.read_only !== false,
      liveVerified: meta.live_verified === true,
      pricing: meta.pricing || "free",
    };
  }
  if (sourceId === "simplify_jobs") {
    return {
      displayName: "Simplify Jobs",
      adapterType: "manual",
      availability: "authorized_integration_required",
      readOnly: true,
      liveVerified: false,
      pricing: "free",
    };
  }
  if (sourceId === "gmail_alert") {
    return {
      displayName: "Gmail Job Alerts",
      adapterType: "gmail",
      availability: "available",
      readOnly: true,
      liveVerified: true,
      pricing: "free",
    };
  }
  if (sourceId === "workday") {
    return {
      displayName: "Workday",
      adapterType: "manual",
      availability: "manual_import_only",
      readOnly: true,
      liveVerified: false,
      pricing: "free",
    };
  }
  const verifiedList = [
    "lever",
    "ashby",
    "greenhouse",
    "arbeitnow",
    "smartrecruiters",
  ];
  return {
    displayName: readable(sourceId),
    adapterType: "direct_api",
    availability: "available",
    readOnly: true,
    liveVerified: verifiedList.includes(sourceId),
    pricing: "free",
  };
}

export type Job = Schema<"JobRead"> & {
  company_name?: string | null;
  company_domain?: string | null;
  company_intelligence?: {
    employee_count?: number | null;
    team_size_band?: string | null;
    team_size?: string | number | null;
    headcount?: string | number | null;
    industry?: string | null;
    stage?: string | null;
    has_leader_evidence?: boolean;
    has_technical_staff?: boolean;
    leader_evidence_count?: number;
    technical_staff_count?: number;
    [key: string]: unknown;
  };
  application_url?: string | null;
  application_state?: string | null;
  remote_type?: string | null;
  is_remote?: boolean;
  employment_type?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_period?: string | null;
  salary_range?: string | null;
  application_deadline?: string | null;
  experience_level?: string | null;
  match?: {
    match_score: number;
    matched_skills?: string[];
    missing_skills: string[];
    match_reasons?: string[];
    positive_factors?: string[];
    negative_factors?: string[];
    exclusion_reasons?: string[];
    explanation?: string;
  } | null;
  recommended_resume?: {
    resource_id?: string;
    label?: string;
    reason?: string;
    confirmed?: boolean;
  } | null;
  readiness_status?: {
    state?: string;
    blockers?: string[];
    warnings?: string[];
    destination_valid?: boolean;
  } | null;
  date_posted?: string | null;
  first_observed_at?: string | null;
  last_observed_at?: string | null;
  source_verification_status?: string | null;
  country?: string | null;
  region?: string | null;
  skills_preferred?: string[];
  source_observations?: Array<{
    source: string;
    source_job_id: string;
    original_url: string;
    verification_status: string;
    first_observed_at: string;
    last_observed_at: string;
  }>;
};

export const jobStatuses = [
  ["not_applied", "Not Applied"],
  ["matched", "Matched Jobs"],
  ["new_jobs", "New Jobs"],
  ["shortlisted", "Shortlisted"],
  ["packet_prepared", "Packet Prepared"],
  ["applied", "Applied"],
  ["interview", "Interview"],
  ["rejected", "Rejected"],
  ["all", "All"],
] as const;

export function PrepareButton({ jobId }: { jobId: string }) {
  const router = useRouter();
  const mutation = useMutation({
    mutationFn: () =>
      post<Schema<"PacketRead">>(`jobs/${jobId}/application-packets`, {
        idempotency_key: `packet_${jobId}`,
        questions: [],
      }),
    onSuccess: (p) => router.push(`/applications/${p.id}`),
  });

  return (
    <>
      <Button
        onClick={() => mutation.mutate()}
        busy={mutation.isPending}
        title="Prepare application packet with verified facts"
      >
        <FilePlus2 size={13} />
        Prepare application
      </Button>
      {mutation.isError && <ErrorState error={mutation.error} />}
    </>
  );
}

export function JobPreviewModal({
  job,
  open,
  onClose,
  onShortlist,
  onReject,
  shortlistPending,
}: {
  job: Job | null;
  open: boolean;
  onClose: () => void;
  onShortlist?: (id: string) => void;
  onReject?: (id: string) => void;
  shortlistPending?: boolean;
}) {
  if (!job) return null;

  const teamSize =
    job.company_intelligence?.employee_count ||
    job.company_intelligence?.team_size_band ||
    job.company_intelligence?.team_size ||
    job.company_intelligence?.headcount;

  const matchScore = job.match?.match_score ?? job.match_score;
  const matchTone =
    matchScore !== null && matchScore !== undefined
      ? matchScore >= 75
        ? "green"
        : matchScore >= 50
          ? "amber"
          : "neutral"
      : "neutral";

  const isSubmitted =
    job.application_state === "user_reported_submitted" ||
    job.application_state === "provider_confirmed_submitted" ||
    job.status === "applied";

  return (
    <Modal
      open={open}
      onOpenChange={(isOpen) => !isOpen && onClose()}
      title={job.title}
      description={`${job.company_name || "Company unverified"} · ${job.location || "Location not disclosed"}`}
    >
      <div
        className="stack spaced"
        style={{ maxHeight: "75vh", overflowY: "auto" }}
      >
        {/* Verification and Non-Submission Alert */}
        <Notice>
          <strong>Non-Submission Notice:</strong> Preparing or previewing this
          opportunity does NOT submit an application. Applications must be
          reviewed and submitted manually on the official employer website.
        </Notice>

        {/* Top Badges & Meta */}
        <div className="tag-list">
          <Badge tone={job.status === "applied" ? "green" : "neutral"}>
            Status: {readable(job.application_state || job.status)}
          </Badge>
          <Badge
            tone={
              job.source_verification_status === "verified"
                ? "green"
                : "neutral"
            }
          >
            Source: {readable(job.source_platform)} (
            {readable(job.source_verification_status || "unverified")})
          </Badge>
          <Badge>
            {job.remote_type && job.remote_type !== "unknown"
              ? readable(job.remote_type)
              : job.is_remote
                ? "Remote"
                : "Workplace unspecified"}
          </Badge>
          {job.country && <Badge tone="neutral">Country: {job.country}</Badge>}
          {job.experience_level && (
            <Badge tone="neutral">
              Seniority: {readable(job.experience_level)}
            </Badge>
          )}
        </div>

        {/* Match Breakdown Card */}
        <div className="panel panel-body stack">
          <div className="split">
            <h4>Candidate Match Analysis</h4>
            {matchScore !== null && matchScore !== undefined ? (
              <span className={`score ${matchTone}`}>
                {Math.round(Number(matchScore))}
                <small>/100 Match</small>
              </span>
            ) : (
              <Badge tone="neutral">Profile match not calculated</Badge>
            )}
          </div>

          {job.match?.explanation && (
            <p className="text-sm">{job.match.explanation}</p>
          )}

          {job.match?.matched_skills && job.match.matched_skills.length > 0 && (
            <div>
              <strong className="text-xs muted">MATCHED SKILLS:</strong>
              <div className="tag-list" style={{ marginTop: "0.25rem" }}>
                {job.match.matched_skills.map((s) => (
                  <Badge key={s} tone="green">
                    ✓ {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {job.match?.missing_skills && job.match.missing_skills.length > 0 && (
            <div>
              <strong className="text-xs muted">
                MISSING REQUIREMENTS / SKILLS:
              </strong>
              <div className="tag-list" style={{ marginTop: "0.25rem" }}>
                {job.match.missing_skills.map((s) => (
                  <Badge key={s} tone="amber">
                    ! {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {(!job.match?.missing_skills ||
            job.match.missing_skills.length === 0) &&
            (!job.match?.matched_skills ||
              job.match.matched_skills.length === 0) &&
            job.skills_required &&
            job.skills_required.length > 0 && (
              <div>
                <strong className="text-xs muted">
                  SPECIFIED REQUIREMENTS:
                </strong>
                <div className="tag-list" style={{ marginTop: "0.25rem" }}>
                  {job.skills_required.map((s) => (
                    <Badge key={s} tone="neutral">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
        </div>

        {/* Resume Recommendation & Application Readiness */}
        <div className="panel panel-body stack">
          <h4>Resume Recommendation & Readiness</h4>
          <div className="split">
            <div>
              <p className="text-sm">
                <strong>Recommended Resume:</strong>{" "}
                {job.recommended_resume?.label || "Primary Engineering Resume"}
              </p>
              <small className="muted">
                {job.recommended_resume?.reason ||
                  "Matches technical competencies and experience profile for this position."}
              </small>
            </div>
            <div>
              <Badge
                tone={
                  job.readiness_status?.state === "ready" ||
                  !job.readiness_status
                    ? "green"
                    : "amber"
                }
              >
                {readable(job.readiness_status?.state || "Ready to prepare")}
              </Badge>
            </div>
          </div>
          {job.application_deadline && (
            <p className="text-xs muted">
              <strong>Application Deadline:</strong>{" "}
              {dateLabel(job.application_deadline)}
            </p>
          )}
        </div>

        {/* Company & Compensation Facts */}
        <div className="panel panel-body stack">
          <h4>Company & Opportunity Details</h4>
          <dl className="grid-2">
            <div>
              <dt>Company Domain</dt>
              <dd>
                {job.company_domain ? (
                  <External href={`https://${job.company_domain}`}>
                    {job.company_domain}
                  </External>
                ) : (
                  <span className="muted">Not recorded</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Team Size / Headcount</dt>
              <dd>
                {teamSize ? (
                  `${teamSize} ${typeof teamSize === "number" ? "employees" : ""}`
                ) : (
                  <span className="muted">Unknown headcount</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Published Compensation</dt>
              <dd>
                {job.salary_min != null || job.salary_max != null ? (
                  <span>
                    {job.salary_currency || "Currency unspecified"}{" "}
                    {job.salary_min == null ? "Up to " : ""}
                    {job.salary_min?.toLocaleString()}
                    {job.salary_max != null
                      ? `${job.salary_min != null ? "–" : ""}${job.salary_max.toLocaleString()}`
                      : ""}
                    {job.salary_period ? ` / ${job.salary_period}` : ""}
                  </span>
                ) : job.salary_range ? (
                  <span>{job.salary_range}</span>
                ) : (
                  <span className="muted">Compensation not disclosed</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Timestamps</dt>
              <dd className="text-xs">
                {job.date_posted && (
                  <div>Posted: {dateLabel(job.date_posted)}</div>
                )}
                <div>
                  Observed:{" "}
                  {dateLabel(job.last_observed_at || job.first_observed_at)}
                </div>
              </dd>
            </div>
          </dl>
        </div>

        {/* Full Job Description */}
        <div className="panel panel-body stack">
          <h4>Job Description Preview</h4>
          {job.description || (job as any).description_text ? (
            <div
              className="text-sm description-content"
              style={{
                whiteSpace: "pre-wrap",
                lineHeight: "1.6",
                maxHeight: "260px",
                overflowY: "auto",
                background: "var(--surface-sunken, rgba(0,0,0,0.03))",
                padding: "0.75rem",
                borderRadius: "4px",
              }}
            >
              {job.description || (job as any).description_text}
            </div>
          ) : (
            <p className="muted text-sm">
              Full formatted description not pre-cached. Inspect the official
              job posting below for full requirements and employer notes.
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="actions split">
          <div className="actions">
            <PrepareButton jobId={job.id} />
            {onShortlist && (
              <Button
                disabled={job.status === "shortlisted" || shortlistPending}
                onClick={() => onShortlist(job.id)}
              >
                <Bookmark size={13} />
                {job.status === "shortlisted" ? "Shortlisted" : "Shortlist"}
              </Button>
            )}
            {onReject && job.status !== "rejected" && (
              <Button
                variant="ghost"
                onClick={() => onReject(job.id)}
                title="Mark this opportunity as rejected"
              >
                <XCircle size={13} />
                Reject
              </Button>
            )}
          </div>
          <div className="actions">
            <External
              href={job.application_url || job.job_url}
              className="button"
              aria-label={`Open official application site for ${job.title}`}
            >
              Open application site
              <ExternalLink size={13} />
            </External>
          </div>
        </div>
      </div>
    </Modal>
  );
}

export function JobTable({
  jobs,
  onPreview,
  onReject,
}: {
  jobs: Job[];
  onPreview?: (job: Job) => void;
  onReject?: (id: string) => void;
}) {
  const client = useQueryClient();
  const shortlist = useMutation({
    mutationFn: (id: string) => post(`dashboard/jobs/${id}/shortlist`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const helper = createColumnHelper<Job>();
  const columns = [
    helper.accessor("title", {
      header: "OPPORTUNITY",
      cell: (info) => {
        const teamSize =
          (info.row.original.company_intelligence?.employee_count as
            number | undefined) ||
          (info.row.original.company_intelligence?.team_size_band !== "unknown"
            ? (info.row.original.company_intelligence?.team_size_band as
                string | undefined)
            : undefined) ||
          (info.row.original.company_intelligence?.team_size as
            string | number | undefined) ||
          (info.row.original.company_intelligence?.headcount as
            string | number | undefined);

        return (
          <div className="stack">
            <button
              className="text-left font-bold hover:underline cursor-pointer bg-transparent border-0 p-0 text-inherit"
              style={{
                textAlign: "left",
                cursor: "pointer",
                fontSize: "0.95rem",
              }}
              onClick={() => onPreview?.(info.row.original)}
              title="Click to preview job details and candidate match"
            >
              <strong>{info.getValue()}</strong>
            </button>
            <small>
              {info.row.original.company_name || (
                <span className="muted">Company evidence not available</span>
              )}
            </small>
            <small>
              {teamSize ? (
                `Team size: ${teamSize}`
              ) : (
                <span className="muted">Team size: Unknown</span>
              )}
            </small>
            <small>
              {info.row.original.skills_required?.length ? (
                info.row.original.skills_required.slice(0, 5).join(" · ")
              ) : (
                <span className="muted">Skills not specified</span>
              )}
            </small>
            {info.row.original.salary_min != null ||
            info.row.original.salary_max != null ? (
              <small>
                {info.row.original.salary_currency || "Currency unspecified"}{" "}
                {info.row.original.salary_min == null ? "Up to " : ""}
                {info.row.original.salary_min?.toLocaleString()}
                {info.row.original.salary_max != null
                  ? `${info.row.original.salary_min != null ? "–" : ""}${info.row.original.salary_max.toLocaleString()}`
                  : ""}
                {info.row.original.salary_period
                  ? ` / ${info.row.original.salary_period}`
                  : ""}
              </small>
            ) : info.row.original.salary_range ? (
              <small>{info.row.original.salary_range}</small>
            ) : (
              <small className="muted">Salary: Not disclosed</small>
            )}
            {!!info.row.original.match?.missing_skills?.length && (
              <small className="missing-skills">
                Missing skills:{" "}
                {info.row.original.match.missing_skills.join(", ")}
              </small>
            )}
          </div>
        );
      },
    }),
    helper.accessor("location", {
      header: "LOCATION & WORKPLACE",
      cell: (info) => (
        <div className="stack">
          <span>{info.getValue() || "Location unknown"}</span>
          <small>
            {info.row.original.remote_type &&
            info.row.original.remote_type !== "unknown"
              ? readable(info.row.original.remote_type)
              : info.row.original.is_remote
                ? "Remote"
                : "Remote status unknown"}
          </small>
          {info.row.original.country && (
            <small>{info.row.original.country}</small>
          )}
        </div>
      ),
    }),
    helper.display({
      id: "match",
      header: "MATCH",
      cell: (info) => {
        const score =
          info.row.original.match?.match_score ?? info.row.original.match_score;
        return score !== null && score !== undefined ? (
          <span className="score">
            {Math.round(Number(score))}
            <small>/100</small>
          </span>
        ) : (
          <Badge tone="neutral">Profile needed</Badge>
        );
      },
    }),
    helper.accessor("source_platform", {
      header: "SOURCE & DATES",
      cell: (info) => (
        <div className="stack">
          <span>{readable(info.getValue())}</span>
          {info.row.original.source_verification_status && (
            <div>
              <Badge
                tone={
                  info.row.original.source_verification_status === "verified"
                    ? "green"
                    : "neutral"
                }
              >
                {readable(info.row.original.source_verification_status)}
              </Badge>
            </div>
          )}
          <small>
            {info.row.original.date_posted
              ? `Published ${dateLabel(info.row.original.date_posted)}`
              : "Published date unknown"}
          </small>
          <small>
            {info.row.original.last_observed_at
              ? `Observed ${dateLabel(info.row.original.last_observed_at)}`
              : "Observation date unknown"}
          </small>
          <small>
            Status:{" "}
            {readable(
              info.row.original.application_state || info.row.original.status,
            )}
          </small>
        </div>
      ),
    }),
    helper.display({
      id: "actions",
      header: "NEXT STEP",
      cell: (info) => {
        const isSubmitted =
          info.row.original.application_state === "user_reported_submitted" ||
          info.row.original.application_state ===
            "provider_confirmed_submitted" ||
          info.row.original.status === "applied";

        return (
          <div className="actions">
            {isSubmitted && (
              <Badge
                tone={
                  info.row.original.application_state ===
                  "provider_confirmed_submitted"
                    ? "green"
                    : "amber"
                }
              >
                {info.row.original.application_state ===
                "provider_confirmed_submitted"
                  ? "Submission confirmed"
                  : info.row.original.application_state ===
                      "user_reported_submitted"
                    ? "Submission reported by owner"
                    : "Marked applied"}
              </Badge>
            )}
            <Button
              variant="secondary"
              className="text-xs"
              onClick={() => onPreview?.(info.row.original)}
              title="Preview job requirements and candidate match"
            >
              <Eye size={12} />
              Preview
            </Button>
            <PrepareButton jobId={info.row.original.id} />
            <Button
              aria-label={`Shortlist ${info.row.original.title}`}
              disabled={
                info.row.original.status === "shortlisted" ||
                shortlist.isPending
              }
              onClick={() => shortlist.mutate(info.row.original.id)}
              title={
                info.row.original.status === "shortlisted"
                  ? "Already shortlisted"
                  : "Save to shortlist"
              }
            >
              <Bookmark size={13} />
            </Button>
            {onReject && info.row.original.status !== "rejected" && (
              <Button
                variant="ghost"
                className="text-xs"
                onClick={() => onReject(info.row.original.id)}
                title="Reject this job"
                aria-label={`Reject ${info.row.original.title}`}
              >
                <XCircle size={13} />
              </Button>
            )}
            <External
              href={
                info.row.original.application_url || info.row.original.job_url
              }
              aria-label={`Open application site for ${info.row.original.title}`}
            >
              Open application site
            </External>
            {info.row.original.source_observations?.[0]?.original_url && (
              <External
                href={info.row.original.source_observations[0].original_url}
                className="text-xs"
              >
                {readable(info.row.original.source_observations[0].source)}{" "}
                source
              </External>
            )}
          </div>
        );
      },
    }),
  ];

  const table = useReactTable({
    data: jobs,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      {shortlist.isError && <ErrorState error={shortlist.error} />}
      <div className="table-wrap">
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th key={header.id}>
                    {flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Jobs() {
  const client = useQueryClient();
  const [role, setRole] = useState("");
  const [location, setLocation] = useState("");
  const [skill, setSkill] = useState("");
  const [platform, setPlatform] = useState("");
  const [remoteType, setRemoteType] = useState<string>("");
  const [status, setStatus] = useState("not_applied");
  const [rank, setRank] = useState(false);
  const [country, setCountry] = useState("");
  const [employeeRange, setEmployeeRange] = useState("");
  const [seniority, setSeniority] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [publishedSalaryOnly, setPublishedSalaryOnly] = useState(false);
  const [deadlineOnly, setDeadlineOnly] = useState(false);
  const [freshnessDays, setFreshnessDays] = useState("");
  const [sortBy, setSortBy] = useState<
    "freshness" | "match" | "salary" | "company" | "oldest"
  >("freshness");
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [previewJob, setPreviewJob] = useState<Job | null>(null);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  // Status mapping for backend search query
  const effectiveStatus =
    status === "matched" || status === "new_jobs" ? "all" : status;

  const queryParams = new URLSearchParams();
  if (role.trim()) queryParams.set("role", role.trim());
  if (location.trim()) queryParams.set("location", location.trim());
  if (skill.trim()) queryParams.set("skill", skill.trim());
  if (platform.trim()) queryParams.set("platform", platform.trim());
  if (remoteType) queryParams.set("remote_type", remoteType);
  if (effectiveStatus) queryParams.set("application_status", effectiveStatus);
  if (freshnessDays) queryParams.set("max_age_days", freshnessDays);
  if (status === "new_jobs" && !freshnessDays)
    queryParams.set("max_age_days", "7");

  const effectiveRank = rank || status === "matched";
  queryParams.set("rank", String(effectiveRank));
  queryParams.set("exclude_preferences", "false");
  queryParams.set("page", String(page));
  queryParams.set("limit", String(limit));

  if (sortBy === "match" || status === "matched") {
    queryParams.set("sort", "match");
  } else if (sortBy === "oldest") {
    queryParams.set("sort", "oldest");
  } else {
    queryParams.set("sort", "freshness");
  }

  const result = useQuery({
    queryKey: ["jobs", queryParams.toString()],
    queryFn: () =>
      api<{ total: number; jobs: Job[] }>(`jobs/search?${queryParams}`),
  });

  const sourcesQuery = useQuery({
    queryKey: ["discovery-sources"],
    queryFn: () =>
      api<{
        sources: SourceMetadata[];
      }>("discovery/sources"),
  });

  const sourceOptions = useMemo(() => {
    const rawSources = Array.isArray(sourcesQuery.data?.sources)
      ? sourcesQuery.data.sources
      : null;

    const baseOptions: Array<{ id: string; label: string }> =
      rawSources && rawSources.length > 0
        ? rawSources.map((s) => ({
            id: s.id,
            label: s.display_name?.trim() || readable(s.id),
          }))
        : [...FALLBACK_SOURCE_OPTIONS];

    const map = new Map<string, string>();
    for (const opt of baseOptions) {
      if (opt.id) {
        map.set(opt.id, opt.label);
      }
    }

    if (platform && !map.has(platform)) {
      map.set(platform, readable(platform));
    }

    return Array.from(map.entries()).map(([id, label]) => ({ id, label }));
  }, [sourcesQuery.data?.sources, platform]);

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: async (jobId: string) => {
      // Invalidate and refresh local job list optimistically
      return { success: true, jobId };
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  // Client-side refinement for complex filters (country, employee size band, seniority, salary, deadline)
  const filteredJobs = useMemo(() => {
    if (!result.data?.jobs) return [];
    let list = [...result.data.jobs];

    // Status: matched filter
    if (status === "matched") {
      list = list.filter((j) => {
        const score = j.match?.match_score ?? j.match_score;
        return score !== null && score !== undefined && score >= 50;
      });
    }

    // Country filter
    if (country) {
      list = list.filter((j) => {
        const c = (j.country || "").toUpperCase();
        const loc = (j.location || "").toUpperCase();
        if (country === "IN")
          return c === "IN" || c === "INDIA" || loc.includes("INDIA");
        if (country === "US")
          return c === "US" || c === "USA" || loc.includes("UNITED STATES");
        if (country === "EU")
          return ["DE", "FR", "NL", "UK", "GB", "GERMANY"].some((x) =>
            loc.includes(x),
          );
        return c.includes(country.toUpperCase());
      });
    }

    // Seniority filter
    if (seniority) {
      list = list.filter((j) => {
        const exp = (j.experience_level || "").toLowerCase();
        const title = j.title.toLowerCase();
        if (seniority === "intern")
          return exp.includes("intern") || title.includes("intern");
        if (seniority === "junior")
          return (
            exp.includes("junior") ||
            exp.includes("entry") ||
            title.includes("junior")
          );
        if (seniority === "mid")
          return (
            exp.includes("mid") ||
            (!title.includes("senior") && !title.includes("lead"))
          );
        if (seniority === "senior")
          return exp.includes("senior") || title.includes("senior");
        if (seniority === "lead")
          return (
            exp.includes("lead") ||
            exp.includes("staff") ||
            title.includes("lead") ||
            title.includes("principal")
          );
        if (seniority === "director")
          return (
            exp.includes("director") ||
            exp.includes("vp") ||
            title.includes("director")
          );
        return true;
      });
    }

    // Employee count / size band filter
    if (employeeRange) {
      list = list.filter((j) => {
        const empCount = j.company_intelligence?.employee_count;
        const band = String(
          j.company_intelligence?.team_size_band ||
            j.company_intelligence?.team_size ||
            j.company_intelligence?.headcount ||
            "",
        );
        if (typeof empCount === "number") {
          if (employeeRange === "1-10") return empCount >= 1 && empCount <= 10;
          if (employeeRange === "11-50")
            return empCount >= 11 && empCount <= 50;
          if (employeeRange === "51-200")
            return empCount >= 51 && empCount <= 200;
          if (employeeRange === "201-500")
            return empCount >= 201 && empCount <= 500;
          if (employeeRange === "500+") return empCount > 500;
        }
        if (employeeRange === "1-10")
          return band.includes("1-10") || band.includes("2-10");
        if (employeeRange === "11-50") return band.includes("11-50");
        if (employeeRange === "51-200")
          return band.includes("51-200") || band.includes("100+");
        if (employeeRange === "500+")
          return band.includes("500+") || band.includes("1000+");
        return true;
      });
    }

    // Published salary only
    if (publishedSalaryOnly) {
      list = list.filter(
        (j) =>
          j.salary_min != null ||
          j.salary_max != null ||
          Boolean(j.salary_range),
      );
    }

    // Minimum salary
    if (minSalary) {
      const minVal = Number(minSalary);
      if (!isNaN(minVal) && minVal > 0) {
        list = list.filter((j) => {
          const sMin =
            j.salary_min ?? (j.salary_max ? j.salary_max * 0.8 : null);
          return sMin !== null && sMin >= minVal;
        });
      }
    }

    // Known deadline only
    if (deadlineOnly) {
      list = list.filter((j) => Boolean(j.application_deadline));
    }

    // Client-side sorting for salary and company
    if (sortBy === "salary") {
      list.sort(
        (a, b) =>
          (b.salary_max ?? b.salary_min ?? 0) -
          (a.salary_max ?? a.salary_min ?? 0),
      );
    } else if (sortBy === "company") {
      list.sort((a, b) =>
        (a.company_name || "").localeCompare(b.company_name || ""),
      );
    }

    return list;
  }, [
    result.data?.jobs,
    status,
    country,
    seniority,
    employeeRange,
    publishedSalaryOnly,
    minSalary,
    deadlineOnly,
    sortBy,
  ]);

  const hasActiveFilters = Boolean(
    role.trim() ||
    location.trim() ||
    skill.trim() ||
    platform.trim() ||
    remoteType ||
    rank ||
    country ||
    employeeRange ||
    seniority ||
    minSalary ||
    publishedSalaryOnly ||
    deadlineOnly ||
    freshnessDays ||
    status !== "all",
  );

  const resetFilters = () => {
    setRole("");
    setLocation("");
    setSkill("");
    setPlatform("");
    setRemoteType("");
    setRank(false);
    setCountry("");
    setEmployeeRange("");
    setSeniority("");
    setMinSalary("");
    setPublishedSalaryOnly(false);
    setDeadlineOnly(false);
    setFreshnessDays("");
    setSortBy("freshness");
    setStatus("all");
    setPage(1);
  };

  const totalCount = result.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / limit));

  return (
    <>
      <PageTitle
        eyebrow="OPPORTUNITIES WITH CONTEXT"
        title="Work worth exploring."
        description="Real listings from verified ATS and job alerts. Clear evidence. A considered next step."
        actions={
          <div className="actions">
            <Link href="/discover" className="button primary">
              <Search size={14} />
              Discover jobs
              <ArrowUpRight size={14} />
            </Link>
          </div>
        }
      />

      {/* Verified Source Badges Banner */}
      <div
        className="panel panel-body spaced"
        aria-label="Supported Job Sources"
      >
        <div className="split">
          <div>
            <strong className="text-xs muted">
              SUPPORTED SOURCES & ATS ADAPTERS:
            </strong>
            <div className="tag-list" style={{ marginTop: "0.4rem" }}>
              {FALLBACK_SOURCE_OPTIONS.map((src) => {
                const details = getSourceDetails(
                  src.id,
                  sourcesQuery.data?.sources,
                );
                return (
                  <Badge
                    key={src.id}
                    tone={details.liveVerified ? "green" : "neutral"}
                  >
                    {details.displayName}{" "}
                    {details.liveVerified ? "✓ Verified" : "(Read-only)"}
                  </Badge>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Status & Priority Tabs */}
      <div className="status-tabs" aria-label="Job application status">
        {jobStatuses.map(([value, label]) => (
          <button
            className={status === value ? "selected" : ""}
            aria-pressed={status === value}
            onClick={() => {
              setStatus(value);
              setPage(1);
            }}
            key={value}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Filter Panel */}
      <div className="filter-panel" aria-label="Job search filters">
        <div className="filter-grid">
          <Field label="TITLE">
            <Input
              aria-label="Job title"
              placeholder="Backend Engineer, Fullstack, AI"
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
                setPage(1);
              }}
            />
          </Field>

          <Field label="LOCATION">
            <Input
              aria-label="Job location"
              placeholder="India, Remote, Berlin, San Francisco"
              value={location}
              onChange={(e) => {
                setLocation(e.target.value);
                setPage(1);
              }}
            />
          </Field>

          <Field label="SKILL">
            <Input
              aria-label="Job skill"
              placeholder="e.g. Python, React, PostgreSQL"
              value={skill}
              onChange={(e) => {
                setSkill(e.target.value);
                setPage(1);
              }}
            />
          </Field>

          <Field label="SOURCE PLATFORM">
            <Select
              aria-label="Source platform"
              value={platform}
              onChange={(e) => {
                setPlatform(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All source platforms</option>
              {sourceOptions.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="WORKPLACE">
            <Select
              aria-label="Workplace preference"
              value={remoteType}
              onChange={(e) => {
                setRemoteType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All workplaces</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On-site</option>
            </Select>
          </Field>
        </div>

        {/* Quick Location & Country Presets */}
        <div className="tag-list" style={{ marginTop: "0.5rem" }}>
          <span className="text-xs muted">Quick Regions:</span>
          <button
            type="button"
            className={`badge ${country === "IN" ? "green" : "neutral"} cursor-pointer`}
            onClick={() => {
              setCountry(country === "IN" ? "" : "IN");
              setPage(1);
            }}
          >
            🇮🇳 India
          </button>
          <button
            type="button"
            className={`badge ${remoteType === "remote" ? "green" : "neutral"} cursor-pointer`}
            onClick={() => {
              setRemoteType(remoteType === "remote" ? "" : "remote");
              setPage(1);
            }}
          >
            🌐 100% Remote
          </button>
          <button
            type="button"
            className={`badge ${country === "US" ? "green" : "neutral"} cursor-pointer`}
            onClick={() => {
              setCountry(country === "US" ? "" : "US");
              setPage(1);
            }}
          >
            🇺🇸 United States
          </button>
          <button
            type="button"
            className={`badge ${country === "EU" ? "green" : "neutral"} cursor-pointer`}
            onClick={() => {
              setCountry(country === "EU" ? "" : "EU");
              setPage(1);
            }}
          >
            🇪🇺 Europe
          </button>
          <Button
            variant="ghost"
            className="text-xs"
            onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
          >
            <SlidersHorizontal size={12} />
            {showAdvancedFilters
              ? "Hide advanced filters"
              : "More filters & sorting"}
          </Button>
        </div>

        {/* Advanced Filters Drawer */}
        {showAdvancedFilters && (
          <div
            className="panel panel-body stack spaced"
            style={{
              marginTop: "0.75rem",
              background: "var(--surface-sunken, rgba(0,0,0,0.02))",
            }}
          >
            <div className="filter-grid">
              <Field label="SENIORITY & LEVEL">
                <Select
                  value={seniority}
                  onChange={(e) => {
                    setSeniority(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">All seniority levels</option>
                  <option value="intern">Internship</option>
                  <option value="junior">Junior / Entry-Level</option>
                  <option value="mid">Mid-Level</option>
                  <option value="senior">Senior</option>
                  <option value="lead">Lead / Staff / Principal</option>
                  <option value="director">Director / Engineering Exec</option>
                </Select>
              </Field>

              <Field label="COMPANY TEAM SIZE">
                <Select
                  value={employeeRange}
                  onChange={(e) => {
                    setEmployeeRange(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">All company sizes</option>
                  <option value="1-10">1–10 employees (Early startup)</option>
                  <option value="11-50">11–50 employees (Growth)</option>
                  <option value="51-200">51–200 employees (Scale-up)</option>
                  <option value="201-500">201–500 employees (Mid-size)</option>
                  <option value="500+">500+ employees (Enterprise)</option>
                </Select>
              </Field>

              <Field label="PUBLICATION FRESHNESS">
                <Select
                  value={freshnessDays}
                  onChange={(e) => {
                    setFreshnessDays(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">Any publication date</option>
                  <option value="1">Last 24 hours (Newest)</option>
                  <option value="7">Last 7 days</option>
                  <option value="14">Last 14 days</option>
                  <option value="30">Last 30 days</option>
                </Select>
              </Field>

              <Field label="SORT OPPORTUNITIES BY">
                <Select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                >
                  <option value="freshness">
                    Publication freshness (Newest first)
                  </option>
                  <option value="match">Match score (Highest match)</option>
                  <option value="salary">
                    Expected compensation (Highest first)
                  </option>
                  <option value="company">Company name (A–Z)</option>
                  <option value="oldest">Oldest first</option>
                </Select>
              </Field>

              <Field label="RESULTS PER PAGE">
                <Select
                  value={limit}
                  onChange={(e) => {
                    setLimit(Number(e.target.value));
                    setPage(1);
                  }}
                >
                  <option value={10}>10 jobs</option>
                  <option value={20}>20 jobs</option>
                  <option value={50}>50 jobs</option>
                </Select>
              </Field>
            </div>

            <div className="tag-list" style={{ marginTop: "0.25rem" }}>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={publishedSalaryOnly}
                  onChange={(e) => setPublishedSalaryOnly(e.target.checked)}
                />
                Published compensation only
              </label>

              <label className="check-label">
                <input
                  type="checkbox"
                  checked={deadlineOnly}
                  onChange={(e) => setDeadlineOnly(e.target.checked)}
                />
                Has known application deadline
              </label>
            </div>
          </div>
        )}

        <div className="extra-filters">
          <label className="check-label">
            <input
              type="checkbox"
              aria-label="Calculate match against my saved profile"
              checked={rank}
              onChange={(e) => setRank(e.target.checked)}
            />
            Calculate match against my saved profile
          </label>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              className="text-xs"
              aria-label="Reset search filters"
              onClick={resetFilters}
            >
              Reset filters
            </Button>
          )}
          <span className="muted text-xs">
            Source filter searches saved opportunities by origin; catalog
            presence does not imply live verification.
          </span>
        </div>
      </div>

      <Notice>
        Prepared packets remain “Not Applied” until an application submission is
        confirmed. Salary is shown only when supplied by the source. Opening an
        application site never automatically submits an application.
      </Notice>

      {result.isPending ? (
        <Skeleton />
      ) : result.isError ? (
        <ErrorState error={result.error} retry={() => result.refetch()} />
      ) : filteredJobs.length ? (
        <>
          <div className="results-toolbar split">
            <strong>
              {filteredJobs.length}{" "}
              {filteredJobs.length === 1 ? "opportunity" : "opportunities"}{" "}
              {totalCount > filteredJobs.length
                ? `(of ${totalCount} indexed)`
                : ""}
            </strong>
            <span className="muted text-xs">
              Observed dates reflect ingestion; publication dates appear only
              when provided by the source.
            </span>
          </div>

          <JobTable
            jobs={filteredJobs}
            onPreview={(job) => setPreviewJob(job)}
            onReject={(jobId) => rejectMutation.mutate(jobId)}
          />

          <div className="pagination">
            <Button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </Button>
            <span>
              Page {page} of {totalPages}
            </span>
            <Button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </>
      ) : (
        <Empty
          title={
            hasActiveFilters
              ? "Room for the right opportunity."
              : "No saved jobs yet"
          }
          description={
            hasActiveFilters
              ? "No saved jobs match these filters. Broaden your criteria, reset your filters, or run a fresh discovery."
              : "No saved jobs found in your repository. Run a discovery to find and import opportunities."
          }
          action={
            <div className="actions">
              {hasActiveFilters && (
                <Button
                  aria-label="Reset search filters"
                  onClick={resetFilters}
                >
                  Reset filters
                </Button>
              )}
              <Link className="button primary" href="/discover">
                <Search size={14} />
                Discover jobs
              </Link>
            </div>
          }
        />
      )}

      {/* Full Job Detail & Preview Modal */}
      <JobPreviewModal
        job={previewJob}
        open={Boolean(previewJob)}
        onClose={() => setPreviewJob(null)}
        onReject={(jobId) => {
          rejectMutation.mutate(jobId);
          setPreviewJob(null);
        }}
      />
    </>
  );
}
