"use client";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, del, post } from "@/lib/api";
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
import { stamp } from "@/features/autopilot-forms";

/** GET v2/semantic-cache/stats (store totals + per-process decision counters). */
export type CacheStats = {
  total_entries?: number;
  total_hits?: number;
  threshold?: number;
  status_counts?: Record<string, number>;
  stale_entries?: number | null;
  decisions?: {
    since?: string;
    lookups?: number;
    hits?: number;
    hit_rate?: number | null;
    counters?: Record<string, number>;
    rejections?: Record<string, number>;
  };
};

export type ExplainCandidate = {
  id?: string;
  question?: string | null;
  question_text?: string | null;
  answer?: string | null;
  similarity?: number | null;
  passed?: boolean | null;
  reason?: string | null;
};

/** POST v2/semantic-cache/explain — dry-run decision trace (no hit counted). */
export type ExplainTrace = {
  intent_bucket?: string | null;
  field_type?: string | null;
  cache_policy?: string | null;
  invalidation_scope?: string | null;
  polarity?: string | null;
  entities?: Record<string, unknown>;
  decision?: string | null;
  reason?: string | null;
  candidates?: ExplainCandidate[];
  hit?: {
    id: string;
    match: string;
    similarity: number;
    answer: string;
  } | null;
};

export type CacheRowStatus = "active" | "quarantined" | "expired";
export type StudioEntry = {
  id: string;
  kind: string;
  question_text: string;
  answer_text: string;
  source: "user" | "profile" | "llm";
  hits: number;
  updated_at?: string | null;
  status?: CacheRowStatus | string;
};
type EntryPage = {
  items: StudioEntry[];
  total: number;
  limit: number;
  offset: number;
};
export type StampResult = {
  stamped: number;
  profile_hash: string;
  stale_remaining: number;
};

export const STUDIO_KEY = ["v2-cache-studio"] as const;
export const STUDIO_STATS_KEY = ["v2-cache-studio-stats"] as const;
const PAGE = 25;

export const REJECTION_REASONS = [
  ["entity_mismatch", "Entity mismatch"],
  ["polarity_flip", "Polarity flip"],
  ["cross_company", "Cross-company"],
  ["option_mismatch", "Option mismatch"],
  ["stale_profile", "Stale profile"],
  ["below_threshold", "Below threshold"],
] as const;

/** Explorer filters: three map to the server `status`, two to the entry source. */
export const FILTERS = [
  ["active", "Active"],
  ["quarantined", "Quarantined"],
  ["stale", "Stale / expired"],
  ["human_verified", "Human verified"],
  ["llm_verified", "LLM verified"],
] as const;
export type StudioFilter = (typeof FILTERS)[number][0];

export function studioPath(filter: StudioFilter, q: string, offset: number) {
  const params = new URLSearchParams({
    kind: "screening_qa",
    limit: String(PAGE),
    offset: String(offset),
    status:
      filter === "quarantined"
        ? "quarantined"
        : filter === "stale"
          ? "expired"
          : "active",
  });
  if (q.trim()) params.set("q", q.trim().slice(0, 200));
  return `v2/semantic-cache?${params}`;
}

export function matchesSource(entry: StudioEntry, filter: StudioFilter) {
  if (filter === "human_verified") return entry.source === "user";
  if (filter === "llm_verified") return entry.source === "llm";
  return true;
}

export function parseOptions(text: string) {
  return text
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 400);
}

export function staleCount(stats?: CacheStats, stampResult?: StampResult) {
  if (stampResult) return stampResult.stale_remaining;
  if (typeof stats?.stale_entries === "number") return stats.stale_entries;
  return stats?.decisions?.counters?.rejected_stale_profile ?? 0;
}

