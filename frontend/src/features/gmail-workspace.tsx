"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, dateLabel, post, readable } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Select,
  Skeleton,
} from "@/components/ui";
import { ConnectedEmails } from "@/features/connected-emails";
import type {
  ReadAccount,
  JobEmailEvidence,
} from "@/features/connected-emails";

type Account = Partial<ReadAccount> & {
  slot: "read_1" | "read_2" | "outreach";
  drafts_enabled?: boolean;
  generation?: number;
};
type History = {
  id: string;
  version: number;
  company: string;
  role: string;
  status: string;
  applied_at: string;
  confirmed_application: boolean;
  retention_days: number;
  evidence: Record<string, string[]>;
};
type Draft = {
  id: string;
  version: number;
  content_hash: string;
  status: string;
  company: string;
  role: string;
  gmail_draft_id?: string;
  content: { recipient: string; subject: string; body: string };
};
const base = "integrations/gmail/workspace";

export function GmailWorkspace() {
  const accounts = useQuery({
    queryKey: ["gmail-workspace"],
    queryFn: () =>
      api<{ schema_ready: boolean; accounts: Account[] }>(`${base}/accounts`),
  });
  const history = useQuery({
    queryKey: ["gmail-history"],
    queryFn: () => api<{ history: History[] }>(`${base}/history`),
  });
  const drafts = useQuery({
    queryKey: ["gmail-outreach-drafts"],
    queryFn: () => api<{ drafts: Draft[] }>(`${base}/drafts`),
  });
  if (accounts.isPending) return <Skeleton />;
  if (accounts.isError)
    return (
      <ErrorState error={accounts.error} retry={() => accounts.refetch()} />
    );
  const outreach = accounts.data.accounts.find((a) => a.slot === "outreach");
  return (
    <section className="stack">
      <div>
        <h2>Three independent Gmail accounts</h2>
        <p>
          Two read-only application histories and one separate outreach account.
          Sending stays disabled.
        </p>
      </div>
      {!accounts.data.schema_ready && (
        <Notice>
          Mailbox storage needs the separately approved setup update. No OAuth,
          scan or Gmail draft starts automatically.
        </Notice>
      )}
      <div className="grid-3">
        {accounts.data.accounts.map((account) => (
          <AccountCard
            key={account.slot}
            account={account}
            schemaReady={accounts.data.schema_ready}
            history={history.data?.history || []}
          />
        ))}
      </div>
      <ConnectedEmails reviewOnly />
      <section className="card">
        <h2>Reviewed application history</h2>
        <p>
          Confirmed applications prevent matching the same job again. Uncertain
          email evidence stays separate. Raw metadata expires independently.
        </p>
        <p>
          Headers alone can miss application details. Review uncertain evidence
          before confirming a company or role; message bodies require separate
          consent.
        </p>
        {history.isError && (
          <ErrorState error={history.error} retry={() => history.refetch()} />
        )}
        {!history.isPending && !history.data?.history.length && (
          <p>No reviewed application history yet.</p>
        )}
        {history.data?.history.map((item) => (
          <HistoryRow key={item.id} item={item} />
        ))}
      </section>
      <section className="card">
        <h2>Outreach drafts</h2>
        <p>
          Prepare and edit locally, then explicitly review each message before
          saving a Gmail draft. This workspace has no send action.
        </p>
        <DraftComposer />
        {drafts.isError && (
          <ErrorState error={drafts.error} retry={() => drafts.refetch()} />
        )}
        {drafts.data?.drafts.map((draft) => (
          <DraftEditor
            key={`${draft.id}:${draft.version}:${outreach?.generation}`}
            draft={draft}
            generation={outreach?.generation || 0}
            enabled={Boolean(
              outreach?.drafts_enabled && outreach.status === "connected",
            )}
          />
        ))}
      </section>
    </section>
  );
}

