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
  delivery_attempt?: string | null;
  delivery_lease?: string | null;
};

export function isPendingExecutionQuestion(question: ExecutionQuestion) {
  return ["pending", "sent", "delivery_unknown", "delivery_not_sent"].includes(
    question.state,
  );
}

export function ExecutionQuestionDelivery({
  question: q,
  onSaved,
}: {
  question: ExecutionQuestion;
  onSaved: () => void;
}) {
  const [outcome, setOutcome] = useState("");
  const [messageId, setMessageId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (q.state !== "delivery_unknown" || !q.delivery_attempt) return null;
  const activeLease =
    !!q.delivery_lease && Date.parse(q.delivery_lease) > Date.now();
  const id = Number(messageId);
  const validId = /^\d+$/.test(messageId) && Number.isSafeInteger(id) && id > 0;
  const ready =
    !activeLease && (outcome === "not_sent" || (outcome === "sent" && validId));
  return (
    <form
      className="stack"
      aria-label="Record Telegram delivery outcome"
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy || !ready) return;
        setBusy(true);
        setError(null);
        try {
          await post(`execution/questions/${q.id}/delivery-reconciliation`, {
            expected_delivery_attempt: q.delivery_attempt,
            outcome,
            message_id: outcome === "sent" ? id : null,
          });
          onSaved();
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      <p>
        Record only a delivery outcome you verified. This saves your finding
        without resending the prompt or changing its application review.
      </p>
      <Field label="Verified Telegram delivery outcome">
        <Select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
          required
        >
          <option value="">Keep delivery unknown</option>
          <option value="sent">
            I verified the exact bot message was delivered
          </option>
          <option value="not_sent">I verified the prompt was not sent</option>
        </Select>
      </Field>
      {outcome === "sent" && (
        <Field label="Exact Telegram message ID">
          <Input
            inputMode="numeric"
            pattern="[0-9]+"
            value={messageId}
            onChange={(e) => setMessageId(e.target.value)}
            required
          />
        </Field>
      )}
      {activeLease && (
        <p>
          The original send is still being resolved. Wait for its current
          attempt to finish.
        </p>
      )}
      {error ? <ErrorState error={error} /> : null}
      <Button type="submit" busy={busy} disabled={busy || !ready}>
        Record delivery outcome
      </Button>
    </form>
  );
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
