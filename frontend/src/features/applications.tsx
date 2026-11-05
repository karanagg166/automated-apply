"use client";
import {
  ExecutionQuestionAnswer,
  isPendingExecutionQuestion,
  type ExecutionQuestion,
} from "@/features/execution-question-answer";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
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
import {
  ExtensionAssistant,
  challengeMessages,
  retainedFieldCount,
  type ExtensionTask,
} from "@/features/extension-assistant";
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
      needs_input: "Needs Input",
      ready_for_review: "Ready for Review",
      reviewed: "Ready for Review",
      approved_for_manual_handoff: "Approved / Manual Handoff",
      external_application_opened: "External Application Opened",
      submitting: "Submitting",
      submission_unknown: "Submission Unknown",
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
export type FieldReviewStatus =
  | "Ready"
  | "Needs Answer"
  | "Pending Review"
  | "Manual Only"
  | "Challenge Required"
  | "Failed Validation";

export function getFieldReviewStatus({
  field,
  task,
  isReviewed,
  isDirty,
  exceedsLimit,
}: {
  field: Schema<"PacketField">;
  task?: ExtensionTask | null;
  isReviewed: boolean;
  isDirty?: boolean;
  exceedsLimit?: boolean;
}): {
  status: FieldReviewStatus;
  nextAction: string;
  tone: "green" | "amber" | "neutral" | "red";
} {
  // Receipt field IDs address a DOM snapshot, not PacketField UUIDs. The API
  // provides no mapping, so receipt verification belongs in the history only.
  // 2. Failed Validation
  const hasValidationError = Boolean(
    field.validation_status === "validation_failed" || exceedsLimit,
  );
  if (hasValidationError) {
    return {
      status: "Failed Validation",
      nextAction: exceedsLimit
        ? "Shorten answer to satisfy character or word limit constraints."
        : "Correct the answer to pass format and validation checks.",
      tone: "red",
    };
  }

  // 3. Challenge Required
  const isChallenge = Boolean(
    task?.challenge_state === "CHALLENGE_BLOCKING" ||
    task?.challenge_state === "WIDGET_PRESENT_UNVERIFIED" ||
    task?.challenge_state === "UNKNOWN" ||
    task?.state === "CHALLENGE_REQUIRED" ||
    (field.category as string) === "challenge" ||
    (field.category as string) === "captcha",
  );
  if (isChallenge) {
    return {
      status: "Challenge Required",
      nextAction:
        "Complete the security challenge on the official page before filling.",
      tone: "red",
    };
  }

  // 4. Manual Only
  const isManualOnly = Boolean(
    field.field_type === "file" ||
    field.validation_status === "file_upload_required" ||
    field.category === "resume_upload",
  );
  if (isManualOnly) {
    return {
      status: "Manual Only",
      nextAction:
        field.field_type === "file" || field.category === "resume_upload"
          ? "Download approved resume PDF and upload manually on employer portal."
          : "Complete manually on the employer portal.",
      tone: "neutral",
    };
  }

  // 5. Needs Answer
  const isExpired = Boolean(
    field.provenance?.answer_expires_at &&
    Date.parse(field.provenance.answer_expires_at) <= Date.now(),
  );
  const isNeedsAnswer = Boolean(
    field.validation_status === "needs_input" ||
    field.validation_status === "provider_unavailable" ||
    (!field.effective_answer && field.required) ||
    isExpired,
  );
  if (isNeedsAnswer) {
    return {
      status: "Needs Answer",
      nextAction: "Provide an answer below or queue for Telegram.",
      tone: "amber",
    };
  }

  // 6. Ready (checked by owner or already reviewed in packet, not dirty)
  if (isReviewed && !isDirty) {
    return {
      status: "Ready",
      nextAction: "Ready to fill in Chrome once packet is approved.",
      tone: "green",
    };
  }

  // 7. Pending Review
  return {
    status: "Pending Review",
    nextAction: "Review proposed answer and mark reviewed.",
    tone: "amber",
  };
}

