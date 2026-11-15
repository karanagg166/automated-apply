"use client";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { BrowserIntake } from "@/features/browser-assistant";
import { api, dateLabel, readable, type Schema } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, List, Plus, Rows3 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { pipelineColumn } from "./application-pipeline";
export { ApplicationDetail } from "./application-detail";
export {
  getFieldReviewStatus,
  type FieldReviewStatus,
} from "./application-field-review";
export { pipelineColumn } from "./application-pipeline";
type Packet = Schema<"PacketRead">;
export function Applications() {
  const [view, setView] = useState("board"),
    [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["packets", offset],
    queryFn: () =>
      api<Schema<"PacketList">>(
        `application-packets?limit=100&offset=${offset}`,
      ),
  });
  const columns = [
    "Preparing",
    "Needs Input",
    "Ready for Review",
    "Approved / Manual Handoff",
    "External Application Opened",
    "Submitting",
    "Submission Unknown",
    "Applied — User Reported",
    "Applied — Provider Confirmed",
    "Interview",
    "Offer",
    "Rejected",
    "Archived",
  ];
  return (
    <>
      <PageTitle
        eyebrow="EVERY MOVE, IN ONE PLACE"
        title="Your search is taking shape."
        description="Prepare carefully. Review with confidence. Track what actually happened."
        actions={
          <div className="actions">
            <Button
              aria-pressed={view === "board"}
              onClick={() => setView("board")}
            >
              <Rows3 size={14} />
              Board
            </Button>
            <Button
              aria-pressed={view === "table"}
              onClick={() => setView("table")}
            >
              <List size={14} />
              Table
            </Button>
            <Link className="button primary" href="/jobs">
              <Plus size={14} />
              Prepare from a job
            </Link>
          </div>
        }
      />
      <BrowserIntake />
      {query.isPending ? (
        <Skeleton />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : !query.data.packets.length ? (
        <Empty
          title="Your next chapter, one application at a time."
          description="Choose a saved job to generate a real application packet. Its fields, evidence, approvals and manual handoff will appear here."
          action={
            <Link className="button" href="/jobs">
              Explore saved jobs
              <ArrowUpRight size={14} />
            </Link>
          }
        />
      ) : view === "board" ? (
        <div className="kanban" aria-label="Application pipeline">
          {columns.map((column) => (
            <section className="kanban-column" key={column}>
              <div className="kanban-heading">
                {column}
                <Badge>
                  {
                    query.data.packets.filter(
                      (p) => pipelineColumn(p) === column,
                    ).length
                  }
                </Badge>
              </div>
              {query.data.packets
                .filter((p) => pipelineColumn(p) === column)
                .map((p) => (
                  <Link
                    href={`/applications/${p.id}`}
                    className="kanban-card"
                    key={p.id}
                  >
                    <h3>{p.snapshot.job_title}</h3>
                    <p>
                      {p.snapshot.company_name || "Company not established"}
                    </p>
                    <Badge
                      tone={
                        (p.readiness.blockers || []).length ? "amber" : "green"
                      }
                    >
                      {readable(p.readiness.state)}
                    </Badge>
                    <small>
                      Revision {p.revision} · {readable(p.platform)}
                    </small>
                  </Link>
                ))}
            </section>
          ))}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>JOB / COMPANY</th>
                <th>PROGRESS</th>
                <th>REVIEW</th>
                <th>UPDATED</th>
                <th>DETAILS</th>
              </tr>
            </thead>
            <tbody>
              {query.data.packets.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.snapshot.job_title}</strong>
                    <small>{p.snapshot.company_name}</small>
                  </td>
                  <td>{pipelineColumn(p)}</td>
                  <td>
                    <Badge>{readable(p.review_status)}</Badge>
                    <small>Revision {p.revision}</small>
                  </td>
                  <td>{dateLabel(p.updated_at)}</td>
                  <td>
                    <Link className="button" href={`/applications/${p.id}`}>
                      Review packet
                      <ArrowUpRight size={12} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.data && (
        <div className="pagination">
          <Button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 100))}
          >
            Previous
          </Button>
          <span>
            {offset + 1}–{offset + query.data.packets.length}
          </span>
          <Button
            disabled={query.data.packets.length < 100}
            onClick={() => setOffset(offset + 100)}
          >
            Next
          </Button>
        </div>
      )}
    </>
  );
}