function AccountCard({
  account,
  schemaReady,
  history,
}: {
  account: Account;
  schemaReady: boolean;
  history: History[];
}) {
  const client = useQueryClient();
  const [consent, setConsent] = useState(false),
    [showEvidence, setShowEvidence] = useState(false),
    [bodyConsent, setBodyConsent] = useState(false);
  const outreach = account.slot === "outreach";
  const connect = useMutation({
    mutationFn: () =>
      post<{ authorization_url: string }>(
        `${base}/accounts/${account.slot}/connect`,
        { account_consent: consent || bodyConsent, read_body: bodyConsent },
      ),
    onSuccess: (result) => {
      const url = new URL(result.authorization_url);
      if (url.protocol !== "https:" || url.hostname !== "accounts.google.com")
        throw new Error("Unexpected authorization destination");
      window.location.assign(url.href);
    },
  });
  const disconnect = useMutation({
    mutationFn: () =>
      post(
        outreach
          ? `${base}/outreach/disconnect`
          : `integrations/gmail/accounts/${account.id}/disconnect`,
      ),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["gmail-workspace"] }),
  });
  return (
    <article className="card stack">
      <h3>
        {outreach
          ? "Account 3 · Outreach drafts only"
          : `Account ${account.slot === "read_1" ? "1" : "2"} · Read only`}
      </h3>
      <Badge>{readable(account.status || "not_connected")}</Badge>
      <p>
        {account.account_email ||
          "Choose your Google account during authorization. No email address is needed now."}
      </p>
      {account.status !== "connected" ? (
        <>
          <label>
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />{" "}
            {outreach
              ? "Authorize a separate outreach account for reviewed Gmail drafts only"
              : "Authorize this account for read-only metadata access"}
          </label>
          {outreach && (
            <p>
              Google’s compose permission also permits sending. The application
              restricts this account to drafts.
            </p>
          )}
          {!outreach && (
            <label>
              <input
                type="checkbox"
                checked={bodyConsent}
                disabled={!account.body_access_reviewed}
                onChange={(e) => setBodyConsent(e.target.checked)}
              />{" "}
              Separately authorize read-only body access after operator review
            </label>
          )}
          <Button
            disabled={!consent || !schemaReady}
            busy={connect.isPending}
            onClick={() => connect.mutate()}
          >
            Connect with Google
          </Button>
        </>
      ) : (
        <Button busy={disconnect.isPending} onClick={() => disconnect.mutate()}>
          Disconnect this account
        </Button>
      )}
      {(connect.isError || disconnect.isError) && (
        <Notice>{(connect.error || disconnect.error)?.message}</Notice>
      )}
      {!outreach &&
        account.status === "connected" &&
        account.body_access_reviewed &&
        !account.permissions?.read_body && (
          <>
            <label>
              <input
                type="checkbox"
                checked={bodyConsent}
                onChange={(e) => setBodyConsent(e.target.checked)}
              />{" "}
              I separately authorize read-only message body access
            </label>
            <Button
              disabled={!bodyConsent}
              busy={connect.isPending}
              onClick={() => connect.mutate()}
            >
              Authorize optional body access
            </Button>
          </>
        )}
      {!outreach && account.id && (
        <>
          <ReadSettings
            key={`${account.id}:${account.sync?.version}`}
            account={account}
          />
          <Button onClick={() => setShowEvidence(!showEvidence)}>
            {showEvidence ? "Hide" : "Review"} email evidence
          </Button>
          {showEvidence && (
            <Evidence accountId={account.id} history={history} />
          )}
        </>
      )}
    </article>
  );
}

