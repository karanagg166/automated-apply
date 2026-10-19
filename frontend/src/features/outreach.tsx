"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Check, Mail, Send } from "lucide-react";
import { api, dateLabel, patch, post, readable } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  Modal,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
type Draft = {
  id: string;
  subject: string;
  body: string;
  recipient_email: string | null;
  draft_revision: number;
  approval_status: string;
  delivery_status: string;
  created_at: string;
  send_attempt_id?: string | null;
  eligibility: {
    eligible_for_approval: boolean;
    blockers: string[];
    warnings: string[];
    approved?: boolean;
  };
  outbound_messages_sent: number;
};
type SendPreview = {
  draft_revision: number;
  approval_hash: string;
  sender_account_id: string;
  sender: string;
  recipient: string;
  subject: string;
  body: string;
  confirmation_token: string;
  confirmation_expires_at: string;
};
export function Outreach() {
  const query = useQuery({
    queryKey: ["drafts"],
    queryFn: () =>
      api<{ drafts: Draft[]; total: number }>("outreach/drafts?limit=100"),
  });
  const history = useQuery({
    queryKey: ["outreach-history"],
    queryFn: () =>
      api<{
        messages: Array<{ id: string; status: string; created_at: string }>;
      }>("outreach/history"),
  });
  return (
    <>
      <PageTitle
        eyebrow="BETTER CONVERSATIONS BEGIN WITH RELEVANCE"
        title="Make your introduction count."
        description="Professional, evidence-grounded outreach. Reviewed by you, sent only with your exact consent."
        actions={
          <Link className="button primary" href="/people">
            <Mail size={14} />
            Prepare from a contact
          </Link>
        }
      />
      <Notice>
        These are persisted local drafts. A draft or approval does not mean
        Gmail has accepted a message. Secondary Gmail authorization and an
        exact-content confirmation are required before sending.
      </Notice>
      {query.isPending ? (
        <Skeleton />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : query.data.drafts.length ? (
        <div className="company-grid">
          {query.data.drafts.map((d) => (
            <Link
              className="company-card"
              href={`/outreach/${d.id}`}
              key={d.id}
            >
              <div className="split">
                <span className="row-icon">
                  <Mail size={17} />
                </span>
                <Badge
                  tone={d.approval_status === "approved" ? "green" : "neutral"}
                >
                  {readable(d.approval_status)}
                </Badge>
              </div>
              <h3 className="spaced">{d.subject}</h3>
              <p className="company-description spaced">{d.body}</p>
              <div className="split">
                <small className="muted">
                  Revision {d.draft_revision} · {dateLabel(d.created_at)}
                </small>
                <Badge>{readable(d.delivery_status)}</Badge>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty
          title="A good introduction starts with a real person."
          description="Open a saved company’s contact evidence, then prepare a concise local draft from confirmed candidate projects and genuine company context."
          action={
            <Link href="/people" className="button">
              Review professional contacts
              <ArrowUpRight size={13} />
            </Link>
          }
        />
      )}
      <section className="panel spaced">
        <div className="panel-header">
          <h2>Send attempt history</h2>
          <Badge>NO AUTOMATIC RETRIES</Badge>
        </div>
        <div className="panel-body">
          {history.isError ? (
            <ErrorState error={history.error} />
          ) : history.data?.messages?.length ? (
            history.data.messages.map((a) => (
              <div className="evidence-item" key={a.id}>
                <strong>{readable(a.status)}</strong>
                <p>{dateLabel(a.created_at)}</p>
              </div>
            ))
          ) : (
            <p className="section-intro">
              No send attempts are recorded in this view. Unknown attempts must
              be reconciled manually; provider acceptance is distinct from
              delivery.
            </p>
          )}
        </div>
      </section>
    </>
  );
}
export function OutreachDetail({ id }: { id: string }) {
  const client = useQueryClient(),
    [subject, setSubject] = useState(""),
    [body, setBody] = useState(""),
    [preview, setPreview] = useState<SendPreview | null>(null),
    [exactConsent, setExactConsent] = useState(false),
    [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["draft", id],
    queryFn: () => api<Draft>(`outreach/drafts/${id}`),
  });
  const gmail = useQuery({
    queryKey: ["gmail-status"],
    queryFn: () =>
      api<{
        sending_enabled: boolean;
        send_capability: string;
        status: string;
      }>("integrations/gmail/status"),
  });
  useEffect(() => {
    if (query.data) {
      setSubject(query.data.subject);
      setBody(query.data.body);
      setPreview(null);
      setExactConsent(false);
    }
  }, [query.data]);
  const updated = () => {
    client.invalidateQueries({ queryKey: ["draft", id] });
    client.invalidateQueries({ queryKey: ["drafts"] });
    client.invalidateQueries({ queryKey: ["outreach-history"] });
  };
  const save = useMutation({
    mutationFn: () =>
      patch(`outreach/drafts/${id}`, {
        expected_revision: query.data!.draft_revision,
        subject,
        body,
      }),
    onSuccess: updated,
  });
  const approve = useMutation({
    mutationFn: () =>
      post(`outreach/drafts/${id}/approve`, {
        expected_revision: query.data!.draft_revision,
      }),
    onSuccess: updated,
  });
  const sendPreview = useMutation({
    mutationFn: () => post<SendPreview>(`outreach/drafts/${id}/send-preview`),
    onSuccess: (p) => {
      setPreview(p);
      setExactConsent(false);
    },
  });
  const send = useMutation({
    mutationFn: () =>
      post<{ status: string }>(`outreach/drafts/${id}/send`, {
        expected_revision: preview!.draft_revision,
        approval_hash: preview!.approval_hash,
        sender_account_id: preview!.sender_account_id,
        confirmation_token: preview!.confirmation_token,
        idempotency_key: `send_${id}_${preview!.draft_revision}`,
      }),
    onSuccess: (result) => {
      setNotice(
        `Recorded send attempt: ${readable(result.status)}. Inspect history; this is not a delivery claim.`,
      );
      setPreview(null);
      updated();
    },
  });
  const attempt = useQuery({
    queryKey: ["send-attempt", query.data?.send_attempt_id],
    queryFn: () =>
      api<Record<string, unknown>>(
        `outreach/send-attempts/${query.data!.send_attempt_id}`,
      ),
    enabled: !!query.data?.send_attempt_id,
  });
  if (query.isPending) return <Skeleton />;
  if (query.isError) return <ErrorState error={query.error} />;
  const d = query.data;
  const sendReady =
    gmail.data?.sending_enabled &&
    gmail.data.send_capability === "send_authorized" &&
    d.approval_status === "approved" &&
    !d.send_attempt_id;
  const dirty = subject !== d.subject || body !== d.body;
  return (
    <>
      <Link className="external" href="/outreach">
        <ArrowLeft size={13} />
        Back to outreach
      </Link>
      <div className="spaced">
        <PageTitle
          eyebrow="A CONSIDERED INTRODUCTION"
          title="Every word, reviewed."
          description={`Local draft · Revision ${d.draft_revision} · ${readable(d.approval_status)}`}
          actions={<Badge>{readable(d.delivery_status)}</Badge>}
        />
      </div>
      {notice && <Notice>{notice}</Notice>}
      <div className="detail-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Message preview</h2>
            <Badge>LOCAL DRAFT</Badge>
          </div>
          <div className="panel-body stack">
            <Field label="Recipient">
              <Input
                readOnly
                value={d.recipient_email || "Business mailbox unavailable"}
              />
            </Field>
            <Field label="Subject">
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                maxLength={255}
                disabled={!!d.send_attempt_id}
              />
            </Field>
            <Field label="Exact message">
              <textarea
                className="input"
                style={{ minHeight: 330 }}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                maxLength={5000}
                disabled={!!d.send_attempt_id}
              />
            </Field>
            <div className="actions">
              <Button
                disabled={!dirty || !subject || !body || !!d.send_attempt_id}
                busy={save.isPending}
                onClick={() => save.mutate()}
              >
                Save edits
              </Button>
              <Button
                variant="primary"
                disabled={
                  dirty ||
                  !d.eligibility.eligible_for_approval ||
                  !!d.send_attempt_id ||
                  d.approval_status === "approved"
                }
                busy={approve.isPending}
                onClick={() => approve.mutate()}
              >
                <Check size={13} />
                Approve exact content
              </Button>
            </div>
            {save.isError && <ErrorState error={save.error} />}{" "}
            {approve.isError && <ErrorState error={approve.error} />}
          </div>
        </section>
        <aside className="stack">
          <section className="panel">
            <div className="panel-header">
              <h2>Evidence & eligibility</h2>
            </div>
            <div className="panel-body">
              <p className="section-intro">
                The existing drafting service grounds approval in candidate
                projects, recipient identity, company context and fresh contact
                evidence.
              </p>
              {d.eligibility.blockers.length ? (
                <ul className="section-intro">
                  {d.eligibility.blockers.map((b) => (
                    <li key={b}>{readable(b)}</li>
                  ))}
                </ul>
              ) : (
                <Badge tone="green">Current evidence supports approval</Badge>
              )}
              {d.eligibility.warnings?.map((w) => (
                <Notice key={w}>{readable(w)}</Notice>
              ))}
              <Notice>
                Any message edit invalidates approval. Provider-reported email
                alone is not verified mailbox evidence.
              </Notice>
              <Link className="external" href="/people">
                Review contact and source evidence
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </section>
          <section className="panel">
            <div className="panel-header">
              <h2>Secondary Gmail</h2>
              <Mail size={17} className="muted" />
            </div>
            <div className="panel-body stack">
              {gmail.isError ? (
                <ErrorState error={gmail.error} />
              ) : (
                <>
                  <Badge tone={sendReady ? "green" : "amber"}>
                    {readable(gmail.data?.send_capability)}
                  </Badge>
                  <p className="section-intro">
                    {!gmail.data?.sending_enabled
                      ? "Gmail sending is disabled by server configuration."
                      : !sendReady
                        ? "Connect and authorize the designated secondary Gmail account, then approve this exact draft."
                        : "Request a short-lived send preview and review the exact sender, recipient and content."}
                  </p>
                  <Button
                    disabled={!sendReady || dirty}
                    busy={sendPreview.isPending}
                    onClick={() => sendPreview.mutate()}
                  >
                    <Send size={13} />
                    Review exact send
                  </Button>
                  <Link className="external" href="/connections">
                    Connection & scopes
                    <ArrowUpRight size={13} />
                  </Link>
                </>
              )}
              {sendPreview.isError && <ErrorState error={sendPreview.error} />}
            </div>
          </section>
          {d.send_attempt_id && (
            <section className="panel">
              <div className="panel-header">
                <h2>Attempt reconciliation</h2>
              </div>
              <div className="panel-body">
                <Notice>
                  An attempt is already reserved. Do not retry an uncertain
                  send. Inspect Gmail manually and preserve the attempt record.
                </Notice>
                {attempt.isError ? (
                  <ErrorState error={attempt.error} />
                ) : (
                  <pre className="source-text">
                    {JSON.stringify(attempt.data, null, 2)}
                  </pre>
                )}
              </div>
            </section>
          )}
        </aside>
      </div>
      <Modal
        open={!!preview}
        onOpenChange={(v) => !v && setPreview(null)}
        title="Confirm this exact email"
        description="This approval applies only to the displayed content, sender, recipient and draft revision."
      >
        {preview && (
          <div className="stack">
            <div className="evidence-item">
              <strong>From: {preview.sender}</strong>
              <p>To: {preview.recipient}</p>
              <p>Subject: {preview.subject}</p>
            </div>
            <pre className="source-text">{preview.body}</pre>
            <p className="section-intro">
              Confirmation expires{" "}
              {new Date(preview.confirmation_expires_at).toLocaleTimeString()}.
            </p>
            <label className="check-label">
              <input
                type="checkbox"
                checked={exactConsent}
                onChange={(e) => setExactConsent(e.target.checked)}
              />
              I authorize sending this exact message from my secondary Gmail
              account to this recipient now.
            </label>
            <Button
              variant="primary"
              disabled={
                !exactConsent ||
                Date.parse(preview.confirmation_expires_at) <= Date.now()
              }
              busy={send.isPending}
              onClick={() => send.mutate()}
            >
              <Send size={13} />
              Send this exact email
            </Button>
            {send.isError && <ErrorState error={send.error} />}
          </div>
        )}
      </Modal>
    </>
  );
}