function AnswerField({
  field,
  packet,
  onReviewed,
  onDirty,
  checked,
  task,
}: {
  field: Schema<"PacketField">;
  packet: Packet;
  onReviewed: (checked: boolean) => void;
  onDirty: (id: string, dirty: boolean) => void;
  checked: boolean;
  task?: ExtensionTask | null;
}) {
  const client = useQueryClient(),
    [answer, setAnswer] = useState(field.effective_answer || ""),
    [copied, setCopied] = useState(false);
  const savedAnswer = useRef(field.effective_answer || "");
  useEffect(() => {
    const updated = field.effective_answer || "";
    const previous = savedAnswer.current;
    setAnswer((draft) => (draft === previous ? updated : draft));
    savedAnswer.current = updated;
  }, [field.effective_answer]);
  const dirty = answer !== (field.effective_answer || "");
  useEffect(() => onDirty(field.id, dirty), [field.id, dirty, onDirty]);
  useEffect(() => () => onDirty(field.id, false), [field.id, onDirty]);
  const edit = useMutation({
    mutationFn: (submitted: string) =>
      patch(`application-packets/${packet.id}/questions/${field.id}`, {
        expected_revision: packet.revision,
        answer: submitted,
      }),
    onSuccess: (_data, submitted) => {
      savedAnswer.current = submitted;
      return client.invalidateQueries({ queryKey: ["packet", packet.id] });
    },
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

  const charCount = answer.length;
  const wordCount = answer.trim()
    ? answer.trim().split(/\s+/).filter(Boolean).length
    : 0;
  const exceedsCharLimit = charCount > field.max_characters;
  const exceedsWordLimit =
    typeof field.max_words === "number" && field.max_words > 0
      ? wordCount > field.max_words
      : false;
  const exceedsLimit = exceedsCharLimit || exceedsWordLimit;
  const isNarrative = [
    "experience",
    "project_explanation",
    "motivation",
    "free_text",
  ].includes(field.category);

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

  const isReviewed = Boolean(checked || field.review_status === "reviewed");
  const reviewStatus = getFieldReviewStatus({
    field,
    task,
    isReviewed,
    isDirty: dirty,
    exceedsLimit,
  });

  return (
    <div className="evidence-item" data-field-id={field.id}>
      {/* 1. Field */}
      <div className="split">
        <div>
          <small
            className="muted"
            style={{
              fontWeight: 600,
              fontSize: "9px",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
            }}
          >
            Field
          </small>
          <div style={{ marginTop: "2px" }}>
            <strong>
              {field.question}
              {field.required ? " *" : ""}
            </strong>
          </div>
        </div>
        <div className="actions">
          <Badge tone={isNarrative ? "amber" : "neutral"}>
            {readable(field.category)}
          </Badge>
          <Badge tone="neutral">{readable(field.field_type)}</Badge>
        </div>
      </div>
      {!!field.options?.length && (
        <p style={{ margin: "4px 0" }}>
          {field.field_type === "multi_select"
            ? "Available options"
            : "Choose one exact option"}
          : {field.options.join(" · ")}
        </p>
      )}
      {/* 2. Proposed Answer */}
      <div style={{ marginTop: "10px" }}>
        <small
          className="muted"
          style={{
            fontWeight: 600,
            fontSize: "9px",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          Proposed Answer
        </small>
        {field.field_type === "file" ? (
          <Notice>
            Download the selected private resume and upload the actual file on
            the official website during manual handoff. The dedicated browser
            can attach the approved canonical PDF when upload checks pass.
            Chrome extension attachments remain manual.
          </Notice>
        ) : field.field_type === "multi_select" ? (
          <fieldset>
            <legend>Review multiple selections</legend>
            <p>
              Review every selected and unselected option. Proposals use
              confirmed facts; other options remain unknown. Filling replaces
              existing selections on the website.
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
                        (field.options || []).filter((item) =>
                          chosen.has(item),
                        ),
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
            <div className="split">
              <small className={exceedsLimit ? "missing-skills" : "muted"}>
                {charCount} / {field.max_characters} characters · {wordCount}{" "}
                {field.max_words ? `/ ${field.max_words} ` : ""}words
                {exceedsCharLimit
                  ? " (exceeds character limit)"
                  : exceedsWordLimit
                    ? " (exceeds word limit)"
                    : ""}
              </small>
            </div>
          </Field>
        )}
        {field.provenance?.error_code && (
          <Notice>
            {field.provenance.error_code === "rate_limit_exceeded"
              ? "AI rate limit reached. Draft your answer manually or retry later."
              : field.provenance.error_code === "model_unavailable"
                ? "AI model is currently unavailable. Enter your answer manually."
                : field.provenance.error_code === "missing_candidate_facts"
                  ? "Required candidate facts were not found in your profile. Real qualifications cannot be invented."
                  : `AI generation notice: ${readable(field.provenance.error_code)}`}
          </Notice>
        )}
        {field.validation_status === "provider_unavailable" && (
          <Notice>
            AI provider is unavailable for this answer. Please provide your
            answer manually.
          </Notice>
        )}
        {(field.missing_information || []).length > 0 && (
          <Notice>
            Missing candidate facts:{" "}
            {(field.missing_information || []).join(" · ")}. Real qualifications
            and employment history cannot be invented. Enter manually or update
            your profile.
          </Notice>
        )}
      </div>
      {/* 3. Evidence */}
      <div style={{ marginTop: "10px" }}>
        <small
          className="muted"
          style={{
            fontWeight: 600,
            fontSize: "9px",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          Evidence &amp; Provenance
        </small>
        <div
          className="split"
          style={{ alignItems: "center", marginTop: "0.25rem" }}
        >
          <p>
            source: {readable(field.provenance?.source)}
            {field.provenance?.provider && (
              <span>
                {" "}
                · provider: {field.provenance.provider}
                {field.provenance.model ? ` (${field.provenance.model})` : ""}
              </span>
            )}
          </p>
          <div className="tag-list">
            {((field.provenance?.source as string) === "owner_answer" ||
              field.provenance?.source === "human") && (
              <Badge tone="green">Human-approved (exact context)</Badge>
            )}
            {field.provenance?.source === "approved_answer" && (
              <Badge tone="green">Reused from approved answers</Badge>
            )}
            {((field.provenance?.source as string) === "profile_fact" ||
              field.provenance?.source === "candidate_profile") && (
              <Badge tone="neutral">Verified profile fact</Badge>
            )}
            {((field.provenance?.source as string) === "approved_project" ||
              field.provenance?.source === "candidate_resource") && (
              <Badge tone="neutral">Approved project evidence</Badge>
            )}
            {field.provenance?.source === "deterministic_extractive" && (
              <Badge tone="neutral">Deterministic extractive</Badge>
            )}
          </div>
        </div>
        {!!field.provenance?.evidence_references?.length && (
          <details className="evidence-details spaced">
            <summary>
              {field.provenance.evidence_references.length} evidence
              reference(s)
            </summary>
            <ul>
              {field.provenance.evidence_references.map((ref, idx) => (
                <li key={idx}>
                  <small>
                    {readable(ref.source_type)}: {ref.source_id}
                  </small>
                </li>
              ))}
            </ul>
          </details>
        )}
        {field.provenance?.answer_expires_at && (
          <small
            className="muted"
            style={{ display: "block", marginTop: "4px" }}
          >
            Answer expires:{" "}
            {new Date(field.provenance.answer_expires_at).toLocaleString()}
          </small>
        )}
      </div>
      {/* 4 & 5. Status and Next Action */}
      <div
        style={{
          marginTop: "10px",
          padding: "8px 10px",
          background: "var(--surface-sunken, rgba(0,0,0,0.02))",
          borderRadius: "6px",
        }}
      >
        <div className="split" style={{ alignItems: "flex-start" }}>
          <div>
            <small
              className="muted"
              style={{
                fontWeight: 600,
                fontSize: "9px",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              Status
            </small>
            <div style={{ marginTop: "3px" }}>
              <Badge tone={reviewStatus.tone}>{reviewStatus.status}</Badge>
            </div>
          </div>
          <div style={{ maxWidth: "65%" }}>
            <small
              className="muted"
              style={{
                fontWeight: 600,
                fontSize: "9px",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              Next Action
            </small>
            <p
              style={{
                margin: "3px 0 0",
                fontSize: "11px",
                fontWeight: 550,
              }}
            >
              {reviewStatus.nextAction}
            </p>
          </div>
        </div>
      </div>
      {dirty && (
        <Notice>
          Save answer changes before reviewing or filling this application.
        </Notice>
      )}
      {/* Action Buttons & Review Checkbox */}
      <div
        className="actions spaced"
        style={{
          marginTop: "12px",
          borderTop: "1px solid var(--line)",
          paddingTop: "10px",
        }}
      >
        {field.field_type !== "file" && (
          <>
            <Button
              disabled={
                terminal ||
                exceedsLimit ||
                !answer ||
                answer === field.effective_answer
              }
              busy={edit.isPending}
              onClick={() => edit.mutate(answer)}
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
            {field.field_type !== "multi_select" && isNarrative && (
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
              disabled={terminal || dirty || exceedsLimit || !answer.trim()}
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
const QUESTION_TEMPLATES = [
  {
    label: "Select a standard question template…",
    question: "",
    category: "free_text" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Why this company? (Narrative)",
    question: "Why are you interested in joining our company?",
    category: "motivation" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Why this role? (Narrative)",
    question: "Why are you a good fit for this role?",
    category: "motivation" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Describe your project (Narrative)",
    question: "Describe a complex project you led and its technical impact.",
    category: "project_explanation" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Hardest technical problem (Narrative)",
    question:
      "What is the hardest technical problem you have faced and how did you solve it?",
    category: "experience" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Relevant achievements (Narrative)",
    question: "What are your most relevant technical achievements?",
    category: "experience" as const,
    field_type: "textarea" as const,
  },
  {
    label: "Notice period (Factual)",
    question: "What is your official notice period?",
    category: "notice_period" as const,
    field_type: "text" as const,
  },
  {
    label: "Preferred location (Factual)",
    question: "What is your preferred work location or remote preference?",
    category: "personal_information" as const,
    field_type: "text" as const,
  },
] as const;

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
    [questionOptions, setQuestionOptions] = useState(""),
    [category, setCategory] =
      useState<Schema<"QuestionInput">["category"]>("free_text"),
    [fieldType, setFieldType] =
      useState<Schema<"QuestionInput">["field_type"]>("textarea"),
    [templateIdx, setTemplateIdx] = useState(0),
    [notice, setNotice] = useState("");
  const [answerSuccess, setAnswerSuccess] = useState("");
  useEffect(() => {
    if (!dirtyFields.length) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirtyFields.length]);

  const packet = useQuery({
    queryKey: ["packet", id],
    queryFn: () => api<Packet>(`application-packets/${id}`),
  });
  const events = useQuery({
    queryKey: ["packet-events", id],
    queryFn: () =>
      api<Schema<"ApplicationEventRead">[]>(`application-packets/${id}/events`),
  });
  const executionQuestions = useQuery({
    queryKey: ["execution-questions", id],
    queryFn: () => api<ExecutionQuestion[]>("execution/questions"),
    refetchInterval: 5000,
  });
  const extensionTask = useQuery({
    queryKey: ["extension-task", id],
    queryFn: ({ signal }) =>
      api<ExtensionTask | null>(`browser/extension-tasks/application/${id}`, {
        signal,
      }),
    retry: false,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  useEffect(() => {
    if (
      Array.isArray(executionQuestions.data) &&
      executionQuestions.data.some(
        (q) =>
          q.packet_id === id &&
          q.state === "answered" &&
          q.packet_revision >= (packet.data?.revision ?? Infinity),
      )
    ) {
      void client.invalidateQueries({ queryKey: ["packet", id] });
      void client.invalidateQueries({ queryKey: ["packet-events", id] });
    }
  }, [executionQuestions.data, packet.data?.revision, client, id]);
  useEffect(() => {
    setReviewed([]);
    setResumeConfirmed(false);
    setDestinationConfirmed(false);
    setHandoff(null);
  }, [packet.data?.revision]);
  const changed = (p?: unknown) => {
    if (p && typeof p === "object" && "revision" in p)
      client.setQueryData(["packet", id], p);
    client.invalidateQueries({ queryKey: ["execution-questions", id] });
    client.invalidateQueries({ queryKey: ["packet", id] });
    client.invalidateQueries({ queryKey: ["packet-events", id] });
    client.invalidateQueries({ queryKey: ["packets"] });
    client.invalidateQueries({ queryKey: ["jobs"] });
    client.invalidateQueries({ queryKey: ["overview"] });
  };
  const askOwner = useMutation({
    mutationFn: (fieldId: string) =>
      post(`execution/packets/${id}/questions/${fieldId}`, {
        expected_revision: packet.data!.revision,
      }),
    onSuccess: () => {
      changed();
      setNotice(
        "Question queued for your bound private Telegram chat. Reply to that exact message.",
      );
    },
  });
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
  const updateLifecycle = useMutation({
    mutationFn: (lifecycle_state: Schema<"TrackingInput">["lifecycle_state"]) =>
      patch(`application-packets/${id}/tracking`, {
        expected_revision: packet.data!.revision,
        lifecycle_state,
      }),
    onSuccess: changed,
  });
  const requiresOptions = [
    "multiple_choice",
    "multi_select",
    "yes_no",
  ].includes(fieldType);
  const actualOptions = questionOptions
    .split("\n")
    .map((option) => option.trim())
    .filter(Boolean);
  const invalidOptions =
    requiresOptions &&
    (!actualOptions.length ||
      actualOptions.length > 50 ||
      actualOptions.some((option) => option.length > 200));
  const add = useMutation({
    mutationFn: () =>
      post(`application-packets/${id}/questions`, {
        expected_revision: packet.data!.revision,
        questions: [
          {
            question,
            category,
            field_type: fieldType,
            required: true,
            options: requiresOptions ? actualOptions : [],
          },
        ],
      }),
    onSuccess: () => {
      setQuestion("");
      setQuestionOptions("");
      setCategory("free_text");
      setFieldType("textarea");
      setTemplateIdx(0);
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

  const task = extensionTask.data;
  const identityMatches =
    task?.application_id === id && task?.job_id === p.job_id;
  const currentTask = task && identityMatches ? task : null;
  const taskStale = Boolean(
    currentTask && currentTask.packet_revision !== p.revision,
  );
  const challengeState =
    extensionTask.isError || taskStale
      ? "UNKNOWN"
      : currentTask?.challenge_state || "UNKNOWN";
  const formChanged = Boolean(
    currentTask &&
    currentTask.current_url &&
    currentTask.target_url &&
    currentTask.current_url !== currentTask.target_url,
  );

  const reviewedCount = p.fields.filter(
    (f) => f.review_status === "reviewed",
  ).length;

  const pendingExecQuestion = Array.isArray(executionQuestions.data)
    ? executionQuestions.data.find(
        (q) =>
          q.packet_id === id &&
          q.packet_revision === p.revision &&
          isPendingExecutionQuestion(q),
      )
    : undefined;

  const unresolved = p.fields.some(
    (field) =>
      field.field_type !== "file" &&
      ((field.required &&
        (!field.effective_answer ||
          field.validation_status === "needs_input")) ||
        (field.provenance?.answer_expires_at &&
          Date.parse(field.provenance.answer_expires_at) <= Date.now())),
  );
  const approved = p.approved_revision === p.revision && !p.readiness.stale;
  const nextAction = extensionTask.isError
    ? "Connection unverified. Refresh saved extension status before continuing in Chrome."
    : dirtyFields.length
      ? "Save your edited answers before continuing."
      : currentTask?.challenge_state === "UNKNOWN"
        ? challengeMessages.UNKNOWN
        : pendingExecQuestion
          ? "Answer the missing questions, then review the updated packet."
          : unresolved
            ? "Answer the missing questions, then review the updated packet."
            : currentTask?.challenge_state === "CHALLENGE_BLOCKING" ||
                currentTask?.challenge_state === "WIDGET_PRESENT_UNVERIFIED"
              ? "Complete security verification on the employer portal, then inspect and review again in Chrome."
              : currentTask?.state === "PAUSED"
                ? "Application paused. Resume in the Chrome extension panel once ready."
                : terminal
                  ? "Check the recorded submission status and its evidence below."
                  : p.readiness.stale || taskStale
                    ? "Refresh the packet and review the changed context."
                    : approved
                      ? currentTask?.state === "FILLED_VERIFIED"
                        ? "Review verified retained fields and complete remaining manual steps on official portal."
                        : currentTask?.next_action
                          ? currentTask.next_action
                          : "Review the actual form and approve supported fields in the browser assistant."
                      : "Review answers, confirm the resume and destination, then approve the current packet.";

  const progressSteps = [
    { label: "Packet prepared", done: true },
    {
      label: "Required answers resolved",
      done: !pendingExecQuestion && !unresolved,
    },
    { label: "Current packet approved", done: approved },
    {
      label: "Retained fill recorded for current packet",
      done: Boolean(
        !taskStale &&
        currentTask?.verified_receipts?.some(
          (r) =>
            r.packet_revision === p.revision &&
            (!currentTask?.profile_binding_id ||
              r.profile_binding_id === currentTask.profile_binding_id) &&
            retainedFieldCount(r) > 0,
        ),
      ),
    },
    {
      label: "Official portal submission (Manual)",
      done: [
        "user_reported_submitted",
        "provider_confirmed_submitted",
      ].includes(p.lifecycle_state),
    },
  ];

  const timelineItems = [
    ...(events.data || []).map((e) => ({
      key: `event-${e.id}`,
      title: readable(e.event_type),
      description: "",
      timestamp: e.created_at,
      revision: e.packet_revision,
    })),
    ...(currentTask?.verified_receipts || []).map((r, idx) => ({
      key: `receipt-${r.plan_id || idx}`,
      title:
        retainedFieldCount(r) > 0
          ? "Fill verified (retained after blur)"
          : "Fill receipt — manual review required",
      description: `${r.profile_binding_id ? `Chrome profile ${r.profile_binding_id}; ` : ""}${retainedFieldCount(r)} field(s) verified retained (${r.verification_method}); ${r.results.map((res) => `${res.field_id}: ${res.status}`).join(", ") || "outcome unknown"}. Page-local IDs belong to this receipt's snapshot; submission unconfirmed.`,
      timestamp: r.recorded_at,
      revision: r.packet_revision,
    })),
  ].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));

  const lastVerified = currentTask?.verified_receipts
    ?.filter(
      (r) =>
        (!currentTask?.profile_binding_id ||
          r.profile_binding_id === currentTask.profile_binding_id) &&
        retainedFieldCount(r) > 0,
    )
    .at(-1);
  const lastSuccessfulActivity = lastVerified
    ? `${dateLabel(lastVerified.recorded_at)} · Verified retained fill`
    : events.data?.length
      ? `${dateLabel(events.data[0].created_at)} · ${readable(events.data[0].event_type)}`
      : `${dateLabel(p.updated_at)} · Packet saved`;

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
            <div className="actions">
              <Badge tone={terminal ? "green" : "amber"}>
                {pipelineColumn(p)}
              </Badge>
              {p.approved_revision ? (
                <Badge tone="green">Approved rev {p.approved_revision}</Badge>
              ) : (
                <Badge tone="neutral">Unapproved revision</Badge>
              )}
            </div>
          }
        />
      </div>

      {/* Visual Form-Fill Progress Bar */}
      <div
        className="panel panel-body"
        style={{ padding: "0.75rem 1rem", marginTop: "0.5rem" }}
        aria-label="Application Progress"
      >
        <div className="tag-list" style={{ justifyContent: "space-between" }}>
          {progressSteps.map((s, idx) => (
            <Badge key={idx} tone={s.done ? "green" : "neutral"}>
              {s.done ? "✓ " : "○ "}
              {s.label}
            </Badge>
          ))}
        </div>
      </div>

      {/* Dynamic Next Action Callout */}
      <section
        className="panel panel-body"
        style={{
          background: "var(--surface-sunken, rgba(0,0,0,0.02))",
          borderLeft: "4px solid var(--accent, #2563eb)",
          marginTop: "0.75rem",
        }}
        aria-label="Next Action Guidance"
      >
        <div className="split">
          <div>
            <strong
              style={{
                color: "var(--accent, #2563eb)",
                fontSize: "0.75rem",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              NEXT ACTION
            </strong>
            <p style={{ margin: "0.25rem 0 0", fontWeight: 600 }}>
              {nextAction}
            </p>
          </div>
          <div className="actions">
            <Badge tone={terminal ? "green" : "neutral"}>
              {readable(p.lifecycle_state)}
            </Badge>
            {currentTask && (
              <Badge
                tone={
                  currentTask.browser_connection === "connected"
                    ? "green"
                    : "neutral"
                }
              >
                Chrome: {readable(currentTask.state)}
              </Badge>
            )}
          </div>
        </div>
      </section>

      {taskStale && currentTask && (
        <Notice>
          Extension task belongs to packet revision{" "}
          {currentTask.packet_revision}, but the saved application packet is at
          revision {p.revision}. Your saved answers and in-progress edits are
          preserved. Re-inspect this step in Chrome to synchronize.
        </Notice>
      )}
      {formChanged && currentTask && (
        <Notice>
          Form page changed: observed {currentTask.current_url} (target was{" "}
          {currentTask.target_url}). Your saved answers are preserved. Inspect
          the current step in Chrome.
        </Notice>
      )}
      {dirtyFields.length > 0 && (
        <Notice>
          You have unsaved answer edits. Save your answers before resuming or
          inspecting.
        </Notice>
      )}

      {!terminal &&
        !p.readiness.stale &&
        p.fields
          .filter(
            (field) =>
              field.field_type !== "file" &&
              ((field.required && !field.effective_answer) ||
                (field.provenance?.answer_expires_at &&
                  Date.parse(field.provenance?.answer_expires_at) <=
                    Date.now())),
          )
          .map((field) => (
            <div className="panel panel-body spaced" key={`ask-${field.id}`}>
              <p>{field.question}</p>
              <Button
                disabled={
                  askOwner.isPending ||
                  (!!pendingExecQuestion &&
                    Date.parse(pendingExecQuestion.expires_at) > Date.now())
                }
                onClick={() => askOwner.mutate(field.id)}
              >
                Ask me on Telegram: {field.question}
              </Button>
            </div>
          ))}
      {askOwner.isError && <ErrorState error={askOwner.error} />}

      {/* In-Dashboard Telegram Question Answering Card */}
      {pendingExecQuestion && (
        <div
          className="panel panel-body stack spaced"
          style={{
            borderLeft: "4px solid var(--amber, #f59e0b)",
            background: "var(--surface-sunken, rgba(0,0,0,0.02))",
            marginTop: "0.75rem",
          }}
          aria-label="Waiting for Your Answer"
        >
          <div className="split">
            <Badge tone="amber">Waiting for Your Answer</Badge>
            <small className="muted">Backend paused preparation</small>
          </div>
          <h3>{pendingExecQuestion.question}</h3>
          <p className="text-xs muted">
            Answer the existing question here. The application follows its saved
            review or automatic policy.
          </p>
          <ExecutionQuestionAnswer
            key={`${pendingExecQuestion.id}:${pendingExecQuestion.packet_revision}`}
            question={pendingExecQuestion}
            onSaved={() => {
              setAnswerSuccess(
                pendingExecQuestion.queue_work_id
                  ? "Answer saved. The worker will refresh the account, resume, job and original form before continuing this application."
                  : "Answer saved. Review and approve the updated packet before filling.",
              );
              changed();
            }}
          />
        </div>
      )}
      {executionQuestions.isError && (
        <ErrorState error={executionQuestions.error} />
      )}
      {answerSuccess && <Notice>{answerSuccess}</Notice>}

      {p.lifecycle_state === "needs_input" && (
        <Notice>
          <div className="split">
            <span>
              This application stopped because required factual answers or
              evidence are missing.
            </span>
            <Link className="button primary" href="/needs-input">
              Resolve in &apos;Needs your input&apos; queue
              <ArrowUpRight size={13} />
            </Link>
          </div>
        </Notice>
      )}

      <div className="detail-grid">
        <section className="panel panel-body">
          <div className="split">
            <div>
              <h3>Application destination</h3>
              <p>
                {p.snapshot.destination.application_url ? (
                  <External href={p.snapshot.destination.application_url}>
                    {p.snapshot.destination.application_url}
                  </External>
                ) : (
                  <span className="muted">No direct URL recorded</span>
                )}
              </p>
              <small>
                Kind: {readable(p.snapshot.destination.kind)} · Confidence:{" "}
                {readable(p.snapshot.destination.source_confidence)}
              </small>
              {(p.snapshot.destination.warnings || []).map((w) => (
                <Notice key={w}>{w}</Notice>
              ))}
            </div>
            <div>
              <h3>Selected resume</h3>
              <p>
                <strong>
                  {p.snapshot.resume.selected?.label || "No resume selected"}
                </strong>{" "}
                <Badge
                  tone={
                    p.snapshot.resume.selected?.confirmed ? "green" : "amber"
                  }
                >
                  {p.snapshot.resume.selected?.confirmed
                    ? "Confirmed"
                    : "Needs confirmation"}
                </Badge>
              </p>
              <small className="muted">
                File upload is manual on employer portal.
              </small>
            </div>
          </div>
          <div className="split spaced">
            <small>
              Candidate profile: v{p.candidate_profile_version} · Source
              platform: {readable(p.snapshot.source_platform)}
              {p.snapshot.original_job_url && (
                <span>
                  {" "}
                  ·{" "}
                  <External href={p.snapshot.original_job_url}>
                    Original posting
                  </External>
                </span>
              )}
            </small>
            <small>
              Reviewed questions: {reviewedCount} of {p.fields.length} · Last
              updated: {dateLabel(p.updated_at)}
            </small>
          </div>
        </section>
      </div>

      <div className="detail-grid" style={{ marginTop: "0.75rem" }}>
        <section
          className="panel panel-body"
          aria-label="Required Manual Actions"
        >
          <h3>Required manual actions</h3>
          <ul
            className="section-intro spaced"
            style={{ paddingLeft: "1.2rem", margin: "0.5rem 0" }}
          >
            <li>
              <strong>Resume upload:</strong> Download the approved canonical
              PDF and upload it directly on the employer portal (file uploads
              are completed manually on the website).
            </li>
            <li>
              <strong>Security challenge / CAPTCHA:</strong> Interactive
              challenges must be solved manually on the official page. Automated
              solving is not permitted.
            </li>
            <li>
              <strong>Manual-only fields:</strong> Self-identification (e.g.
              gender, race) and non-standard custom controls must be completed
              manually.
            </li>
            <li>
              <strong>Portal submission:</strong> Automated submission is
              strictly disabled. Review your completed form and submit manually
              on the employer portal.
            </li>
          </ul>
        </section>

        <section
          className="panel panel-body"
          aria-label="Security & Verification State"
        >
          <h3>Security &amp; verification status</h3>
          <p style={{ margin: "0.25rem 0 0.5rem" }}>
            {currentTask
              ? challengeMessages[challengeState]
              : "Security state unverified. Inspect the exact application in Chrome before continuing."}
          </p>
          <div className="split" style={{ marginTop: "0.5rem" }}>
            <small className="muted">
              Challenge status: <strong>{challengeState}</strong>
            </small>
            <Badge
              tone={
                challengeState === "NONE" ||
                challengeState === "MANUALLY_RESOLVED_AND_SITE_VERIFIED"
                  ? "green"
                  : "amber"
              }
            >
              {challengeState === "NONE" ? "Clear" : readable(challengeState)}
            </Badge>
          </div>
          <div
            style={{
              marginTop: "0.75rem",
              borderTop: "1px solid var(--line)",
              paddingTop: "0.5rem",
            }}
          >
            <small className="muted">
              Preserved fields: Existing website answers and manual inputs are
              preserved and never overwritten by Automated Apply.
            </small>
          </div>
        </section>
      </div>

      <ExtensionAssistant
        packet={p}
        hasUnsavedAnswers={dirtyFields.length > 0}
      />
      <BrowserAssistant
        packet={p}
        hasUnsavedAnswers={dirtyFields.length > 0}
        onRefresh={() => refresh.mutate()}
      />
      {notice && <Notice>{notice}</Notice>}

      {p.lifecycle_state === "submission_unknown" && (
        <Notice>
          Submission outcome is unknown due to an ambiguous dispatch attempt. Do
          NOT resubmit blindly. Reconcile this attempt by checking your email or
          the application portal for confirmation. The backend tracker rejects a
          new manual submission report while an ambiguous attempt remains
          unresolved.
        </Notice>
      )}

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
                task={taskStale || extensionTask.isError ? null : currentTask}
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
                <h3>Add a question from the application form</h3>
                <Field label="Choose from common question templates">
                  <Select
                    value={templateIdx}
                    onChange={(e) => {
                      const idx = Number(e.target.value);
                      setTemplateIdx(idx);
                      const tmpl = QUESTION_TEMPLATES[idx];
                      if (tmpl && tmpl.question) {
                        setQuestion(tmpl.question);
                        setCategory(tmpl.category);
                        setFieldType(tmpl.field_type);
                      }
                    }}
                  >
                    {QUESTION_TEMPLATES.map((tmpl, idx) => (
                      <option key={idx} value={idx}>
                        {tmpl.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Question text">
                  <Input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    required
                    maxLength={2000}
                    placeholder="Enter question text from application form…"
                  />
                </Field>
                <div className="split">
                  <Field label="Question category">
                    <Select
                      value={category}
                      onChange={(e) =>
                        setCategory(
                          e.target.value as Schema<"QuestionInput">["category"],
                        )
                      }
                    >
                      <option value="free_text">Free text</option>
                      <option value="motivation">
                        Motivation (Why company / role)
                      </option>
                      <option value="project_explanation">
                        Project explanation / Problem solving
                      </option>
                      <option value="technical_skills">Technical skills</option>
                      <option value="notice_period">Notice period</option>
                      <option value="personal_information">
                        Personal info / Preferred location
                      </option>
                      <option value="experience">Experience</option>
                    </Select>
                  </Field>
                  <Field label="Field type">
                    <Select
                      value={fieldType}
                      onChange={(e) =>
                        setFieldType(
                          e.target
                            .value as Schema<"QuestionInput">["field_type"],
                        )
                      }
                    >
                      <option value="textarea">Textarea (Narrative)</option>
                      <option value="text">Single-line text (Factual)</option>
                      <option value="multiple_choice">Multiple choice</option>
                      <option value="multi_select">Multi select</option>
                      <option value="yes_no">Yes / No</option>
                    </Select>
                  </Field>
                </div>
                {requiresOptions && (
                  <Field
                    label="Actual form options (one per line)"
                    hint="Copy the options from the application form. Supply up to 50 options, each at most 200 characters."
                  >
                    <textarea
                      className="input"
                      value={questionOptions}
                      onChange={(event) =>
                        setQuestionOptions(event.target.value)
                      }
                      maxLength={10049}
                      required
                    />
                  </Field>
                )}
                <Button
                  type="submit"
                  disabled={!question || invalidOptions}
                  busy={add.isPending}
                >
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
                {p.approved_revision === p.revision && !terminal && (
                  <Button
                    busy={updateLifecycle.isPending}
                    onClick={() =>
                      updateLifecycle.mutate("external_application_opened")
                    }
                  >
                    Record external application opened
                  </Button>
                )}
                <Button
                  disabled={
                    (!terminal && p.approved_revision !== p.revision) ||
                    terminal ||
                    p.lifecycle_state === "submission_unknown"
                  }
                  onClick={() => {
                    setSubmissionConfirmed(false);
                    setReportOpen(true);
                  }}
                >
                  Report manual completion
                </Button>
                {p.lifecycle_state === "submission_unknown" && (
                  <small className="missing-skills">
                    Manual completion reporting is disabled until the ambiguous
                    dispatch attempt is reconciled.
                  </small>
                )}
                <Button
                  disabled={terminal}
                  busy={refresh.isPending}
                  onClick={() => refresh.mutate()}
                >
                  Refresh profile & saved evidence
                </Button>
              </div>
              {openHandoff.isError && <ErrorState error={openHandoff.error} />}{" "}
              {updateLifecycle.isError && (
                <ErrorState error={updateLifecycle.error} />
              )}{" "}
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
              {timelineItems.length > 0 && (
                <Badge>{timelineItems.length} events</Badge>
              )}
            </div>
            <div className="panel-body">
              {events.isError ? (
                <ErrorState error={events.error} />
              ) : (
                <div className="timeline">
                  {timelineItems.map((item) => (
                    <div key={item.key}>
                      <strong>{item.title}</strong>
                      {item.description && (
                        <p
                          style={{
                            margin: "2px 0",
                            fontSize: "10px",
                            color: "var(--muted)",
                          }}
                        >
                          {item.description}
                        </p>
                      )}
                      <time>
                        {dateLabel(item.timestamp)} · revision {item.revision}
                      </time>
                    </div>
                  ))}
                  {!timelineItems.length &&
                    events.data?.map((event) => (
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
              {lastSuccessfulActivity && (
                <div
                  style={{
                    marginTop: "12px",
                    borderTop: "1px solid var(--line)",
                    paddingTop: "8px",
                  }}
                >
                  <small className="muted">
                    <strong>Last successful activity:</strong>{" "}
                    {lastSuccessfulActivity}
                  </small>
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
