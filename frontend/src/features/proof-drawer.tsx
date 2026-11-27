"use client";
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, post } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  Skeleton,
} from "@/components/ui";
import { stateTone } from "@/features/autopilot-forms";
import { istStamp, portalName } from "@/features/applied-model";

export type ProofAnswer = {
  question: string;
  answer: string;
  source?: string | null;
  tier_label?: string | null;
  similarity?: number | null;
  cache_entry_id?: string | null;
};
export type ProofTiming = {
  posted_at?: string | null;
  discovered_at?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  submitted_at?: string | null;
  first_mover_lag_seconds?: number | null;
};
/** GET v2/applications/{id}/proof (milestone 2 contract). */
export type ApplicationProof = {
  application: {
    id: string;
    platform: string;
    external_job_id: string;
    company_name?: string | null;
    role_title?: string | null;
    job_url?: string | null;
    state: string;
    reason?: string | null;
    applied_at?: string | null;
  };
  timing: ProofTiming;
  answers: ProofAnswer[];
  resume_variant_used?: string | null;
  screenshot?: string | null;
  mail_events: Array<{
    kind: string;
    subject?: string | null;
    sender?: string | null;
    received_at?: string | null;
  }>;
  outreach_draft?: {
    id: string;
    status: string;
    recipient_email?: string | null;
    created_at?: string | null;
  } | null;
  email_verified: boolean;
  confirmed_at?: string | null;
  needs_reconciliation: boolean;
};

export const proofKey = (id: string) => ["v2-application-proof", id] as const;

/** "1h 4m", "45s"; null-safe. */
export function lagLabel(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  if (s < 86400)
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function tierTone(label?: string | null) {
  if (!label) return "neutral" as const;
  if (label.startsWith("Tier 1") || label.startsWith("Tier 2"))
    return "green" as const;
  if (label.startsWith("Tier 3") || label.startsWith("HITL"))
    return "neutral" as const;
  if (label.startsWith("Tier 4")) return "amber" as const;
  return "neutral" as const;
}

const TIMELINE: ReadonlyArray<[keyof ProofTiming, string]> = [
  ["posted_at", "Posted"],
  ["discovered_at", "Discovered"],
  ["queued_at", "Queued"],
  ["started_at", "Started"],
  ["submitted_at", "Submitted"],
];

function AnswerRow({ answer }: { answer: ProofAnswer }) {
  const client = useQueryClient();
  const flag = useMutation({
    mutationFn: () =>
      post(`v2/semantic-cache/${answer.cache_entry_id}/quarantine`, {
        reason: "flagged_from_receipt",
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["v2-cache-studio"] }),
  });
  return (
    <tr>
      <td className="reason-cell">{answer.question}</td>
      <td className="reason-cell">{answer.answer}</td>
      <td>
        <Badge tone={tierTone(answer.tier_label)}>
          {answer.tier_label || answer.source || "Unknown"}
        </Badge>
      </td>
      <td>
        {answer.cache_entry_id ? (
          flag.isSuccess ? (
            <Badge tone="red">Quarantined</Badge>
          ) : (
            <Button
              variant="danger"
              busy={flag.isPending}
              aria-label={`Flag bad answer and quarantine: ${answer.question}`}
              onClick={() => flag.mutate()}
            >
              Flag bad answer
            </Button>
          )
        ) : (
          <span className="muted small-print">—</span>
        )}
        {flag.isError && (
          <small className="portal-hint" role="alert">
            {flag.error.message}
          </small>
        )}
      </td>
    </tr>
  );
}

function Reconcile({ proof }: { proof: ApplicationProof }) {
  const client = useQueryClient();
  const [confirm, setConfirm] = useState("");
  const id = proof.application.id;
  const act = useMutation({
    mutationFn: (action: "confirm_applied" | "release_not_submitted") =>
      post(`v2/applications/${id}/reconcile`, {
        action,
        confirm: action === "release_not_submitted" ? confirm : "APPLIED",
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: proofKey(id) });
      client.invalidateQueries({ queryKey: ["v2-pipeline"] });
    },
  });
  return (
    <section className="detail-section" aria-labelledby="proof-reconcile">
      <h3 id="proof-reconcile">Reconcile unknown submission</h3>
      <p className="muted small-print">
        The Apply click happened but no confirmation was seen
        {proof.needs_reconciliation ? " for over 24 hours" : ""}. Check the
        portal, then record what you found.
      </p>
      <div className="actions">
        <Button
          variant="primary"
          busy={act.isPending}
          onClick={() => act.mutate("confirm_applied")}
        >
          I see it applied
        </Button>
      </div>
      <Field
        label='Type RELEASE to mark "not submitted"'
        hint="Frees today's quota slot and lets the worker apply again."
      >
        <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <Button
        variant="danger"
        busy={act.isPending}
        disabled={confirm !== "RELEASE"}
        onClick={() => act.mutate("release_not_submitted")}
      >
        Release: not submitted
      </Button>
      {act.isError && <ErrorState error={act.error} />}
      {act.isSuccess && <Notice>Saved.</Notice>}
    </section>
  );
}

