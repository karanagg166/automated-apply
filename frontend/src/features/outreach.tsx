"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Check, Mail } from "lucide-react";
import { api, dateLabel, patch, post, readable } from "@/lib/api";
import {
  prepareReviewedDraftReplacement,
  readDraftAttempt,
  recoverLocalDraft,
} from "./outreach-draft-attempt";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  GmailPermissionBadge,
  Field,
  Input,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
type Draft = {
  id: string;
  contact_id?: string | null;
  job_id?: string | null;
  sent_at?: string | null;
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
export function Outreach() {
  const query = useQuery({
    queryKey: ["drafts"],
    queryFn: () =>
      api<{ drafts: Draft[]; total: number }>("outreach/drafts?limit=100"),
  });
  return (
    <>
      <PageTitle
        eyebrow="BETTER CONVERSATIONS BEGIN WITH RELEVANCE"
        title="Make your introduction count."
        description="Prepare and review professional outreach drafts using verified evidence."
        actions={
          <Link className="button primary" href="/people">
            <Mail size={14} />
            Prepare from a contact
          </Link>
        }
      />
      <GmailPermissionBadge />
      <Notice>
        These drafts are saved locally. Gmail supports reading and unsent draft
        creation through the separate mailbox workspace. Sending is disabled.
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
    </>
  );
}
export function OutreachDetail({ id }: { id: string }) {
  const client = useQueryClient(),
    router = useRouter(),
    [subject, setSubject] = useState(""),
    [body, setBody] = useState(""),
    [replacementReviewed, setReplacementReviewed] = useState(false);
  const query = useQuery({
    queryKey: ["draft", id],
    queryFn: () => api<Draft>(`outreach/drafts/${id}`),
  });
  useEffect(() => {
    if (query.data) {
      setSubject(query.data.subject);
      setBody(query.data.body);
      setReplacementReviewed(false);
    }
  }, [query.data]);
  const updated = () => {
    client.invalidateQueries({ queryKey: ["draft", id] });
    client.invalidateQueries({ queryKey: ["drafts"] });
  };
  const save = useMutation({
    retry: false,
    mutationFn: () =>
      patch(`outreach/drafts/${id}`, {
        expected_revision: query.data!.draft_revision,
        subject,
        body,
      }),
    onSuccess: updated,
  });
  const approve = useMutation({
    retry: false,
    mutationFn: () =>
      post(`outreach/drafts/${id}/approve`, {
        expected_revision: query.data!.draft_revision,
      }),
    onSuccess: updated,
  });
  const replacement = useMutation({
    retry: false,
    mutationFn: async () => {
      const reviewed = query.data;
      if (!replacementReviewed || !reviewed?.contact_id || reviewed.job_id)
        throw new Error(
          "Review the saved contact draft before preparing a new introduction.",
        );
      const current = await api<Draft>(`outreach/drafts/${id}`);
      if (
        current.id !== reviewed.id ||
        current.draft_revision !== reviewed.draft_revision ||
        current.contact_id !== reviewed.contact_id ||
        current.job_id
      )
        throw new Error(
          "The saved draft changed. Reload and review its current revision.",
        );
      const retained = readDraftAttempt(reviewed.contact_id);
      if (!retained || retained.draftId === current.id)
        prepareReviewedDraftReplacement({
          id: current.id,
          contact_id: reviewed.contact_id,
          draft_revision: current.draft_revision,
          delivery_status: current.delivery_status,
          send_attempt_id: current.send_attempt_id,
          sent_at: current.sent_at,
        });
      return recoverLocalDraft(reviewed.contact_id);
    },
    onSuccess: (draft) => {
      updated();
      router.push(`/outreach/${draft.id}`);
    },
    onError: () => client.invalidateQueries({ queryKey: ["draft", id] }),
  });
  if (query.isPending) return <Skeleton />;
  if (query.isError) return <ErrorState error={query.error} />;
  const d = query.data;
  const dirty = subject !== d.subject || body !== d.body;
  const immutable =
    !!d.send_attempt_id || !!d.sent_at || d.delivery_status !== "not_attempted";
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
                disabled={immutable}
              />
            </Field>
            <Field label="Exact message">
              <textarea
                className="input"
                style={{ minHeight: 330 }}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                maxLength={5000}
                disabled={immutable}
              />
            </Field>
            <div className="actions">
              <Button
                disabled={
                  !dirty ||
                  !subject ||
                  !body ||
                  immutable ||
                  replacement.isPending
                }
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
                  immutable ||
                  replacement.isPending ||
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
            {d.contact_id && !d.job_id && !immutable && (
              <>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={replacementReviewed}
                    disabled={dirty || replacement.isPending}
                    onChange={(event) =>
                      setReplacementReviewed(event.target.checked)
                    }
                  />
                  I reviewed this saved draft and want a new local introduction
                  using the current contact evidence.
                </label>
                <Button
                  disabled={
                    !replacementReviewed ||
                    dirty ||
                    save.isPending ||
                    approve.isPending
                  }
                  busy={replacement.isPending}
                  onClick={() => replacement.mutate()}
                >
                  Prepare another local draft
                </Button>
              </>
            )}
            {replacement.isError && <ErrorState error={replacement.error} />}
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
              <GmailPermissionBadge />
              <p className="section-intro">
                Sending is disabled. Review your account and save unsent Gmail
                drafts in the separate mailbox workspace.
              </p>
              <Link className="external" href="/connections">
                Gmail account and draft workspace
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}
