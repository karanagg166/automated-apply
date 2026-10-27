"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowUpRight, Bookmark, FilePlus2, Search } from "lucide-react";
import { api, dateLabel, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";

export type Job = Schema<"JobRead"> & {
  company_name?: string | null;
  company_domain?: string | null;
  company_intelligence?: Record<string, unknown>;
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
  match?: {
    match_score: number;
    missing_skills: string[];
    match_reasons?: string[];
    exclusion_reasons?: string[];
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
  ["shortlisted", "Shortlisted"],
  ["applied", "Applied"],
  ["packet_prepared", "Packet Prepared"],
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
      <Button onClick={() => mutation.mutate()} busy={mutation.isPending}>
        <FilePlus2 size={13} />
        Prepare application
      </Button>
      {mutation.isError && <ErrorState error={mutation.error} />}
    </>
  );
}

export function JobTable({ jobs }: { jobs: Job[] }) {
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
            <strong>{info.getValue()}</strong>
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
            <PrepareButton jobId={info.row.original.id} />
            <Button
              aria-label={`Shortlist ${info.row.original.title}`}
              disabled={
                info.row.original.status === "shortlisted" ||
                shortlist.isPending
              }
              onClick={() => shortlist.mutate(info.row.original.id)}
            >
              <Bookmark size={13} />
            </Button>
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
  const [role, setRole] = useState("");
  const [location, setLocation] = useState("");
  const [skill, setSkill] = useState("");
  const [platform, setPlatform] = useState("");
  const [remoteType, setRemoteType] = useState<string>("");
  const [status, setStatus] = useState("not_applied");
  const [rank, setRank] = useState(false);
  const [page, setPage] = useState(1);

  const queryParams = new URLSearchParams();
  if (role.trim()) queryParams.set("role", role.trim());
  if (location.trim()) queryParams.set("location", location.trim());
  if (skill.trim()) queryParams.set("skill", skill.trim());
  if (platform.trim()) queryParams.set("platform", platform.trim());
  if (remoteType) queryParams.set("remote_type", remoteType);
  if (status) queryParams.set("application_status", status);
  queryParams.set("rank", String(rank));
  queryParams.set("exclude_preferences", "false");
  queryParams.set("page", String(page));
  queryParams.set("limit", "20");

  const result = useQuery({
    queryKey: ["jobs", queryParams.toString()],
    queryFn: () =>
      api<{ total: number; jobs: Job[] }>(`jobs/search?${queryParams}`),
  });

  const totalCount = result.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / 20));

  return (
    <>
      <PageTitle
        eyebrow="OPPORTUNITIES WITH CONTEXT"
        title="Work worth exploring."
        description="Real listings. Clear sources. A considered next step."
        actions={
          <Link href="/discover" className="button primary">
            <Search size={14} />
            Discover jobs
            <ArrowUpRight size={14} />
          </Link>
        }
      />

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

      <div className="filter-panel" aria-label="Job search filters">
        <div className="filter-grid">
          <Field label="TITLE">
            <Input
              aria-label="Job title"
              placeholder="Backend Engineer"
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
              placeholder="Berlin, Remote, India"
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
              <option value="arbeitnow">Arbeitnow (Free API)</option>
              <option value="greenhouse">Greenhouse</option>
              <option value="remotive">Remotive (Free API)</option>
              <option value="hacker_news">Hacker News</option>
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
      ) : result.data.jobs.length ? (
        <>
          <div className="results-toolbar">
            <strong>{result.data.total} matching opportunities</strong>
            <span className="muted">
              Observed dates reflect ingestion; publication dates appear only
              when provided by the source.
            </span>
          </div>

          <JobTable jobs={result.data.jobs} />

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
          title="Room for the right opportunity."
          description="No saved jobs match these filters. Run a fresh discovery or broaden your criteria."
          action={
            <Link className="button" href="/discover">
              Fresh discovery
            </Link>
          }
        />
      )}
    </>
  );
}