function ReadSettings({ account }: { account: Account }) {
  const client = useQueryClient();
  const saved = account.sync?.policy as
    | (ReadAccount["sync"]["policy"] & {
        folders?: string[];
        history_months?: number | null;
      })
    | undefined;
  const [enabled, setEnabled] = useState(saved?.enabled || false);
  const [readBody, setReadBody] = useState(saved?.read_body || false),
    [purpose, setPurpose] = useState(saved?.body_purpose || "");
  const [inbox, setInbox] = useState(saved?.folders?.includes("INBOX") ?? true),
    [sent, setSent] = useState(saved?.folders?.includes("SENT") ?? true);
  const [months, setMonths] = useState(saved?.history_months || 24),
    [labels, setLabels] = useState(saved?.label_allowlist.join(", ") || ""),
    [senders, setSenders] = useState(saved?.sender_allowlist.join(", ") || "");
  const split = (value: string) =>
    value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  const save = useMutation({
    mutationFn: () =>
      api(`integrations/gmail/accounts/${account.id}/selection`, {
        method: "PUT",
        body: JSON.stringify({
          expected_version: account.sync?.version || 0,
          enabled,
          folders: [inbox && "INBOX", sent && "SENT"].filter(Boolean),
          history_months: months,
          label_allowlist: split(labels),
          sender_allowlist: split(senders),
          query_allowlist: null,
          read_body: readBody,
          body_purpose: readBody ? purpose : null,
          backfill_days: 7,
          retention_days: 14,
          retain_metadata: true,
          max_pages: 1,
        }),
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["gmail-workspace"] }),
  });
  const scan = useMutation({
    mutationFn: () => post(`integrations/gmail/accounts/${account.id}/sync`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["gmail-workspace"] });
      client.invalidateQueries({ queryKey: ["gmail-evidence", account.id] });
    },
  });
  return (
    <div className="stack">
      <h4>Scan settings</h4>
      <label>
        <input
          type="checkbox"
          checked={inbox}
          onChange={(e) => setInbox(e.target.checked)}
        />{" "}
        Inbox
      </label>
      <label>
        <input
          type="checkbox"
          checked={sent}
          onChange={(e) => setSent(e.target.checked)}
        />{" "}
        Sent Mail
      </label>
      <Field label="Historical lookback (months, maximum 24)">
        <Input
          type="number"
          min={1}
          max={24}
          value={months}
          onChange={(e) => setMonths(Number(e.target.value))}
        />
      </Field>
      <Field label="Optional custom label IDs, comma separated">
        <Input
          value={labels}
          onChange={(e) => setLabels(e.target.value)}
          placeholder="Label_jobs"
        />
      </Field>
      <Field label="Optional sender allowlist, comma separated">
        <Input value={senders} onChange={(e) => setSenders(e.target.value)} />
      </Field>
      <label>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />{" "}
        Enable this reviewed scan selection
      </label>
      <label>
        <input
          type="checkbox"
          checked={readBody}
          disabled={
            !account.permissions?.read_body || !account.body_access_reviewed
          }
          onChange={(e) => setReadBody(e.target.checked)}
        />{" "}
        Use separately authorized read-only message bodies
      </label>
      {readBody && (
        <Field label="Why headers do not suffice">
          <Input
            value={purpose}
            minLength={10}
            maxLength={300}
            onChange={(e) => setPurpose(e.target.value)}
          />
        </Field>
      )}
      <p>
        At most 25 messages per batch. Metadata dates are checked locally; older
        pages may need inspection to complete the chosen window. Raw metadata
        retention: 14 days.
      </p>
      <Button
        disabled={account.status !== "connected" || !(inbox || sent)}
        busy={save.isPending}
        onClick={() => save.mutate()}
      >
        Save account settings
      </Button>
      <Button
        disabled={
          !account.sync_enabled ||
          !account.sync?.policy?.enabled ||
          account.status !== "connected"
        }
        busy={scan.isPending}
        onClick={() => scan.mutate()}
      >
        Scan next batch (up to 25)
      </Button>
      <p>
        {readable(account.sync?.status)} · Last scan{" "}
        {dateLabel(account.sync?.last_sync_at)} · {account.sync?.scanned || 0}{" "}
        messages inspected
      </p>
      {(save.isError || scan.isError) && (
        <Notice>{(save.error || scan.error)?.message}</Notice>
      )}
    </div>
  );
}

function Evidence({
  accountId,
  history,
}: {
  accountId: string;
  history: History[];
}) {
  const evidence = useQuery({
    queryKey: ["gmail-evidence", accountId],
    queryFn: () =>
      api<{
        evidence: Array<
          JobEmailEvidence & {
            metadata?: {
              subject: string;
              from: string;
              to: string;
              folder: string;
            };
          }
        >;
      }>(`integrations/gmail/accounts/${accountId}/evidence`),
  });
  if (evidence.isPending) return <Skeleton />;
  if (evidence.isError)
    return (
      <ErrorState error={evidence.error} retry={() => evidence.refetch()} />
    );
  return (
    <div>
      <p>
        Email evidence is uncertain until reviewed. Inbox and Sent messages do
        not prove an application by themselves.
      </p>
      {!evidence.data.evidence.length && <p>No selected evidence yet.</p>}
      {evidence.data.evidence.map((message) => (
        <EvidenceReview
          key={message.id}
          message={message}
          accountId={accountId}
          history={history}
        />
      ))}
    </div>
  );
}

