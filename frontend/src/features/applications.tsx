"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Clipboard,
  FileCheck2,
  List,
  Plus,
  Rows3,
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
import { BrowserAssistant, BrowserIntake } from "@/features/browser-assistant";
type Packet = Schema<"PacketRead">;
export function pipelineColumn(
  packet: Pick<Packet, "tracking_state" | "lifecycle_state">,
) {
  const tracking: Record<string, string> = {
    interview_scheduled: "Interview",
    offer_received: "Offer",
    application_rejected: "Rejected",
    archived: "Archived",
  };
  return (
    tracking[packet.tracking_state] ||
    {
      created: "Preparing",
      preparing: "Preparing",
      submitting: "Submitting",
      submission_unknown: "Submission Unknown",
      needs_input: "Preparing",
      ready_for_review: "Ready for Review",
      reviewed: "Ready for Review",
      approved_for_manual_handoff: "Approved / Manual Handoff",
      external_application_opened: "Approved / Manual Handoff",
      user_reported_submitted: "Applied — User Reported",
      provider_confirmed_submitted: "Applied — Provider Confirmed",
      abandoned: "Archived",
      withdrawn: "Archived",
    }[packet.lifecycle_state] ||
    "Preparing"
  );
}
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
    "Ready for Review",
    "Submitting",
    "Submission Unknown",
    "Approved / Manual Handoff",
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
function AnswerField({
  field,
  packet,
  onReviewed,
  onDirty,
  checked,
}: {
  field: Schema<"PacketField">;
  packet: Packet;
  onReviewed: (checked: boolean) => void;
  onDirty: (id: string, dirty: boolean) => void;
  checked: boolean;
}) {
  const client = useQueryClient(),
    [answer, setAnswer] = useState(field.effective_answer || ""),
    [copied, setCopied] = useState(false);
  useEffect(
    () => setAnswer(field.effective_answer || ""),
    [field.effective_answer],
  );
  const dirty = answer !== (field.effective_answer || "");
  useEffect(() => onDirty(field.id, dirty), [field.id, dirty, onDirty]);
  useEffect(() => () => onDirty(field.id, false), [field.id, onDirty]);
  const edit = useMutation({
    mutationFn: () =>
      patch(`application-packets/${packet.id}/questions/${field.id}`, {
        expected_revision: packet.revision,
        answer,
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["packet", packet.id] }),
  });
  const generate = useMutation({
    mutationFn: () =>
      post(`application-packets/${packet.id}/questions/${field.id}/generate`, {
        expected_revision: packet.revision,
        rewrite: true,
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["packet", packet.id] }),
  });
  const terminal = [
    "user_reported_submitted",
    "provider_confirmed_submitted",
    "submitting",
    "submission_unknown",
  ].includes(packet.lifecycle_state);
  let selectedOptions: string[] = [];
  if (field.field_type === "multi_select") {
    try {
      const value = JSON.parse(answer || "[]");
      if (
        Array.isArray(value) &&
        value.every((item) => typeof item === "string")
      )
        selectedOptions = value;
    } catch {
      selectedOptions = [];
    }
  }
  return (
    <div className="evidence-item">
      <div className="split">
        <strong>
          {field.question}
          {field.required ? " *" : ""}
        </strong>
        <Badge
          tone={field.validation_status === "draft_ready" ? "green" : "amber"}
        >
          {readable(field.validation_status)}
        </Badge>
      </div>
      <p>
        {readable(field.category)} · source:{" "}
        {readable(field.provenance?.source)} · {field.max_characters} characters
        maximum
      </p>
      {!!field.options?.length && (
        <p>
          {field.field_type === "multi_select"
            ? "Available options"
            : "Choose one exact option"}
          : {field.options.join(" · ")}
        </p>
      )}
      {field.field_type === "file" ? (
        <Notice>
          Download the selected private resume and upload the actual file on the
          official website during manual handoff.
        </Notice>
      ) : field.field_type === "multi_select" ? (
        <fieldset>
          <legend>Review multiple selections</legend>
          <p>
            Review every selected and unselected option. Proposals use confirmed
            facts; other options remain unknown. Filling replaces existing
            selections on the website.
          </p>
          {(field.options || []).map((option) => (
            <label className="check-label" key={option}>
              <input
                type="checkbox"
                disabled={terminal}
                checked={selectedOptions.includes(option)}
                onChange={(event) => {
                  const chosen = new Set(selectedOptions);
                  if (event.target.checked) chosen.add(option);
                  else chosen.delete(option);
                  setAnswer(
                    JSON.stringify(
                      (field.options || []).filter((item) => chosen.has(item)),
                    ),
                  );
                }}
              />{" "}
              {option}
            </label>
          ))}
          <Button disabled={terminal} onClick={() => setAnswer("[]")}>
            Clear selections
          </Button>
        </fieldset>
      ) : (
        <Field label="Reviewable answer">
          <textarea
            className="input spaced"
            value={answer}
            maxLength={field.max_characters}
            disabled={terminal}
            onChange={(e) => setAnswer(e.target.value)}
          />
        </Field>
      )}
      {(field.missing_information || []).map((m) => (
        <p key={m}>{m}</p>
      ))}
      {dirty && (
        <Notice>
          Save answer changes before reviewing or filling this application.
        </Notice>
      )}
      <div className="actions spaced">
        {field.field_type !== "file" && (
          <>
            <Button
              disabled={
                terminal || !answer || answer === field.effective_answer
              }
              busy={edit.isPending}
              onClick={() => edit.mutate()}
            >
              Save answer
            </Button>
            <Button
              disabled={!field.effective_answer}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    field.effective_answer || "",
                  );
                  setCopied(true);
                } catch {
                  setCopied(false);
                }
              }}
            >
              <Clipboard size={12} />
              {copied ? "Copied" : "Copy answer"}
            </Button>
            {field.field_type !== "multi_select" &&
              ["project_explanation", "motivation", "free_text"].includes(
                field.category,
              ) && (
                <Button
                  busy={generate.isPending}
                  disabled={terminal}
                  onClick={() => generate.mutate()}
                >
                  Generate with configured AI
                </Button>
              )}
          </>
        )}
        {field.validation_status === "draft_ready" && (
          <label className="check-label">
            <input
              type="checkbox"
              disabled={terminal || dirty}
              checked={checked && !dirty}
              onChange={(e) => onReviewed(e.target.checked)}
            />
            I reviewed this exact answer
          </label>
        )}
      </div>
      {edit.isError && <ErrorState error={edit.error} />}{" "}
      {generate.isError && <ErrorState error={generate.error} />}
    </div>
  );
}
export function ApplicationDetail({ id }: { id: string }) {
  const [dirtyFields, setDirtyFields] = useState<string[]>([]);
  const onDirty = useCallback((fieldId: string, dirty: boolean) => {
    setDirtyFields((current) =>
      current.includes(fieldId) === dirty
        ? current
        : dirty
          ? [...current, fieldId]
          : current.filter((value) => value !== fieldId),
    );
  }, []);
  const client = useQueryClient(),
    [reviewed, setReviewed] = useState<string[]>([]),
    [resumeConfirmed, setResumeConfirmed] = useState(false),
    [destinationConfirmed, setDestinationConfirmed] = useState(false),
    [handoff, setHandoff] = useState<Schema<"Handoff"> | null>(null),
    [reportOpen, setReportOpen] = useState(false),
    [submissionConfirmed, setSubmissionConfirmed] = useState(false),
    [receipt, setReceipt] = useState(""),
    [question, setQuestion] = useState(""),
    [notice, setNotice] = useState("");
  const packet = useQuery({
    queryKey: ["packet", id],
    queryFn: () => api<Packet>(`application-packets/${id}`),
  });
  const events = useQuery({
    queryKey: ["packet-events", id],
    queryFn: () =>
      api<Schema<"ApplicationEventRead">[]>(`application-packets/${id}/events`),
  });
  useEffect(() => {
    setReviewed([]);
    setResumeConfirmed(false);
    setDestinationConfirmed(false);
    setHandoff(null);
  }, [packet.data?.revision]);
  const changed = (p?: unknown) => {
    if (p && typeof p === "object" && "revision" in p)
      client.setQueryData(["packet", id], p);
    client.invalidateQueries({ queryKey: ["packet", id] });
    client.invalidateQueries({ queryKey: ["packet-events", id] });
    client.invalidateQueries({ queryKey: ["packets"] });
    client.invalidateQueries({ queryKey: ["jobs"] });
    client.invalidateQueries({ queryKey: ["overview"] });
  };
  const review = useMutation({
    mutationFn: (action: "review" | "approve") =>
      post<Packet>(`application-packets/${id}/review`, {
        expected_revision: packet.data!.revision,
        action,
        reviewed_field_ids: reviewed,
        confirm_resume: resumeConfirmed,
        confirm_destination: destinationConfirmed,
      }),
    onSuccess: changed,
  });
  const openHandoff = useMutation({
    mutationFn: () =>
      api<Schema<"Handoff">>(`application-packets/${id}/handoff`),
    onSuccess: setHandoff,
  });
  const report = useMutation({
    mutationFn: () =>
      post(`application-packets/${id}/report-submission`, {
        expected_revision: packet.data!.revision,
        idempotency_key: `report_${id}_${packet.data!.revision}`,
        human_confirmed: true,
        confirmation: "I submitted this application on the official website",
        receipt_reference: receipt || null,
      }),
    onSuccess: () => {
      changed();
      setReportOpen(false);
      setNotice(
        "Submission recorded as user reported, with unverified receipt evidence.",
      );
    },
  });
  const track = useMutation({
    mutationFn: (tracking_state: Schema<"TrackingInput">["tracking_state"]) =>
      patch(`application-packets/${id}/tracking`, {
        expected_revision: packet.data!.revision,
        tracking_state,
      }),
    onSuccess: changed,
  });
  const add = useMutation({
    mutationFn: () =>
      post(`application-packets/${id}/questions`, {
        expected_revision: packet.data!.revision,
        questions: [
          {
            question,
            category: "free_text",
            field_type: "textarea",
            required: true,
          },
        ],
      }),
    onSuccess: () => {
      setQuestion("");
      changed();
    },
  });
  const selectResume = useMutation({
    mutationFn: (resume_resource_id: string) =>
      patch(`application-packets/${id}`, {
        expected_revision: packet.data!.revision,
        resume_resource_id,
      }),
    onSuccess: changed,
  });
  const refresh = useMutation({
    mutationFn: () =>
      patch(`application-packets/${id}`, {
        expected_revision: packet.data!.revision,
        refresh_saved_data: true,
      }),
    onSuccess: changed,
  });
  if (packet.isPending) return <Skeleton />;
  if (packet.isError) return <ErrorState error={packet.error} />;
  const p = packet.data;
  const terminal = [
    "user_reported_submitted",
    "provider_confirmed_submitted",
    "submitting",
    "submission_unknown",
  ].includes(p.lifecycle_state);
  return (
    <>
      <Link href="/applications" className="external">
        <ArrowLeft size={13} />
        Back to pipeline
      </Link>
      <div className="spaced">
        <PageTitle
          eyebrow="A THOUGHTFUL APPLICATION"
          title={p.snapshot.job_title}
          description={`${p.snapshot.company_name || "Company unverified"} · ${readable(p.platform)} · Revision ${p.revision}`}
          actions={
            <Badge tone={terminal ? "green" : "amber"}>
              {pipelineColumn(p)}
            </Badge>
          }
        />
      </div>
      <BrowserAssistant packet={p} hasUnsavedAnswers={dirtyFields.length > 0} />
      {notice && <Notice>{notice}</Notice>}
      <div className="detail-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Application fields</h2>
            <Badge>{p.fields.length} fields</Badge>
          </div>
          <div className="panel-body">
            <p className="section-intro">
              Review the exact answers and their provenance. Any edit changes
              the packet revision and invalidates previous approval.
            </p>
            {p.fields.map((field) => (
              <AnswerField
                key={field.id}
                field={field}
                packet={p}
                checked={
                  reviewed.includes(field.id) ||
                  field.review_status === "reviewed"
                }
                onReviewed={(checked) =>
                  setReviewed((r) =>
                    checked
                      ? [...new Set([...r, field.id])]
                      : r.filter((x) => x !== field.id),
                  )
                }
                onDirty={onDirty}
              />
            ))}
            {!terminal && (
              <form
                className="stack spaced"
                onSubmit={(e) => {
                  e.preventDefault();
                  add.mutate();
                }}
              >
                <Field label="Add an actual question from the application form">
                  <Input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    required
                    maxLength={2000}
                  />
                </Field>
                <Button type="submit" disabled={!question} busy={add.isPending}>
                  <Plus size={13} />
                  Add question
                </Button>
                {add.isError && <ErrorState error={add.error} />}
              </form>
            )}
            <div className="divider" />
            <h3>Review & approve</h3>
            <Field label="Resume variant">
              <Select
                aria-label="Resume variant"
                value={p.snapshot.resume.selected?.resource_id || ""}
                disabled={terminal || selectResume.isPending}
                onChange={(e) =>
                  e.target.value && selectResume.mutate(e.target.value)
                }
              >
                <option value="">Select a confirmed resume…</option>
                {p.snapshot.resume.alternatives?.map((r) => (
                  <option
                    key={r.resource_id}
                    value={r.resource_id}
                    disabled={!r.confirmed}
                  >
                    {r.label}
                    {r.confirmed ? "" : " · needs owner confirmation"}
                  </option>
                ))}
              </Select>
            </Field>
            {selectResume.isError && <ErrorState error={selectResume.error} />}

            <p className="section-intro spaced">{p.snapshot.resume.reason}</p>
            {p.snapshot.resume.selected?.download_path && (
              <a
                href={p.snapshot.resume.selected.download_path}
                className="button"
              >
                Download selected private resume
              </a>
            )}
            {p.snapshot.resume.selected?.url &&
              !p.snapshot.resume.selected.download_path && (
                <External href={p.snapshot.resume.selected.url}>
                  Review selected resume
                </External>
              )}
            <div className="stack spaced">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={resumeConfirmed}
                  onChange={(e) => setResumeConfirmed(e.target.checked)}
                  disabled={terminal}
                />
                I reviewed the selected resume variant.
              </label>
              <External href={p.snapshot.destination.application_url}>
                Inspect application destination
              </External>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={destinationConfirmed}
                  onChange={(e) => setDestinationConfirmed(e.target.checked)}
                  disabled={terminal}
                />
                I verified this is the official application destination.
              </label>
              <div className="actions">
                <Button
                  disabled={terminal || dirtyFields.length > 0}
                  busy={review.isPending}
                  onClick={() => review.mutate("review")}
                >
                  <Check size={13} />
                  Save field review
                </Button>
                <Button
                  variant="primary"
                  disabled={
                    terminal ||
                    dirtyFields.length > 0 ||
                    !resumeConfirmed ||
                    !destinationConfirmed
                  }
                  busy={review.isPending}
                  onClick={() => review.mutate("approve")}
                >
                  <FileCheck2 size={13} />
                  Approve current packet
                </Button>
              </div>
            </div>
            {review.isError && <ErrorState error={review.error} />}
          </div>
        </section>
        <aside className="stack">
          <section className="panel">
            <div className="panel-header">
              <h2>Readiness & handoff</h2>
            </div>
            <div className="panel-body">
              <Badge
                tone={(p.readiness.blockers || []).length ? "amber" : "green"}
              >
                {readable(p.readiness.state)}
              </Badge>
              <ul className="section-intro spaced">
                {(p.readiness.blockers || []).map((b) => (
                  <li key={b}>{readable(b)}</li>
                ))}
              </ul>
              {(p.readiness.warnings || []).map((w) => (
                <Notice key={w}>{w}</Notice>
              ))}
              <Notice>
                Submission mode: Manual Handoff. Resume uploads and portal
                actions are completed on the official website.
              </Notice>
              <div className="stack">
                <Button
                  disabled={terminal || p.approved_revision !== p.revision}
                  busy={openHandoff.isPending}
                  onClick={() => openHandoff.mutate()}
                >
                  Open manual handoff
                  <ArrowUpRight size={13} />
                </Button>
                <Button
                  disabled={
                    (!terminal && p.approved_revision !== p.revision) ||
                    terminal
                  }
                  onClick={() => {
                    setSubmissionConfirmed(false);
                    setReportOpen(true);
                  }}
                >
                  Report manual completion
                </Button>
                <Button
                  disabled={terminal}
                  busy={refresh.isPending}
                  onClick={() => refresh.mutate()}
                >
                  Refresh profile & saved evidence
                </Button>
              </div>
              {openHandoff.isError && <ErrorState error={openHandoff.error} />}{" "}
              {refresh.isError && <ErrorState error={refresh.error} />}{" "}
              {handoff && (
                <div className="evidence-item">
                  <strong>Ready for manual handoff</strong>
                  <p>
                    Open the official site, copy the reviewed fields, and upload
                    your resume. This does not submit anything.
                  </p>
                  <External href={handoff.application_url}>
                    Open application website
                  </External>
                  <ul className="section-intro spaced">
                    {handoff.manual_steps.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-header">
              <h2>Keep your record current</h2>
            </div>
            <div className="panel-body">
              <Field label="Tracking status">
                <Select
                  aria-label="Tracking status"
                  value={p.tracking_state}
                  disabled={track.isPending}
                  onChange={(e) =>
                    track.mutate(
                      e.target
                        .value as Schema<"TrackingInput">["tracking_state"],
                    )
                  }
                >
                  {[
                    ["not_applied", "Not applied"],
                    ["application_incomplete", "Incomplete"],
                    ["interview_scheduled", "Interview scheduled"],
                    ["offer_received", "Offer received"],
                    ["application_rejected", "Rejected"],
                    ["archived", "Archived"],
                  ].map(([v, l]) => (
                    <option value={v} key={v}>
                      {l}
                    </option>
                  ))}
                </Select>
              </Field>
              {track.isError && <ErrorState error={track.error} />}
            </div>
          </section>
          <section className="panel">
            <div className="panel-header">
              <h2>Application history</h2>
            </div>
            <div className="panel-body">
              {events.isError ? (
                <ErrorState error={events.error} />
              ) : (
                <div className="timeline">
                  {events.data?.map((event) => (
                    <div key={event.id}>
                      {readable(event.event_type)}
                      <time>
                        {dateLabel(event.created_at)} · revision{" "}
                        {event.packet_revision}
                      </time>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </aside>
      </div>
      <Modal
        open={reportOpen}
        onOpenChange={setReportOpen}
        title="Record what you completed"
        description="This is your report of a manual submission. It is saved separately from provider-confirmed evidence."
      >
        <div className="stack">
          <Field label="Receipt reference · optional">
            <Input
              value={receipt}
              onChange={(e) => setReceipt(e.target.value)}
              maxLength={255}
            />
          </Field>
          <label className="check-label">
            <input
              type="checkbox"
              checked={submissionConfirmed}
              onChange={(e) => setSubmissionConfirmed(e.target.checked)}
            />
            I submitted this application on the official website.
          </label>
          <Button
            variant="primary"
            disabled={!submissionConfirmed}
            busy={report.isPending}
            onClick={() => report.mutate()}
          >
            Record user-reported submission
          </Button>
          {report.isError && <ErrorState error={report.error} />}
        </div>
      </Modal>
    </>
  );
}
