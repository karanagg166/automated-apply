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
import { statuses } from "./startups";
export type Job = Schema<"JobRead"> & {
  company_name?: string | null;
  application_url?: string | null;
  application_state?: string | null;
  remote_type?: string;
  employment_type?: string;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  match?: { match_score: number; missing_skills: string[] } | null;
  date_posted?: string | null;
  last_observed_at?: string | null;
  source_observations?: Array<{
    original_url: string;
    verification_status: string;
  }>;
};
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
      cell: (info) => (
        <div>
          <strong>{info.getValue()}</strong>
          <small>
            {info.row.original.company_name || "Company evidence not available"}
          </small>
          <small>
            {info.row.original.skills_required?.slice(0, 5).join(" · ")}
          </small>
          {info.row.original.salary_min !== null &&
          info.row.original.salary_min !== undefined ? (
            <small>
              {info.row.original.salary_currency || "Currency unspecified"}{" "}
              {info.row.original.salary_min.toLocaleString()}
              {info.row.original.salary_max
                ? `–${info.row.original.salary_max.toLocaleString()}`
                : ""}
            </small>
          ) : (
            info.row.original.salary_range && (
              <small>{info.row.original.salary_range}</small>
            )
          )}
          {!!info.row.original.match?.missing_skills?.length && (
            <small>
              Missing skills:{" "}
              {info.row.original.match.missing_skills.join(", ")}
            </small>
          )}
        </div>
      ),
    }),
    helper.accessor("location", {
      header: "LOCATION",
      cell: (info) => (
        <>
          <span>{info.getValue() || "Unknown"}</span>
          <small>{readable(info.row.original.remote_type)}</small>
        </>
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
          <Badge>Profile needed</Badge>
        );
      },
    }),
    helper.accessor("source_platform", {
      header: "SOURCE / STATUS",
      cell: (info) => (
        <>
          <span>{readable(info.getValue())}</span>
          <small>
            {readable(
              info.row.original.application_state || info.row.original.status,
            )}
          </small>
          <small>{dateLabel(info.row.original.date_posted)}</small>
        </>
      ),
    }),
    helper.display({
      id: "actions",
      header: "NEXT STEP",
      cell: (info) => (
        <div className="actions">
          <PrepareButton jobId={info.row.original.id} />
          <Button
            aria-label={`Shortlist ${info.row.original.title}`}
            disabled={
              info.row.original.status === "shortlisted" || shortlist.isPending
            }
            onClick={() => shortlist.mutate(info.row.original.id)}
          >
            <Bookmark size={13} />
          </Button>
          <External
            href={
              info.row.original.application_url || info.row.original.job_url
            }
          >
            Source / application site
          </External>
        </div>
      ),
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
  const [role, setRole] = useState(""),
    [location, setLocation] = useState(""),
    [skill, setSkill] = useState(""),
    [status, setStatus] = useState("not_applied"),
    [rank, setRank] = useState(false),
    [page, setPage] = useState(1);
  const query = new URLSearchParams({
    role,
    location,
    skill,
    application_status: status,
    rank: String(rank),
    exclude_preferences: "false",
    page: String(page),
    limit: "20",
  });
  const result = useQuery({
    queryKey: ["jobs", query.toString()],
    queryFn: () => api<{ total: number; jobs: Job[] }>(`jobs/search?${query}`),
  });
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
        {statuses.map(([value, label]) => (
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
      <div className="filter-panel">
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
              placeholder="India"
              value={location}
              onChange={(e) => {
                setLocation(e.target.value);
                setPage(1);
              }}
            />
          </Field>
          <Field label="SKILL">
            <Select
              aria-label="Job skill"
              value={skill}
              onChange={(e) => {
                setSkill(e.target.value);
                setPage(1);
              }}
            >
              <option value="">Any technology</option>
              {[
                "Python",
                "FastAPI",
                "PostgreSQL",
                "React",
                "Next.js",
                "TypeScript",
                "Docker",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="extra-filters">
          <label className="check-label">
            <input
              type="checkbox"
              checked={rank}
              onChange={(e) => setRank(e.target.checked)}
            />
            Calculate match against my saved profile
          </label>
        </div>
      </div>
      <Notice>
        Prepared packets remain “Not Applied” until a submission is reported or
        confirmed. Salary is shown only when supplied by the source. Opening a
        listing never submits an application.
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
              Source publication dates appear when known
            </span>
          </div>
          <JobTable jobs={result.data.jobs} />
          <div className="pagination">
            <Button disabled={page === 1} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <span>Page {page}</span>
            <Button
              disabled={page * 20 >= result.data.total}
              onClick={() => setPage(page + 1)}
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
