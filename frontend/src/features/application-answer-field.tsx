"use client";
import { Badge, Button, ErrorState, Field, Notice } from "@/components/ui";
import { type ExtensionTask } from "@/features/extension-assistant";
import { patch, post, readable, type Schema } from "@/lib/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clipboard } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getFieldReviewStatus } from "./application-field-review";
type Packet = Schema<"PacketRead">;
export function AnswerField({
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