function Telemetry({ stats }: { stats: CacheStats }) {
  const counters = stats.decisions?.counters ?? {};
  const exact = counters.exact_hit ?? 0;
  const semantic = counters.semantic_hit ?? 0;
  const rejected = REJECTION_REASONS.reduce(
    (sum, [key]) => sum + (counters[`rejected_${key}`] ?? 0),
    0,
  );
  const rate = stats.decisions?.hit_rate;
  return (
    <section className="panel" aria-labelledby="cache-telemetry">
      <div className="panel-header">
        <div>
          <h2 id="cache-telemetry">Cache telemetry</h2>
          <p>
            Decision counters since{" "}
            {stamp(stats.decisions?.since, "this API process started")}. Every
            hit is one LLM call saved.
          </p>
        </div>
        <Badge tone="green">
          {(stats.total_hits ?? 0).toLocaleString("en-IN")} LLM calls saved
        </Badge>
      </div>
      <div className="panel-body stack">
        <div className="metrics" aria-label="Cache decisions">
          {[
            ["Exact hits", exact],
            ["Semantic hits", semantic],
            ["Rejections", rejected],
            ["Hit rate", rate == null ? "—" : `${Math.round(rate * 100)}%`],
            ["Entries", stats.total_entries ?? 0],
          ].map(([label, value]) => (
            <div className="metric" key={label}>
              <div className="metric-label">{label}</div>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <dl className="worker-facts" aria-label="Rejections by reason">
          {REJECTION_REASONS.map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{counters[`rejected_${key}`] ?? 0}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function TraceValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) return <>{value.map(String).join(", ") || "—"}</>;
  if (value && typeof value === "object")
    return <code>{JSON.stringify(value)}</code>;
  return <>{value === null || value === undefined ? "—" : String(value)}</>;
}

export function ExplainTraceView({ trace }: { trace: ExplainTrace }) {
  const entities = Object.entries(trace.entities ?? {});
  const passed = trace.hit != null;
  return (
    <div className="stack" aria-label="Decision trace">
      <div className="tag-list">
        <Badge tone={passed ? "green" : "amber"}>
          {passed
            ? `Would answer (${trace.hit!.match} · ${trace.hit!.similarity.toFixed(2)})`
            : "No cached answer — falls through to LLM / you"}
        </Badge>
        {(trace.decision || trace.reason) && (
          <Badge tone="neutral">
            {[trace.decision, trace.reason].filter(Boolean).join(": ")}
          </Badge>
        )}
      </div>
      <dl className="worker-facts">
        {(
          [
            ["Intent bucket", trace.intent_bucket],
            ["Field type", trace.field_type],
            ["Polarity", trace.polarity],
            ["Cache policy", trace.cache_policy],
            ["Invalidation", trace.invalidation_scope],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              <TraceValue value={value} />
            </dd>
          </div>
        ))}
        {entities.map(([name, value]) => (
          <div key={name}>
            <dt>Entity · {name}</dt>
            <dd>
              <TraceValue value={value} />
            </dd>
          </div>
        ))}
      </dl>
      {trace.hit && (
        <Notice>
          Answer: <strong>{trace.hit.answer}</strong> (entry{" "}
          <code>{trace.hit.id.slice(0, 8)}</code>)
        </Notice>
      )}
      {!!trace.candidates?.length && (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">Top candidate entries</caption>
            <thead>
              <tr>
                <th scope="col">CANDIDATE</th>
                <th scope="col">SIMILARITY</th>
                <th scope="col">RESULT</th>
              </tr>
            </thead>
            <tbody>
              {trace.candidates.map((c, i) => (
                <tr key={c.id ?? i}>
                  <td className="reason-cell">
                    {c.question_text ?? c.question ?? c.id}
                  </td>
                  <td>
                    {c.similarity == null ? "—" : c.similarity.toFixed(3)}
                  </td>
                  <td>
                    <Badge tone={c.passed ? "green" : "red"}>
                      {c.passed ? "pass" : (c.reason ?? "rejected")}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Playground() {
  const [question, setQuestion] = useState("");
  const [fieldType, setFieldType] = useState("");
  const [company, setCompany] = useState("");
  const [options, setOptions] = useState("");
  const explain = useMutation({
    mutationFn: () =>
      post<ExplainTrace>("v2/semantic-cache/explain", {
        question: question.trim(),
        field_kind: fieldType || null,
        company: company.trim() || null,
        options: parseOptions(options),
      }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (question.trim().length >= 3) explain.mutate();
  };
  return (
    <section className="panel" aria-labelledby="cache-playground">
      <div className="panel-header">
        <div>
          <h2 id="cache-playground">Cache playground</h2>
          <p>Dry-run a form question. Nothing is counted or saved.</p>
        </div>
      </div>
      <form className="panel-body stack" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Question">
            <Input
              value={question}
              maxLength={1000}
              placeholder="e.g. Do you have 2+ years of Python experience?"
              onChange={(e) => setQuestion(e.target.value)}
            />
          </Field>
          <Field label="Field type">
            <Select
              value={fieldType}
              onChange={(e) => setFieldType(e.target.value)}
            >
              <option value="">Unknown</option>
              {[
                "radio",
                "select",
                "combobox",
                "checkbox",
                "text",
                "textarea",
              ].map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Company (optional)">
            <Input
              value={company}
              maxLength={200}
              onChange={(e) => setCompany(e.target.value)}
            />
          </Field>
          <Field label="Options (comma-separated)">
            <Input
              value={options}
              placeholder="Yes, No"
              onChange={(e) => setOptions(e.target.value)}
            />
          </Field>
        </div>
        <div className="actions">
          <Button
            type="submit"
            variant="primary"
            busy={explain.isPending}
            disabled={question.trim().length < 3}
          >
            Explain decision
          </Button>
        </div>
        {explain.isError && <ErrorState error={explain.error} />}
        {explain.data && <ExplainTraceView trace={explain.data} />}
      </form>
    </section>
  );
}

function EntryRow({
  entry,
  status,
  onChanged,
}: {
  entry: StudioEntry;
  status: CacheRowStatus;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [answer, setAnswer] = useState(entry.answer_text);
  const quarantined = status === "quarantined";
  const action = useMutation({
    mutationFn: (kind: "quarantine" | "unquarantine" | "delete" | "edit") => {
      if (kind === "delete") return del(`v2/semantic-cache/${entry.id}`);
      if (kind === "edit")
        return post("v2/semantic-cache", {
          kind: entry.kind,
          question_text: entry.question_text,
          answer_text: answer.trim(),
        });
      return post(
        `v2/semantic-cache/${entry.id}/${kind}`,
        kind === "quarantine" ? { reason: "owner_quarantine" } : {},
      );
    },
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
  });
  return (
    <tr>
      <td className="reason-cell">{entry.question_text}</td>
      <td className="reason-cell">
        {editing ? (
          <Input
            aria-label={`New answer for: ${entry.question_text}`}
            value={answer}
            maxLength={4000}
            onChange={(e) => setAnswer(e.target.value)}
          />
        ) : (
          entry.answer_text
        )}
      </td>
      <td>
        <Badge
          tone={
            quarantined ? "red" : entry.source === "llm" ? "amber" : "green"
          }
        >
          {quarantined
            ? "Quarantined"
            : entry.source === "user"
              ? "Human verified"
              : entry.source === "llm"
                ? "LLM verified"
                : "Profile"}
        </Badge>
      </td>
      <td>{entry.hits}</td>
      <td>
        <small>{stamp(entry.updated_at, "—")}</small>
      </td>
      <td>
        <div className="actions">
          {editing ? (
            <>
              <Button
                variant="primary"
                busy={action.isPending}
                disabled={!answer.trim()}
                onClick={() => action.mutate("edit")}
              >
                Save
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button variant="ghost" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
          <Button
            busy={action.isPending}
            aria-label={`${quarantined ? "Unquarantine" : "Quarantine"}: ${entry.question_text}`}
            onClick={() =>
              action.mutate(quarantined ? "unquarantine" : "quarantine")
            }
          >
            {quarantined ? "Unquarantine" : "Quarantine"}
          </Button>
          <Button
            variant="danger"
            busy={action.isPending}
            aria-label={`Delete: ${entry.question_text}`}
            onClick={() => action.mutate("delete")}
          >
            Delete
          </Button>
        </div>
        {action.isError && (
          <small className="portal-hint" role="alert">
            {action.error.message}
          </small>
        )}
      </td>
    </tr>
  );
}

function Explorer() {
  const client = useQueryClient();
  const [filter, setFilter] = useState<StudioFilter>("active");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const page = useQuery({
    queryKey: [...STUDIO_KEY, filter, query, offset],
    queryFn: () => api<EntryPage>(studioPath(filter, query, offset)),
  });
  const status: CacheRowStatus =
    filter === "quarantined"
      ? "quarantined"
      : filter === "stale"
        ? "expired"
        : "active";
  const rows = (page.data?.items ?? []).filter((e) => matchesSource(e, filter));
  const total = page.data?.total ?? 0;
  const refresh = () => {
    client.invalidateQueries({ queryKey: STUDIO_KEY });
    client.invalidateQueries({ queryKey: STUDIO_STATS_KEY });
  };
  return (
    <section className="panel" aria-labelledby="cache-explorer">
      <div className="panel-header">
        <div>
          <h2 id="cache-explorer">Entry explorer</h2>
          <p>Edit re-teaches the answer as yours (it outranks profile/LLM).</p>
        </div>
        <div className="actions">
          <Field label="Search">
            <Input
              type="search"
              value={query}
              placeholder="Question or answer"
              onChange={(e) => {
                setQuery(e.target.value);
                setOffset(0);
              }}
            />
          </Field>
          <Field label="Status">
            <Select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value as StudioFilter);
                setOffset(0);
              }}
            >
              {FILTERS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
      <div className="panel-body">
        {page.isPending ? (
          <Skeleton />
        ) : page.isError ? (
          <ErrorState error={page.error} retry={() => page.refetch()} />
        ) : rows.length === 0 ? (
          <p className="muted">No entries match this filter.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">
                Semantic cache entries
              </caption>
              <thead>
                <tr>
                  <th scope="col">QUESTION</th>
                  <th scope="col">ANSWER</th>
                  <th scope="col">TRUST</th>
                  <th scope="col">HITS</th>
                  <th scope="col">UPDATED</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <EntryRow
                    key={entry.id}
                    entry={entry}
                    status={status}
                    onChanged={refresh}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE && (
          <div className="actions spaced">
            <Button
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              Previous
            </Button>
            <span className="muted small-print">
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <Button
              variant="ghost"
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Next
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

export function CacheStudio() {
  const client = useQueryClient();
  const stats = useQuery({
    queryKey: STUDIO_STATS_KEY,
    queryFn: () => api<CacheStats>("v2/semantic-cache/stats"),
    refetchInterval: 30000,
  });
  const stampProfile = useMutation({
    mutationFn: () => post<StampResult>("v2/semantic-cache/stamp-profile"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: STUDIO_STATS_KEY });
      client.invalidateQueries({ queryKey: STUDIO_KEY });
    },
  });
  const stale = staleCount(stats.data, stampProfile.data);
  return (
    <>
      <PageTitle
        eyebrow="SEMANTIC CACHE · 4-TIER ANSWERS"
        title="Cache Studio"
        description="See why a cached answer was used or rejected, test questions before the worker meets them, and quarantine anything wrong."
        actions={
          <Button
            variant="primary"
            busy={stampProfile.isPending}
            onClick={() => stampProfile.mutate()}
          >
            Stamp profile hash
          </Button>
        }
      />
      {stale > 0 && (
        <div className="notice warn" role="status">
          {stale} cached answer{stale === 1 ? " was" : "s were"} given for an
          older profile version and will be rejected as stale until you stamp
          the current profile hash.
        </div>
      )}
      {stampProfile.isSuccess && (
        <Notice>
          Stamped {stampProfile.data.stamped} entries with profile{" "}
          <code>{stampProfile.data.profile_hash}</code>.
        </Notice>
      )}
      {stampProfile.isError && <ErrorState error={stampProfile.error} />}
      {stats.isPending ? (
        <Skeleton />
      ) : stats.isError ? (
        <ErrorState error={stats.error} retry={() => stats.refetch()} />
      ) : (
        <Telemetry stats={stats.data} />
      )}
      <Playground />
      <Explorer />
    </>
  );
}
