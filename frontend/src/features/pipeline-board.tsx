"use client";
import { useDeferredValue, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";
import { stateTone } from "@/features/autopilot-forms";
import {
  istStamp,
  portalName,
  relativeTime,
  type AppliedPage,
  type AppliedRow,
} from "@/features/applied-model";
import { ProofDrawer } from "@/features/proof-drawer";

export const PIPELINE_KEY = ["v2-pipeline"] as const;
const LIMIT = 200;

export const STAGES = [
  ["queued", "Queued"],
  ["applied", "Applied"],
  ["verified", "Verified"],
  ["assessment", "OA / Assessment"],
  ["interview", "Interview"],
  ["closed", "Rejected / Skipped"],
] as const;
export type Stage = (typeof STAGES)[number][0];

type PipelineRow = AppliedRow & { funnel_stage?: string | null };

const QUEUED = new Set([
  "DISCOVERED",
  "SCORED",
  "APPLYING",
  "WAITING_FOR_USER",
  "QUOTA_HIT_PENDING",
  "DRAFTED_AND_QUEUED",
]);

/** Funnel column for one application: mail-derived funnel signals win over the state. */
export function stageOf(row: PipelineRow): Stage {
  const signal = `${row.funnel_stage ?? ""} ${row.reason ?? ""}`.toUpperCase();
  if (/REJECT/.test(signal)) return "closed";
  if (/INTERVIEW/.test(signal)) return "interview";
  if (/OA_INVITE|ASSESSMENT/.test(signal)) return "assessment";
  if (row.state === "APPLIED")
    return row.email_verified || /VERIFIED|CONFIRMATION_EMAIL/.test(signal)
      ? "verified"
      : "applied";
  if (row.state === "SUBMISSION_UNKNOWN") return "applied";
  if (QUEUED.has(row.state)) return "queued";
  return "closed";
}

export function groupByStage(rows: PipelineRow[]) {
  const groups = Object.fromEntries(
    STAGES.map(([key]) => [key, [] as PipelineRow[]]),
  ) as Record<Stage, PipelineRow[]>;
  for (const row of rows) groups[stageOf(row)].push(row);
  return groups;
}

function Card({ row, onOpen }: { row: PipelineRow; onOpen: () => void }) {
  return (
    <button
      type="button"
      className="kanban-card"
      onClick={onOpen}
      aria-label={`Open proof: ${row.company_name || "Unknown"} — ${row.role_title || "Untitled"}`}
    >
      <h3>{row.company_name || "Unknown company"}</h3>
      <p>{row.role_title || "Untitled role"}</p>
      <Badge tone={stateTone(row.state)}>
        {row.state.replaceAll("_", " ")}
      </Badge>
      <small>
        {portalName(row.platform)} · {relativeTime(row.updated_at) || "—"}
      </small>
    </button>
  );
}

function Board({
  rows,
  onOpen,
}: {
  rows: PipelineRow[];
  onOpen: (id: string) => void;
}) {
  const groups = groupByStage(rows);
  return (
    <div className="kanban" aria-label="Application funnel">
      {STAGES.map(([key, label]) => (
        <section
          className="kanban-column"
          key={key}
          aria-label={`${label} column`}
        >
          <div className="kanban-heading">
            <span>{label.toUpperCase()}</span>
            <span>{groups[key].length}</span>
          </div>
          {groups[key].slice(0, 50).map((row) => (
            <Card key={row.id} row={row} onOpen={() => onOpen(row.id)} />
          ))}
          {groups[key].length > 50 && (
            <p className="muted small-print">
              +{groups[key].length - 50} more — use the table view
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

function DenseTable({
  rows,
  onOpen,
}: {
  rows: PipelineRow[];
  onOpen: (id: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="visually-hidden">Applications</caption>
        <thead>
          <tr>
            <th scope="col">COMPANY</th>
            <th scope="col">ROLE</th>
            <th scope="col">PORTAL</th>
            <th scope="col">STAGE</th>
            <th scope="col">STATE</th>
            <th scope="col">UPDATED</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <button
                  type="button"
                  className="metric-link"
                  onClick={() => onOpen(row.id)}
                >
                  {row.company_name || "Unknown company"}
                </button>
              </td>
              <td className="reason-cell">{row.role_title || "—"}</td>
              <td>{portalName(row.platform)}</td>
              <td>{STAGES.find(([key]) => key === stageOf(row))?.[1]}</td>
              <td>
                <Badge tone={stateTone(row.state)}>
                  {row.state.replaceAll("_", " ")}
                </Badge>
              </td>
              <td>
                <small>{istStamp(row.updated_at)}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PipelineBoard() {
  const [view, setView] = useState<"board" | "table">("board");
  const [platform, setPlatform] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = useDeferredValue(query);
  const page = useQuery({
    queryKey: [...PIPELINE_KEY, platform, q],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(LIMIT), offset: "0" });
      if (platform) params.set("platform", platform);
      if (q.trim()) params.set("q", q.trim().slice(0, 100));
      return api<AppliedPage>(`v2/applications?${params}`);
    },
    placeholderData: keepPreviousData,
    refetchInterval: 30000,
  });
  const rows = (page.data?.items ?? []) as PipelineRow[];
  const platforms = Array.from(new Set(rows.map((r) => r.platform))).sort();
  return (
    <>
      <PageTitle
        eyebrow="APPLICATIONS · FUNNEL"
        title="Pipeline"
        description="Every job from queue to interview. Open any application for its proof receipt."
        actions={
          <div className="actions" role="group" aria-label="View">
            <Button
              variant={view === "board" ? "primary" : "secondary"}
              aria-pressed={view === "board"}
              onClick={() => setView("board")}
            >
              Funnel
            </Button>
            <Button
              variant={view === "table" ? "primary" : "secondary"}
              aria-pressed={view === "table"}
              onClick={() => setView("table")}
            >
              Table
            </Button>
          </div>
        }
      />
      <div className="log-toolbar">
        <Field label="Search">
          <Input
            type="search"
            value={query}
            placeholder="Company or role"
            onChange={(e) => setQuery(e.target.value)}
          />
        </Field>
        <Field label="Portal">
          <Select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            <option value="">All portals</option>
            {[...new Set([...platforms, platform].filter(Boolean))].map((p) => (
              <option key={p} value={p}>
                {portalName(p)}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {page.isPending ? (
        <Skeleton />
      ) : page.isError ? (
        <ErrorState error={page.error} retry={() => page.refetch()} />
      ) : rows.length === 0 ? (
        <Empty description="No applications match. The worker adds jobs as it discovers them." />
      ) : view === "board" ? (
        <Board rows={rows} onOpen={setOpen} />
      ) : (
        <DenseTable rows={rows} onOpen={setOpen} />
      )}
      {page.data && page.data.total > LIMIT && (
        <p className="muted small-print">
          Showing the {LIMIT} most recent of {page.data.total}. Narrow with
          search or portal.
        </p>
      )}
      {open && (
        <ProofDrawer applicationId={open} onClose={() => setOpen(null)} />
      )}
    </>
  );
}
