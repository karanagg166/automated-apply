"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  Building2,
  Download,
  MapPin,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { api, dateLabel, post, readable, type Schema } from "@/lib/api";
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
export type Startup = Schema<"StartupRead">;

export const statuses = [
  ["not_applied", "Not Applied"],
  ["shortlisted", "Shortlisted"],
  ["packet_prepared", "Packet Prepared"],
  ["applied", "Applied"],
  ["interview", "Interview"],
  ["rejected", "Rejected"],
  ["all", "All"],
] as const;
export const defaultFilters: Schema<"StartupFilters"> = {
  max_employees: null,
  include_unknown_size: true,
  use_profile: false,
  application_status: "not_applied",
  limit: 12,
  page: 1,
  exact_employee_count: false,
  has_business_email: false,
  verified_yc: false,
  early_stage: false,
  size_bands: [],
  locations: [],
  roles: [],
  skills: [],
  stages: [],
  freshness_days: 30,
  minimum_score: 0,
  has_leader_evidence: false,
  has_technical_staff: false,
  industries: [],
  country: null,
};
export function sizeFilter(size: string) {
  if (size === "2-10") {
    return {
      min_employees: 2,
      max_employees: 10,
      exact_employee_count: false,
      include_unknown_size: false,
      size_bands: ["1-10", "2-10"],
    };
  }
  if (size === "11-50") {
    return {
      min_employees: 11,
      max_employees: 50,
      exact_employee_count: false,
      include_unknown_size: false,
      size_bands: ["11-50"],
    };
  }
  if (size === "unknown") {
    return {
      min_employees: null,
      max_employees: null,
      exact_employee_count: false,
      include_unknown_size: true,
      size_bands: ["unknown"],
    };
  }
  if (size === "all") {
    return {
      min_employees: null,
      max_employees: null,
      exact_employee_count: false,
      include_unknown_size: true,
      size_bands: [],
    };
  }
  return {
    min_employees: null,
    max_employees: null,
    exact_employee_count: false,
    include_unknown_size: false,
    size_bands: [size],
  };
}
export const industries = [
  "All industries",
  "Software",
  "SaaS",
  "AI",
  "Fintech",
  "Developer Tools",
] as const;
export const indianLocations = [
  "Any",
  "India",
  "Bengaluru",
  "Delhi NCR",
  "Hyderabad",
  "Pune",
  "Mumbai",
  "Remote",
] as const;
const technologies = [
  "Python",
  "FastAPI",
  "PostgreSQL",
  "React",
  "Next.js",
  "TypeScript",
  "Node.js",
  "AI / LLM",
  "RAG",
  "Redis",
  "Docker",
];
export function StartupExplorer() {
  const params = useSearchParams(),
    client = useQueryClient();
  const [filters, setFilters] = useState<Schema<"StartupFilters">>({
      ...defaultFilters,
      query: params?.get("q") || null,
    }),
    [size, setSize] = useState("all"),
    [industry, setIndustry] = useState("All industries"),
    [extra, setExtra] = useState(false),
    [presetOpen, setPresetOpen] = useState(false),
    [presetName, setPresetName] = useState(""),
    [message, setMessage] = useState("");
  const globalQuery = params?.get("q");
  useEffect(() => {
    setFilters((current) => ({
      ...current,
      query: globalQuery || null,
      page: 1,
    }));
  }, [globalQuery]);
  const update = (value: Partial<Schema<"StartupFilters">>) =>
    setFilters((f) => ({ ...f, ...value, page: 1 }));
  const result = useQuery({
    queryKey: ["startups", filters],
    queryFn: () =>
      post<{ total: number; startups: Startup[] }>("startups/search", filters),
  });
  const presets = useQuery({
    queryKey: ["presets"],
    queryFn: () =>
      api<{
        presets: Array<{ name: string; filters: Schema<"StartupFilters"> }>;
      }>("dashboard/presets"),
  });
  const save = useMutation({
    mutationFn: () => post("dashboard/presets", { name: presetName, filters }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["presets"] });
      setPresetOpen(false);
      setMessage("Filter preset saved to your workspace.");
    },
  });
  const shortlist = useMutation({
    mutationFn: (id: string) => post(`startups/${id}/shortlist`, {}),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["startups"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="GOOD TEAMS. MEANINGFUL WORK."
        title="Find your kind of startup."
        description="Explore emerging teams through real jobs, source evidence, and your priorities."
        actions={
          <>
            <Button onClick={() => result.refetch()} busy={result.isFetching}>
              <RefreshCw size={14} />
              Refresh saved
            </Button>
            <Link className="button primary" href="/discover">
              <Plus size={15} />
              Fresh discovery
            </Link>
          </>
        }
      />
      <div className="status-tabs" role="group" aria-label="Application status">
        {statuses.map(([value, label]) => (
          <button
            key={value}
            className={filters.application_status === value ? "selected" : ""}
            aria-pressed={filters.application_status === value}
            onClick={() => update({ application_status: value })}
          >
            {label}
          </button>
        ))}
      </div>
      <section className="filter-panel" aria-label="Startup filters">
        <div className="filter-search">
          <Search size={18} />
          <Input
            aria-label="Search saved startups"
            placeholder="Search saved startups by name or domain…"
            value={filters.query || ""}
            onChange={(e) => update({ query: e.target.value || null })}
          />
          <Button onClick={() => result.refetch()}>Search saved</Button>
          <Button aria-expanded={extra} onClick={() => setExtra(!extra)}>
            <SlidersHorizontal size={14} />
            <span>Filters</span>
          </Button>
        </div>
        <div className="filter-grid">
          <Field label="LOCATION">
            <Select
              aria-label="Location"
              value={
                filters.remote_preference === "remote"
                  ? "Remote"
                  : filters.locations?.[0] || "Any"
              }
              onChange={(e) =>
                update({
                  locations:
                    e.target.value === "Remote" || e.target.value === "Any"
                      ? []
                      : [e.target.value],
                  remote_preference:
                    e.target.value === "Remote" ? "remote" : "any",
                })
              }
            >
              {indianLocations.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="TEAM SIZE">
            <Select
              aria-label="Company size"
              value={size}
              onChange={(e) => {
                setSize(e.target.value);
                update(
                  sizeFilter(e.target.value) as Partial<
                    Schema<"StartupFilters">
                  >,
                );
              }}
            >
              {[
                ["all", "All sizes"],
                ["2-10", "2–10 employees"],
                ["11-50", "11–50 employees"],
                ["51-200", "51–200 employees"],
                ["201-500", "201–500 employees"],
                ["unknown", "Unknown size"],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="INDUSTRY">
            <Select
              aria-label="Industry"
              value={industry}
              onChange={(e) => {
                setIndustry(e.target.value);
                update({
                  industries:
                    e.target.value === "All industries" ? [] : [e.target.value],
                });
              }}
            >
              {industries.map((ind) => (
                <option key={ind} value={ind}>
                  {ind}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="TECHNOLOGY">
            <Select
              aria-label="Technology"
              value={filters.skills?.[0] || "Any"}
              onChange={(e) =>
                update({
                  skills: e.target.value === "Any" ? [] : [e.target.value],
                })
              }
            >
              {["Any", ...technologies].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </Select>
          </Field>
          <Field label="ROLE">
            <Select
              aria-label="Role"
              value={filters.roles?.[0] || "Any"}
              onChange={(e) =>
                update({
                  roles: e.target.value === "Any" ? [] : [e.target.value],
                })
              }
            >
              {[
                "Any",
                "Backend Engineer",
                "Software Engineer",
                "Full Stack Engineer",
                "AI Engineer",
                "Python Developer",
                "SDE 1",
                "Internship",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </Select>
          </Field>
          <Field label="HIRING SIGNAL">
            <Select
              aria-label="Hiring signal"
              value={filters.hiring_status || ""}
              onChange={(e) =>
                update({
                  hiring_status: (e.target.value ||
                    null) as Schema<"StartupFilters">["hiring_status"],
                })
              }
            >
              {[
                ["", "All signals"],
                ["hiring_confirmed", "Confirmed hiring"],
                ["hiring_possible", "Possible hiring"],
                ["hiring_unknown", "Unknown"],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {extra && (
          <>
            <div className="filter-grid">
              <Field label="COUNTRY">
                <Input
                  aria-label="Country"
                  value={filters.country || ""}
                  onChange={(event) =>
                    update({ country: event.target.value || null })
                  }
                  placeholder="e.g. India"
                />
              </Field>
              <Field label="WORK POLICY">
                <Select
                  aria-label="Work policy"
                  value={filters.remote_preference || "any"}
                  onChange={(e) =>
                    update({ remote_preference: e.target.value as "any" })
                  }
                >
                  {["any", "remote", "hybrid", "onsite"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </Select>
              </Field>
              <Field label="MINIMUM MATCH">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={filters.minimum_score || 0}
                  onChange={(e) =>
                    update({ minimum_score: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label="SOURCE">
                <Input
                  placeholder="Exact provider name"
                  value={filters.source || ""}
                  onChange={(e) => update({ source: e.target.value || null })}
                />
              </Field>
              <Field label="EVIDENCE AGE (DAYS)">
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={filters.freshness_days || 30}
                  onChange={(e) =>
                    update({ freshness_days: Number(e.target.value) || 30 })
                  }
                />
              </Field>
            </div>
            <div className="extra-filters">
              {[
                ["has_leader_evidence", "Known founder / leader"],
                ["has_technical_staff", "Technical staff evidence"],
                ["has_business_email", "Send-ready email evidence"],
                ["verified_yc", "YC evidence"],
                ["early_stage", "Early-stage evidence"],
                ["use_profile", "Use my preferences"],
              ].map(([key, label]) => (
                <label className="check-label" key={key}>
                  <input
                    type="checkbox"
                    checked={!!filters[key as keyof typeof filters]}
                    onChange={(e) => update({ [key]: e.target.checked })}
                  />
                  {label}
                </label>
              ))}
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={!!filters.observed_after}
                  onChange={(e) =>
                    update({
                      observed_after: e.target.checked
                        ? new Date(Date.now() - 86400000).toISOString()
                        : null,
                    })
                  }
                />
                Only new in 24 hours
              </label>
            </div>
          </>
        )}
        {size === "2-10" && (
          <div className="extra-filters">
            <small className="muted">
              Includes observed counts from 2 to 10 and reported 2–10 bands. A
              broader 1–10 band alone cannot establish the lower bound.
            </small>
          </div>
        )}
      </section>
      <div className="results-toolbar">
        <div>
          <strong>
            {result.data ? `${result.data.total} teams` : "Your saved teams"}
          </strong>
          <span className="muted"> · Evidence first. Always.</span>
        </div>
        <div className="actions">
          <Button
            variant="ghost"
            onClick={() => {
              setFilters(defaultFilters);
              setSize("all");
              setMessage("Filters reset.");
            }}
          >
            Reset filters
          </Button>
          <Button onClick={() => setPresetOpen(true)}>
            <Bookmark size={12} />
            Save preset
          </Button>
          <Button
            disabled={!result.data?.startups.length}
            onClick={() => {
              const allowed = result.data!.startups.filter(
                (s) =>
                  s.sources.length &&
                  s.sources.every((x) => ["manual", "greenhouse"].includes(x)),
              );
              const blob = new Blob(
                [
                  JSON.stringify(
                    allowed.map((s) => ({
                      company: s.company_name,
                      domain: s.company_domain,
                      sources: s.sources,
                    })),
                    null,
                    2,
                  ),
                ],
                { type: "application/json" },
              );
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "permitted-startup-view.json";
              a.click();
              URL.revokeObjectURL(url);
              setMessage(
                `Exported ${allowed.length} public/manual company references. Restricted provider records and contact data are excluded.`,
              );
            }}
          >
            <Download size={12} />
            Export
          </Button>
        </div>
      </div>
      {!!presets.data?.presets?.length && (
        <div className="actions" style={{ marginBottom: 16 }}>
          {presets.data.presets.map((p) => (
            <Button
              key={p.name}
              onClick={() => {
                setFilters(p.filters);
                setSize(
                  p.filters.exact_employee_count
                    ? "2-10"
                    : p.filters.size_bands?.[0] || "all",
                );
              }}
            >
              {p.name}
              <ArrowRight size={12} />
            </Button>
          ))}
        </div>
      )}
      {message && <Notice>{message}</Notice>}
      {shortlist.isError && <ErrorState error={shortlist.error} />}{" "}
      {result.isPending ? (
        <Skeleton />
      ) : result.isError ? (
        <ErrorState error={result.error} retry={() => result.refetch()} />
      ) : result.data.startups.length ? (
        <>
          <div className="company-grid">
            {result.data.startups.map((s) => (
              <article className="company-card" key={s.company_id}>
                <div className="company-top">
                  <span className="company-logo">
                    {s.company_name.slice(0, 2)}
                  </span>
                  <div>
                    <h3>
                      <Link href={`/startups/${s.company_id}`}>
                        {s.company_name}
                      </Link>
                    </h3>
                    <p>
                      {s.attributes.industry ||
                        s.company_domain ||
                        "Industry not established"}
                    </p>
                  </div>
                  <Badge
                    tone={
                      s.hiring_status === "hiring_confirmed"
                        ? "green"
                        : "neutral"
                    }
                  >
                    {readable(s.hiring_status)}
                  </Badge>
                </div>
                <p className="company-description">
                  {s.attributes.description ||
                    "Explore the saved company and hiring evidence to understand what this team is building."}
                </p>
                <div className="company-meta">
                  <span>
                    <MapPin size={12} />
                    {s.attributes.location || "Location unknown"}
                  </span>
                  <span>
                    <Users size={12} />
                    {s.employee_count !== null &&
                    ["source_reported", "human_confirmed"].includes(
                      s.team_size_evidence_status,
                    )
                      ? `${s.employee_count} employees (${s.team_size_evidence_status === "human_confirmed" ? "human confirmed" : "source reported"})`
                      : s.team_size_band && s.team_size_band !== "unknown"
                        ? `${s.team_size_band} band`
                        : "Size unknown"}
                  </span>
                  {s.company_domain && (
                    <External href={`https://${s.company_domain}`}>
                      Official website
                    </External>
                  )}
                </div>
                <div className="tag-list">
                  {(s.attributes.technology_stack || [])
                    .slice(0, 5)
                    .map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  {!s.attributes.technology_stack?.length && (
                    <Badge>Technology evidence missing</Badge>
                  )}
                  {s.attributes.yc_batch && (
                    <Badge>YC {s.attributes.yc_batch}</Badge>
                  )}
                  {s.leader_evidence_count > 0 ? (
                    <Badge tone="green">
                      Founder / CEO available ({s.leader_evidence_count})
                    </Badge>
                  ) : (
                    <Badge tone="neutral">No leader recorded</Badge>
                  )}
                  {s.technical_staff_count > 0 && (
                    <Badge tone="neutral">
                      Technical staff evidence ({s.technical_staff_count})
                    </Badge>
                  )}
                </div>
                <div className="company-evidence">
                  <Building2 size={13} />
                  <strong>
                    {s.current_job_count} current role
                    {s.current_job_count === 1 ? "" : "s"}
                  </strong>
                  <span>· {s.sources.join(", ") || "No retained source"}</span>
                  <span style={{ marginLeft: "auto" }} className="score">
                    {Math.round(s.startup_match_score)}
                    <small>match</small>
                  </span>
                </div>
                <div className="company-meta">
                  <Badge
                    tone={
                      s.team_size_evidence_status === "human_confirmed"
                        ? "green"
                        : s.team_size_evidence_status === "source_reported"
                          ? "neutral"
                          : s.team_size_evidence_status === "conflicting"
                            ? "red"
                            : "amber"
                    }
                  >
                    Size: {readable(s.team_size_evidence_status)}
                  </Badge>
                  <span>
                    Last observed{" "}
                    {dateLabel(
                      s.team_size_evidence[0]?.observed_at ||
                        s.hiring_evidence[0]?.observed_at ||
                        null,
                    )}
                  </span>
                </div>
                <div className="company-actions">
                  <Link href={`/startups/${s.company_id}`} className="button">
                    View company
                    <ArrowUpRight size={12} />
                  </Link>
                  <Link
                    href={`/startups/${s.company_id}?tab=jobs`}
                    className="button ghost"
                  >
                    View jobs
                  </Link>
                  <Link
                    href={`/startups/${s.company_id}?tab=people`}
                    className="button ghost"
                  >
                    View founder
                  </Link>
                  <Button
                    disabled={s.shortlisted || shortlist.isPending}
                    aria-label={`Shortlist ${s.company_name}`}
                    onClick={() => shortlist.mutate(s.company_id)}
                  >
                    <Bookmark
                      size={13}
                      fill={s.shortlisted ? "currentColor" : "none"}
                    />
                    {s.shortlisted ? "Saved" : "Save"}
                  </Button>
                </div>
              </article>
            ))}
          </div>
          <div className="pagination">
            <Button
              disabled={(filters.page || 1) === 1}
              onClick={() =>
                setFilters((f) => ({ ...f, page: (f.page || 1) - 1 }))
              }
            >
              Previous
            </Button>
            <span>
              Page {filters.page || 1} · {result.data.total} matching teams
            </span>
            <Button
              disabled={(filters.page || 1) * 12 >= result.data.total}
              onClick={() =>
                setFilters((f) => ({ ...f, page: (f.page || 1) + 1 }))
              }
            >
              Next
            </Button>
          </div>
        </>
      ) : (
        <Empty
          title="Your next team is out there."
          description="No saved startups match this view. Try a wider filter or run an approved public-source search to bring new opportunities into your workspace."
          action={
            <Link href="/discover" className="button primary">
              Start fresh discovery
              <ArrowUpRight size={14} />
            </Link>
          }
        />
      )}
      <Modal
        open={presetOpen}
        onOpenChange={setPresetOpen}
        title="Save this perspective"
        description="Your filters are saved privately so you can return to this search."
      >
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Preset name">
            <Input
              required
              maxLength={80}
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
            />
          </Field>
          {save.isError && <ErrorState error={save.error} />}
          <Button type="submit" variant="primary" busy={save.isPending}>
            Save preset
          </Button>
        </form>
      </Modal>
    </>
  );
}