function EvidenceReview({
  message,
  accountId,
  history,
}: {
  message: JobEmailEvidence & {
    metadata?: { subject: string; from: string; to: string; folder: string };
  };
  accountId: string;
  history: History[];
}) {
  const client = useQueryClient();
  const [company, setCompany] = useState(""),
    [role, setRole] = useState(""),
    [status, setStatus] = useState("uncertain"),
    [confirmed, setConfirmed] = useState(false),
    [reviewed, setReviewed] = useState(false),
    [retention, setRetention] = useState(365),
    [date, setDate] = useState(message.received_at.slice(0, 10));
  const save = useMutation({
    mutationFn: () => {
      const previous = history.find(
        (h) =>
          h.company.trim().toLowerCase() === company.trim().toLowerCase() &&
          h.role.trim().toLowerCase() === role.trim().toLowerCase(),
      );
      return post(`${base}/history/review`, {
        expected_version: previous?.version || 0,
        company,
        role,
        status,
        confirmed_application: confirmed,
        owner_reviewed: reviewed,
        retention_days: retention,
        applied_at: new Date(date + "T00:00:00Z").toISOString(),
        evidence: { [accountId]: [message.id] },
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["gmail-history"] }),
  });
  return (
    <div className="card stack">
      <Badge>Uncertain email evidence</Badge>
      <p>{message.metadata?.subject || "Metadata not retained"}</p>
      <p>
        {message.metadata?.folder} · {dateLabel(message.received_at)}
      </p>
      <p>
        {message.metadata?.from} → {message.metadata?.to}
      </p>
      <p>{message.signals.map(readable).join(", ")}</p>
      <Field label="Reviewed company">
        <Input value={company} onChange={(e) => setCompany(e.target.value)} />
      </Field>
      <Field label="Reviewed job role">
        <Input value={role} onChange={(e) => setRole(e.target.value)} />
      </Field>
      <Field label="Application date">
        <Input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </Field>
      <Field label="Reviewed status">
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          {[
            "uncertain",
            "applied",
            "recruiter_response",
            "interview",
            "rejected",
            "status_update",
          ].map((s) => (
            <option key={s} value={s}>
              {readable(s)}
            </option>
          ))}
        </Select>
      </Field>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        I confirm I applied for this exact role
      </label>
      <Field label="Structured history retention (days)">
        <Input
          type="number"
          min={14}
          max={7300}
          value={retention}
          onChange={(e) => setRetention(Number(e.target.value))}
        />
      </Field>
      <label>
        <input
          type="checkbox"
          checked={reviewed}
          onChange={(e) => setReviewed(e.target.checked)}
        />{" "}
        I reviewed company, role, date, status and evidence
      </label>
      <Button
        disabled={!reviewed || !company.trim() || !role.trim()}
        busy={save.isPending}
        onClick={() => save.mutate()}
      >
        Save reviewed application history
      </Button>
      {save.isError && <Notice>{save.error.message}</Notice>}
      {save.isSuccess && (
        <Notice>
          Reviewed history saved separately from raw email metadata.
        </Notice>
      )}
    </div>
  );
}

function HistoryRow({ item }: { item: History }) {
  const client = useQueryClient();
  const [days, setDays] = useState(item.retention_days);
  const retention = useMutation({
    mutationFn: () =>
      api(`${base}/history/${item.id}/retention`, {
        method: "PUT",
        body: JSON.stringify({
          expected_version: item.version,
          retention_days: days,
        }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["gmail-history"] }),
  });
  const forget = useMutation({
    mutationFn: () =>
      post(`${base}/history/${item.id}/forget`, {
        expected_version: item.version,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["gmail-history"] }),
  });
  return (
    <div className="card">
      <h3>
        {item.company} · {item.role}
      </h3>
      <Badge>
        {item.confirmed_application
          ? "Confirmed application"
          : "Uncertain evidence"}
      </Badge>
      <p>
        {dateLabel(item.applied_at)} · {readable(item.status)} ·{" "}
        {Object.keys(item.evidence).length} account(s) · Structured retention{" "}
        {item.retention_days} days
      </p>
      <Field label="Change structured history retention (days)">
        <Input
          type="number"
          min={14}
          max={7300}
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        />
      </Field>
      <Button busy={retention.isPending} onClick={() => retention.mutate()}>
        Save history retention
      </Button>
      <Button busy={forget.isPending} onClick={() => forget.mutate()}>
        Forget this structured history
      </Button>
      {(forget.isError || retention.isError) && (
        <Notice>{(forget.error || retention.error)?.message}</Notice>
      )}
    </div>
  );
}

function DraftComposer() {
  const client = useQueryClient();
  const [recipient, setRecipient] = useState(""),
    [company, setCompany] = useState(""),
    [role, setRole] = useState(""),
    [context, setContext] = useState("");
  const save = useMutation({
    mutationFn: () =>
      post(`${base}/drafts`, { recipient, company, role, context }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["gmail-outreach-drafts"] }),
  });
  return (
    <div className="stack">
      <Field label="Outreach recipient">
        <Input
          type="email"
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
        />
      </Field>
      <Field label="Outreach company">
        <Input value={company} onChange={(e) => setCompany(e.target.value)} />
      </Field>
      <Field label="Outreach role">
        <Input value={role} onChange={(e) => setRole(e.target.value)} />
      </Field>
      <Field label="Personalized context you reviewed">
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          maxLength={2000}
        />
      </Field>
      <Button
        disabled={
          !recipient ||
          !company.trim() ||
          !role.trim() ||
          context.trim().length < 10
        }
        busy={save.isPending}
        onClick={() => save.mutate()}
      >
        Prepare local outreach draft
      </Button>
      {save.isError && <Notice>{save.error.message}</Notice>}
    </div>
  );
}

function DraftEditor({
  draft,
  enabled,
  generation,
}: {
  draft: Draft;
  enabled: boolean;
  generation: number;
}) {
  const client = useQueryClient();
  const [recipient, setRecipient] = useState(draft.content.recipient),
    [subject, setSubject] = useState(draft.content.subject),
    [body, setBody] = useState(draft.content.body),
    [reviewed, setReviewed] = useState(false);
  const dirty =
    recipient !== draft.content.recipient ||
    subject !== draft.content.subject ||
    body !== draft.content.body;
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["gmail-outreach-drafts"] });
  const save = useMutation({
    mutationFn: () =>
      api(`${base}/drafts/${draft.id}`, {
        method: "PUT",
        body: JSON.stringify({
          expected_version: draft.version,
          recipient,
          company: draft.company,
          role: draft.role,
          context: "Owner edited outreach content",
          subject,
          body,
        }),
      }),
    onSuccess: refresh,
  });
  const create = useMutation({
    mutationFn: () =>
      post(`${base}/drafts/${draft.id}/create-in-gmail`, {
        expected_version: draft.version,
        content_hash: draft.content_hash,
        owner_reviewed: reviewed,
        expected_account_generation: generation,
      }),
    onSuccess: refresh,
  });
  const locked = draft.status !== "local_draft";
  return (
    <div className="card stack">
      <h3>
        {draft.company} · {draft.role}
      </h3>
      <Badge>{readable(draft.status)}</Badge>
      <Field label="Draft recipient">
        <Input
          disabled={locked}
          value={recipient}
          onChange={(e) => {
            setRecipient(e.target.value);
            setReviewed(false);
          }}
        />
      </Field>
      <Field label="Draft subject">
        <Input
          disabled={locked}
          value={subject}
          onChange={(e) => {
            setSubject(e.target.value);
            setReviewed(false);
          }}
        />
      </Field>
      <Field label="Draft message">
        <textarea
          disabled={locked}
          value={body}
          onChange={(e) => {
            setBody(e.target.value);
            setReviewed(false);
          }}
        />
      </Field>
      {!locked && (
        <>
          <Button
            disabled={!dirty}
            busy={save.isPending}
            onClick={() => save.mutate()}
          >
            Save draft edits locally
          </Button>
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              disabled={dirty}
              onChange={(e) => setReviewed(e.target.checked)}
            />{" "}
            I reviewed this exact recipient, subject and message
          </label>
          <Button
            disabled={!enabled || !reviewed || dirty}
            busy={create.isPending}
            onClick={() => create.mutate()}
          >
            Save reviewed draft in Gmail
          </Button>
        </>
      )}
      {draft.status === "saved_in_gmail" && (
        <p>
          Saved as a draft. Open Gmail to review or edit it. Nothing was sent.
        </p>
      )}
      {["dispatching", "unknown"].includes(draft.status) && (
        <Notice>
          Check the outreach mailbox manually before any further action. This
          draft will not be retried automatically.
        </Notice>
      )}
      {(save.isError || create.isError) && (
        <Notice>{(save.error || create.error)?.message}</Notice>
      )}
    </div>
  );
}
