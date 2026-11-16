"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, dateLabel, readable } from "@/lib/api";
import {
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  Select,
} from "@/components/ui";
import type { Contact } from "./people";

export type ContactDetail = Contact & {
  review_version?: string;
  human_review_notes?: string | null;
  evidence?: Array<{
    id: string;
    source: string;
    type: string;
    strength: string;
    url?: string | null;
    collected_at?: string | null;
    expires_at?: string | null;
    user_confirmed?: boolean;
  }>;
};

export function ContactReview({
  contact,
  onRefresh,
  onSaved,
}: {
  contact: ContactDetail;
  onRefresh: () => Promise<void>;
  onSaved: () => void;
}) {
  const [name, setName] = useState(contact.full_name);
  const [role, setRole] = useState(contact.role_title);
  const [suppressed, setSuppressed] = useState(contact.do_not_contact);
  const [reason, setReason] = useState(contact.suppression_reason || "");
  const [notes, setNotes] = useState(contact.human_review_notes || "");
  const [status, setStatus] = useState(contact.email_status);
  const [verification, setVerification] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<unknown>(null);
  const save = useMutation({
    retry: false,
    mutationFn: () => {
      setAttempted(true);
      const body: Record<string, unknown> = {
        full_name: name,
        role_title: role,
        do_not_contact: suppressed,
        suppression_reason: reason || null,
        human_review_notes: notes || null,
      };
      // Reviewing a name/suppression does not re-attest a saved mailbox claim.
      if (status !== contact.email_status || verification) {
        body.email_status = status;
        if (verification) body.verification_evidence_id = verification;
      }
      return api<ContactDetail>(`contacts/${contact.id}`, {
        method: "PATCH",
        headers: { "If-Match": contact.review_version || "" },
        body: JSON.stringify(body),
      });
    },
    onSuccess: onSaved,
  });
  const locked = attempted || save.isPending;
  return (
    <div className="spaced">
      <p>
        <strong>{contact.full_name}</strong> · {contact.role_title}
      </p>
      <p>
        Mailbox evidence:{" "}
        {readable(contact.email_evidence_status || contact.email_status)}
      </p>
      <p>
        Last checked {dateLabel(contact.last_checked_at)}. Sending is disabled.
      </p>
      {contact.evidence?.map((e) => (
        <article key={e.id} className="panel panel-body spaced">
          <strong>{readable(e.type)}</strong>
          <p>
            {readable(e.source)} · {readable(e.strength)} · observed{" "}
            {dateLabel(e.collected_at)} · expires {dateLabel(e.expires_at)}
          </p>
          {e.url && <External href={e.url}>Review evidence source</External>}
        </article>
      ))}
      {!contact.review_version ? (
        <Notice>
          Reload current contact evidence before making a correction.
        </Notice>
      ) : (
        <>
          <Field label="Reviewed contact name">
            <Input
              value={name}
              maxLength={255}
              disabled={locked}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Reviewed contact role">
            <Input
              value={role}
              maxLength={255}
              disabled={locked}
              onChange={(e) => setRole(e.target.value)}
            />
          </Field>
          <label className="check-row">
            <input
              type="checkbox"
              checked={suppressed}
              disabled={locked}
              onChange={(e) => setSuppressed(e.target.checked)}
            />
            Exclude this contact from outreach
          </label>
          <Field label="Exclusion reason">
            <Input
              value={reason}
              maxLength={1000}
              disabled={locked}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <Field label="Review notes">
            <textarea
              className="input"
              value={notes}
              maxLength={4000}
              disabled={locked}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
          <Field label="Reviewed mailbox status">
            <Select
              value={status}
              disabled={locked || contact.retention_expired}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="unknown">Unknown</option>
              <option value="candidate">Candidate pattern</option>
              <option value="provider_reported">Provider reported</option>
              <option value="verified">
                Verified with current mailbox evidence
              </option>
              <option value="invalid">Invalid</option>
            </Select>
          </Field>
          {status === "verified" && (
            <Field
              label="Mailbox verification evidence ID"
              hint="Required to change the mailbox status to verified. Identity evidence alone does not verify a mailbox."
            >
              <Input
                value={verification}
                disabled={locked}
                onChange={(e) => setVerification(e.target.value)}
              />
            </Field>
          )}
          <label className="check-row">
            <input
              type="checkbox"
              checked={reviewed}
              disabled={locked}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            I reviewed these contact corrections against the evidence
          </label>
          <Button
            disabled={
              locked ||
              !reviewed ||
              !name.trim() ||
              !role.trim() ||
              (status === "verified" &&
                status !== contact.email_status &&
                !verification)
            }
            busy={save.isPending}
            onClick={() => save.mutate()}
          >
            Save reviewed contact
          </Button>
        </>
      )}
      {save.isError && <ErrorState error={save.error} />}
      {save.isSuccess && (
        <Notice>
          Contact correction saved. Reload the evidence to review its current
          state.
        </Notice>
      )}
      {attempted && !save.isPending && (
        <Notice>
          Reload current evidence before another correction. A network error may
          have occurred after saving.
        </Notice>
      )}
      {refreshError != null && <ErrorState error={refreshError} />}
      <Button
        busy={refreshing}
        disabled={save.isPending}
        onClick={async () => {
          setRefreshing(true);
          setRefreshError(null);
          try {
            await onRefresh();
          } catch (error) {
            setRefreshError(error);
          } finally {
            setRefreshing(false);
          }
        }}
      >
        Reload current contact evidence
      </Button>
    </div>
  );
}