function ProofBody({ proof }: { proof: ApplicationProof }) {
  const app = proof.application;
  return (
    <div className="stack">
      <div className="tag-list">
        <Badge tone={stateTone(app.state)}>
          {app.state.replaceAll("_", " ")}
        </Badge>
        <Badge tone="neutral">{portalName(app.platform)}</Badge>
        {proof.email_verified && (
          <Badge tone="green">
            Email verified{" "}
            {proof.confirmed_at ? istStamp(proof.confirmed_at) : ""}
          </Badge>
        )}
        {proof.needs_reconciliation && (
          <Badge tone="red">Needs reconciliation</Badge>
        )}
      </div>
      <External href={app.job_url}>Open job posting</External>
      <section className="detail-section" aria-labelledby="proof-timing">
        <h3 id="proof-timing">Timing</h3>
        <dl className="worker-facts">
          {TIMELINE.map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>
                {istStamp(proof.timing[key] as string | null | undefined)}
              </dd>
            </div>
          ))}
          <div>
            <dt>First-mover lag</dt>
            <dd>{lagLabel(proof.timing.first_mover_lag_seconds)}</dd>
          </div>
        </dl>
      </section>
      <section className="detail-section" aria-labelledby="proof-answers">
        <h3 id="proof-answers">Form Q&amp;A audit</h3>
        {proof.answers.length === 0 ? (
          <p className="muted">No screening questions were filled.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">
                Submitted answers with source tier
              </caption>
              <thead>
                <tr>
                  <th scope="col">QUESTION</th>
                  <th scope="col">VALUE SUBMITTED</th>
                  <th scope="col">SOURCE</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {proof.answers.map((answer, i) => (
                  <AnswerRow key={`${answer.question}-${i}`} answer={answer} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="detail-section" aria-labelledby="proof-artifacts">
        <h3 id="proof-artifacts">Receipt</h3>
        <dl className="worker-facts">
          <div>
            <dt>Resume variant</dt>
            <dd>{proof.resume_variant_used || "Default"}</dd>
          </div>
          <div>
            <dt>Confirmation screenshot</dt>
            <dd>
              {proof.screenshot ? (
                <code>{proof.screenshot}</code>
              ) : (
                "None captured"
              )}
            </dd>
          </div>
          <div>
            <dt>Outreach draft</dt>
            <dd>
              {proof.outreach_draft
                ? `${proof.outreach_draft.status} · ${proof.outreach_draft.recipient_email ?? "no recipient"}`
                : "None"}
            </dd>
          </div>
        </dl>
      </section>
      <section className="detail-section" aria-labelledby="proof-mail">
        <h3 id="proof-mail">Linked email</h3>
        {proof.mail_events.length === 0 ? (
          <p className="muted">
            No confirmation, assessment or recruiter email linked yet.
          </p>
        ) : (
          <ul className="stack">
            {proof.mail_events.map((mail, i) => (
              <li key={i}>
                <Badge tone={mail.kind === "REJECTED" ? "red" : "green"}>
                  {mail.kind.replaceAll("_", " ")}
                </Badge>{" "}
                {mail.subject || "(no subject)"}{" "}
                <small className="muted">
                  {mail.sender} · {istStamp(mail.received_at)}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>
      {app.state === "SUBMISSION_UNKNOWN" && <Reconcile proof={proof} />}
    </div>
  );
}

export function ProofDrawer({
  applicationId,
  onClose,
}: {
  applicationId: string;
  onClose: () => void;
}) {
  const proof = useQuery({
    queryKey: proofKey(applicationId),
    queryFn: () =>
      api<ApplicationProof>(`v2/applications/${applicationId}/proof`),
  });
  const title = proof.data
    ? `${proof.data.application.company_name || "Unknown company"} — ${proof.data.application.role_title || "Untitled role"}`
    : "Application proof";
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content proof-drawer">
          <Dialog.Title className="dialog-title">{title}</Dialog.Title>
          <Dialog.Description className="muted">
            Proof receipt: timing, every answer submitted and linked email.
          </Dialog.Description>
          <Dialog.Close
            className="icon-button dialog-close"
            aria-label="Close proof receipt"
          >
            <X size={20} />
          </Dialog.Close>
          {proof.isPending ? (
            <Skeleton />
          ) : proof.isError ? (
            <ErrorState error={proof.error} retry={() => proof.refetch()} />
          ) : (
            <ProofBody proof={proof.data} />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
