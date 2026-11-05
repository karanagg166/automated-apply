"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { Button, ErrorState, Field, Input, Select } from "@/components/ui";

export type ExecutionQuestion = {
  id: string;
  packet_id: string;
  packet_revision: number;
  execution_id: string;
  queue_work_id?: string;
  question: string;
  state: string;
  answer: string | null;
  employer: string;
  role: string;
  answer_type?: string;
  options?: string[];
  expires_at: string;
  answer_expires_at?: string | null;
};

export function isPendingExecutionQuestion(question: ExecutionQuestion) {
  return ["pending", "sent", "delivery_unknown"].includes(question.state);
}

export function ExecutionQuestionAnswer({
  question: q,
  onSaved,
}: {
  question: ExecutionQuestion;
  onSaved: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [slot, setSlot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const availability = q.answer_type === "availability";
  const choices = q.options || [];
  const needsSlot =
    availability && (!choices.length || answer.toLowerCase() !== "no");
  const expired = Date.parse(q.expires_at) <= Date.now();
  return (
    <form
      className="stack"
      aria-label="Answer application question"
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy || expired) return;
        setBusy(true);
        setError(null);
        try {
          const value = availability
            ? choices.length
              ? needsSlot
                ? `${answer} | ${slot.trim()}`
                : answer
              : slot.trim()
            : answer.trim();
          await post(`execution/questions/${q.id}/answer`, {
            expected_revision: q.packet_revision,
            answer: value,
          });
          setAnswer("");
          setSlot("");
          onSaved();
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      {choices.length > 0 ? (
        <Field label="Your verified answer">
          <Select
            required
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
          >
            <option value="">Choose an option…</option>
            {choices.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </Field>
      ) : !availability ? (
        <Field label="Your verified answer">
          <Input
            required
            maxLength={4000}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
          />
        </Field>
      ) : null}
      {needsSlot && (
        <Field label="Interview date, time and time zone">
          <Input
            required
            placeholder="2026-11-15T10:00 Asia/Kolkata"
            value={slot}
            onChange={(e) => setSlot(e.target.value)}
          />
        </Field>
      )}
      <p className="muted">
        {q.queue_work_id
          ? "Saving resumes this application after fresh account, resume, job and original-form checks. Answer reuse stays off."
          : "Saving requires a fresh packet review and approval before filling. Answer reuse stays off."}
      </p>
      {expired && (
        <p>This question expired. Ask a current question before answering.</p>
      )}
      {error ? <ErrorState error={error} /> : null}
      <Button
        type="submit"
        variant="primary"
        busy={busy}
        disabled={
          busy ||
          expired ||
          (choices.length > 0 && !answer) ||
          (needsSlot ? !slot.trim() : !answer.trim())
        }
      >
        Submit Answer from Dashboard
      </Button>
    </form>
  );
}
