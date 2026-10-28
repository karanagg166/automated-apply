"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, dateLabel, externalUrl, post, readable } from "@/lib/api";
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

export type ReadAccount = {
  id: string;
  account_email: string;
  granted_scopes: string[];
  status: "connected" | "disconnected" | "reauthorization_required";
  permissions: {
    read_metadata: boolean;
    read_body: boolean;
    send: false;
    modify: false;
  };
  last_verified_at?: string | null;
  sync_enabled: boolean;
  body_access_reviewed: boolean;
  sync: {
    version: number;
    status: string;
    policy: {
      enabled: boolean;
      sender_allowlist: string[];
      label_allowlist: string[];
      query_allowlist: string | null;
      read_body: boolean;
      body_purpose: string | null;
      backfill_days: number;
      retention_days: number;
      max_pages: number;
    } | null;
    last_sync_at?: string | null;
    inserted?: number;
    scanned?: number;
    last_error?: string | null;
  };
};

export function readableScope(scope: string): string {
  if (scope.includes("gmail.metadata"))
    return "gmail.metadata (Headers & dates)";
  if (scope.includes("gmail.readonly"))
    return "gmail.readonly (Message bodies)";
  if (scope.startsWith("https://www.googleapis.com/auth/")) {
    return scope.replace("https://www.googleapis.com/auth/", "");
  }
  return scope;
}
export type JobEmailEvidence = {
  id: string;
  account_id: string;
  message_id: string;
  thread_id: string;
  received_at: string;
  observed_at: string;
  expires_at: string;
  verification_status: "requires_review";
  submission_confirmed: false;
  links: string[];
  signals: string[];
  imported_job_ids?: string[];
};
type AccountList = {
  accounts: ReadAccount[];
  workflow: "readonly";
  schema_ready: boolean;
  error_code?: string;
};
type Lead = {
  id: string;
  url: string;
  evidence_ids: string[];
  verification_status: "requires_review";
  confirmed_vacancy: false;
};
type ImportSelection = { account: ReadAccount; lead: Lead };

export function ConnectedEmails() {
  const client = useQueryClient();
  const confirmationId = useId();
  const [connectOpen, setConnectOpen] = useState(false);
  const [expectedEmail, setExpectedEmail] = useState("");
  const [accountConsent, setAccountConsent] = useState(false);
  const [readBody, setReadBody] = useState(false);
  const [policyAccount, setPolicyAccount] = useState<ReadAccount | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [senders, setSenders] = useState("");
  const [labels, setLabels] = useState("");
  const [bodyPurpose, setBodyPurpose] = useState("");
  const [backfill, setBackfill] = useState(7);
  const [retention, setRetention] = useState(14);
  const [selectedAccount, setSelectedAccount] = useState("all");
  const [importSelection, setImportSelection] =
    useState<ImportSelection | null>(null);
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [imported, setImported] = useState(false);
  const [importResult, setImportResult] = useState<{
    duplicate_count?: number;
    inserted_count?: number;
    job_ids?: string[];
  } | null>(null);
  const accountsQuery = useQuery({
    queryKey: ["gmail-read-accounts"],
    queryFn: () => api<AccountList>("integrations/gmail/accounts"),
  });
  const accounts = accountsQuery.data?.accounts || [];
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["gmail-read-accounts"] });
    client.invalidateQueries({ queryKey: ["gmail-evidence"] });
  };
  const connect = useMutation({
    mutationFn: () =>
      post<{ authorization_url: string }>(
        "integrations/gmail/accounts/connect/start",
        {
          expected_email: expectedEmail,
          account_consent: accountConsent,
          read_body: readBody,
        },
      ),
    onSuccess: (result) => {
      const url = externalUrl(result.authorization_url);
      if (!url || new URL(url).hostname !== "accounts.google.com")
        throw new Error("Invalid Google authorization URL returned");
      window.location.assign(url);
    },
  });
  const sync = useMutation({
    mutationFn: (id: string) =>
      post<ReadAccount>(`integrations/gmail/accounts/${id}/sync`),
    onSuccess: refresh,
  });
  const verify = useMutation({
    mutationFn: (id: string) =>
      post<ReadAccount>(`integrations/gmail/accounts/${id}/verify`),
    onSuccess: refresh,
  });
  const disconnect = useMutation({
    mutationFn: (id: string) =>
      post(`integrations/gmail/accounts/${id}/disconnect`),
    onSuccess: refresh,
  });
  const policy = useMutation({
    mutationFn: () =>
      api<ReadAccount>(
        `integrations/gmail/accounts/${policyAccount!.id}/selection`,
        {
          method: "PUT",
          body: JSON.stringify({
            expected_version: policyAccount!.sync.version,
            enabled,
            sender_allowlist: senders
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            label_allowlist: labels
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            query_allowlist: null,
            read_body: readBody,
            body_purpose: readBody ? bodyPurpose : null,
            backfill_days: backfill,
            retention_days: retention,
            max_pages: 1,
          }),
        },
      ),
    onSuccess: () => {
      setPolicyAccount(null);
      refresh();
    },
  });
  const evidence = useQuery({
    queryKey: [
      "gmail-evidence",
      selectedAccount,
      accounts.map((a) => a.id).join(","),
    ],
    enabled: accounts.length > 0,
    queryFn: async () =>
      Promise.all(
        accounts
          .filter((a) => selectedAccount === "all" || a.id === selectedAccount)
          .map(async (account) => {
            const [records, leads] = await Promise.all([
              api<{ evidence: JobEmailEvidence[] }>(
                `integrations/gmail/accounts/${account.id}/evidence`,
              ),
              api<{ leads: Lead[] }>(
                `integrations/gmail/accounts/${account.id}/leads`,
              ),
            ]);
            return { account, records: records.evidence, leads: leads.leads };
          }),
      ),
  });
  const importLead = useMutation({
    mutationFn: () =>
      post(
        `integrations/gmail/accounts/${importSelection!.account.id}/evidence/${importSelection!.lead.evidence_ids[0]}/import`,
        {
          job_url: importSelection!.lead.url,
          title: title.trim(),
          company_name: company.trim() || null,
          reviewed_job_evidence: reviewed,
        },
      ),
    onSuccess: (data: any) => {
      setImportSelection(null);
      setImportResult(data);
      setImported(true);
      client.invalidateQueries({ queryKey: ["jobs"] });
      refresh();
    },
  });
  const openPolicy = (account: ReadAccount) => {
    const p = account.sync.policy;
    setPolicyAccount(account);
    setEnabled(p?.enabled ?? false);
    setSenders(p?.sender_allowlist.join(", ") || "");
    setLabels(p?.label_allowlist.join(", ") || "");
    setReadBody(p?.read_body ?? false);
    setBodyPurpose(p?.body_purpose || "");
    setBackfill(p?.backfill_days ?? 7);
    setRetention(p?.retention_days ?? 14);
  };
  const schemaReady = accountsQuery.data?.schema_ready === true;
  return (
    <div
      className="stack spaced"
      aria-label="Connected read-only Gmail accounts"
    >
      <PageTitle
        eyebrow="SELECTED MESSAGE EVIDENCE"
        title="Connected Gmail accounts"
        description="Independent read-only accounts with selected labels, bounded reads, and account-attributed evidence."
        actions={
          <Button
            disabled={!schemaReady}
            title={
              !schemaReady
                ? "Read-only Gmail setup required before connecting accounts"
                : undefined
            }
            onClick={() => {
              setConnectOpen(true);
              setReadBody(false);
              setAccountConsent(false);
            }}
          >
            Connect secondary account
          </Button>
        }
      />
      <Notice>
        <strong>Strict Read-Only Boundary:</strong> This workflow cannot send,
        reply, draft, modify, archive, or delete Gmail messages. Disconnect
        revokes this account's authorization; it does not delete mail. Imported
        links remain unverified vacancy leads.
      </Notice>
      {accountsQuery.isPending && <Skeleton />}
      {accountsQuery.isError && <ErrorState error={accountsQuery.error} />}
      {accountsQuery.data && !schemaReady && (
        <Notice>
          <strong>Read-only Gmail setup required</strong>
          <p>
            The reviewed account storage is not installed. Account connection
            and synchronization are unavailable until the operator completes
            setup.
          </p>
        </Notice>
      )}
      {schemaReady && accounts.length === 0 && (
        <Empty
          title="No read-only accounts connected"
          description="Each mailbox requires its own consent. Existing legacy sending accounts are separate."
        />
      )}
      {imported && (
        <Notice>
          <div className="split">
            <span>
              {importResult && (importResult.duplicate_count || 0) > 0
                ? `Lead updated as existing record (${importResult.duplicate_count} duplicate recognized). Current vacancy and submission remain unconfirmed.`
                : `Reviewed lead imported into workspace (${importResult?.inserted_count || 1} vacancy added). Current vacancy and submission remain unconfirmed.`}
              {importResult?.job_ids?.length
                ? ` Job ID: ${importResult.job_ids.join(", ")}`
                : ""}
            </span>
            <Badge tone="green">Reviewed</Badge>
          </div>
        </Notice>
      )}
      <div
        className="company-grid"
        role="list"
        aria-label="Read-only Gmail accounts"
      >
        {accounts.map((account) => (
          <article className="company-card" role="listitem" key={account.id}>
            <h3>{account.account_email}</h3>
            <div className="tag-list">
              <Badge tone={account.status === "connected" ? "green" : "amber"}>
                {readable(account.status)}
              </Badge>
              <Badge>
                {account.permissions.read_body
                  ? "Body read granted (Job alerts)"
                  : account.permissions.read_metadata
                    ? "Metadata only (Headers & dates)"
                    : "No effective read permission"}
              </Badge>
              <Badge>Sync: {readable(account.sync.status)}</Badge>
            </div>
            <dl>
              <dt>Verified</dt>
              <dd>{dateLabel(account.last_verified_at)}</dd>
              <dt>Last successful sync</dt>
              <dd>{dateLabel(account.sync.last_sync_at)}</dd>
              <dt>Scanned / Inserted</dt>
              <dd>
                {account.sync.scanned ?? 0} scanned ·{" "}
                {account.sync.inserted ?? 0} inserted
              </dd>
              <dt>Allowed labels</dt>
              <dd>
                {account.sync.policy?.label_allowlist.join(", ") ||
                  "None selected"}
              </dd>
              <dt>Granted OAuth scopes</dt>
              <dd style={{ wordBreak: "break-word" }}>
                {account.granted_scopes && account.granted_scopes.length > 0 ? (
                  account.granted_scopes.map(readableScope).join(", ")
                ) : (
                  <span className="muted">None recorded</span>
                )}
              </dd>
            </dl>
            {account.sync.last_error && (
              <p role="alert">{readable(account.sync.last_error)}</p>
            )}
            <div className="actions">
              <Button
                disabled={account.status !== "connected"}
                onClick={() => openPolicy(account)}
              >
                Configure read policy
              </Button>
              <Button
                disabled={
                  account.status !== "connected" ||
                  !account.sync_enabled ||
                  !account.sync.policy?.enabled ||
                  account.sync.status === "syncing"
                }
                title={
                  account.status !== "connected"
                    ? "Account is not connected"
                    : !account.sync_enabled || !account.sync.policy?.enabled
                      ? "Read policy is not enabled for synchronization"
                      : account.sync.status === "syncing"
                        ? "Sync currently in progress"
                        : undefined
                }
                busy={sync.isPending}
                onClick={() => sync.mutate(account.id)}
              >
                Sync now
              </Button>
              <Button
                disabled={account.status !== "connected"}
                busy={verify.isPending}
                onClick={() => verify.mutate(account.id)}
              >
                Verify token
              </Button>
              {account.status === "reauthorization_required" && (
                <Button
                  onClick={() => {
                    setExpectedEmail(account.account_email);
                    setConnectOpen(true);
                  }}
                >
                  Reconnect account
                </Button>
              )}
              <Button
                variant="danger"
                disabled={account.status === "disconnected"}
                busy={disconnect.isPending}
                onClick={() => disconnect.mutate(account.id)}
              >
                Disconnect
              </Button>
            </div>
          </article>
        ))}
      </div>
      {[sync, verify, disconnect].map(
        (mutation, index) =>
          mutation.isError && <ErrorState key={index} error={mutation.error} />,
      )}
      {accounts.length > 0 && (
        <section
          className="panel panel-body stack"
          aria-label="Selected email evidence"
        >
          <h4>Selected-message evidence and candidate links</h4>
          <p>
            Raw senders, subjects, and message bodies are not retained. Links
            and status signals require human review.
          </p>
          <Field label="ORIGINATING ACCOUNT">
            <Select
              aria-label="Filter by account"
              value={selectedAccount}
              onChange={(event) => setSelectedAccount(event.target.value)}
            >
              <option value="all">
                All connected accounts ({accounts.length})
              </option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.account_email}
                </option>
              ))}
            </Select>
          </Field>
          {evidence.isPending && <Skeleton />}
          {evidence.isError && <ErrorState error={evidence.error} />}
          {evidence.data?.map(({ account, records, leads }) => (
            <section
              key={account.id}
              className="stack"
              aria-label={`Evidence from ${account.account_email}`}
            >
              <h5>Account: {account.account_email}</h5>
              {records.length === 0 && (
                <Empty
                  title="No retained evidence"
                  description="Sync only reads messages matching this account's selected policy."
                />
              )}
              {records.map((record) => (
                <div className="panel panel-body" key={record.id}>
                  <div className="tag-list">
                    <Badge tone="amber">Requires review</Badge>
                    {record.imported_job_ids &&
                      record.imported_job_ids.length > 0 && (
                        <Badge tone="green">
                          Imported (Job ID: {record.imported_job_ids.join(", ")}
                          )
                        </Badge>
                      )}
                  </div>
                  <p>
                    Message ID: {record.message_id} · Thread ID:{" "}
                    {record.thread_id}
                  </p>
                  <p>
                    Received {dateLabel(record.received_at)} · Retention expires{" "}
                    {dateLabel(record.expires_at)}
                  </p>
                  <p>
                    {record.signals.map(readable).join(", ") ||
                      "No status signal observed"}
                  </p>
                  {record.links.map((url) => (
                    <p key={url}>
                      <External href={url}>
                        Inspect retained source link
                      </External>
                    </p>
                  ))}
                </div>
              ))}
              {leads.map((lead) => {
                const leadEvidence = records.filter((r) =>
                  lead.evidence_ids.includes(r.id),
                );
                const isImported = leadEvidence.some(
                  (r) => r.imported_job_ids && r.imported_job_ids.length > 0,
                );
                return (
                  <article key={lead.id} className="panel panel-body">
                    <div className="tag-list">
                      <Badge tone="amber">Unconfirmed vacancy lead</Badge>
                      {isImported && (
                        <Badge tone="neutral">Already imported</Badge>
                      )}
                    </div>
                    <p>
                      <External href={lead.url}>{lead.url}</External>
                    </p>
                    <p>Source evidence: {lead.evidence_ids.join(", ")}</p>
                    <Button
                      disabled={!lead.evidence_ids.length}
                      onClick={() => {
                        setImportSelection({ account, lead });
                        setTitle("");
                        setCompany("");
                        setReviewed(false);
                        importLead.reset();
                      }}
                    >
                      Review lead for import
                    </Button>
                  </article>
                );
              })}
            </section>
          ))}
        </section>
      )}
      <Modal
        open={connectOpen}
        onOpenChange={setConnectOpen}
        title="Connect Secondary Gmail Account"
        description="Authorize this account independently with a read-only grant."
      >
        <div className="stack">
          <Field label="Expected secondary Gmail address">
            <Input
              type="email"
              value={expectedEmail}
              onChange={(event) => setExpectedEmail(event.target.value)}
            />
          </Field>
          <Field label="Approved read scope">
            <Select
              value={readBody ? "body" : "metadata"}
              onChange={(event) => setReadBody(event.target.value === "body")}
            >
              <option value="metadata">Metadata only (recommended)</option>
              <option value="body">
                Body read (requires separate restricted-scope review)
              </option>
            </Select>
          </Field>
          <label className="check-label">
            <input
              type="checkbox"
              checked={accountConsent}
              onChange={(event) => setAccountConsent(event.target.checked)}
            />
            This is my designated account. I authorize read-only Google OAuth.
          </label>
          {connect.isError && <ErrorState error={connect.error} />}
          <Button
            disabled={!expectedEmail || !accountConsent}
            busy={connect.isPending}
            onClick={() => connect.mutate()}
          >
            Continue to Google OAuth
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!policyAccount}
        onOpenChange={(open) => !open && setPolicyAccount(null)}
        title={`Read Policy: ${policyAccount?.account_email || ""}`}
        description="Choose this account's selected messages. Sync runs only when requested."
      >
        <div className="stack">
          <label className="check-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            Enable read-only synchronization for selected messages
          </label>
          <Field
            label="Allowed Custom Labels"
            hint="Gmail IDs such as Label_Jobs; required for metadata-only reads"
          >
            <Input
              value={labels}
              onChange={(event) => setLabels(event.target.value)}
            />
          </Field>
          <Field label="Sender Allowlist">
            <Input
              value={senders}
              onChange={(event) => setSenders(event.target.value)}
            />
          </Field>
          {policyAccount?.body_access_reviewed &&
            policyAccount.permissions.read_body && (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={readBody}
                  onChange={(event) => setReadBody(event.target.checked)}
                />
                Read selected message bodies
              </label>
            )}
          {readBody && (
            <Field label="Purpose for Body Access">
              <Input
                value={bodyPurpose}
                onChange={(event) => setBodyPurpose(event.target.value)}
              />
            </Field>
          )}
          <Field label="Backfill Window (Days)">
            <Input
              type="number"
              min={1}
              max={30}
              value={backfill}
              onChange={(event) => setBackfill(Number(event.target.value))}
            />
          </Field>
          <Field label="Evidence Retention (Days)">
            <Input
              type="number"
              min={1}
              max={90}
              value={retention}
              onChange={(event) => setRetention(Number(event.target.value))}
            />
          </Field>
          {policy.isError && <ErrorState error={policy.error} />}
          <Button
            busy={policy.isPending}
            disabled={enabled && !readBody && !labels.trim()}
            title={
              enabled && !readBody && !labels.trim()
                ? "Custom labels are required for metadata-only reads"
                : undefined
            }
            onClick={() => policy.mutate()}
          >
            Save policy
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!importSelection}
        onOpenChange={(open) => !open && setImportSelection(null)}
        title="Review candidate vacancy lead"
        description="Inspect the posting and supply its actual title. Email evidence alone does not confirm a current vacancy."
      >
        {importSelection && (
          <div className="stack">
            {Boolean(
              evidence.data
                ?.find((e) => e.account.id === importSelection.account.id)
                ?.records.filter((r) =>
                  importSelection.lead.evidence_ids.includes(r.id),
                )
                .some(
                  (r) => r.imported_job_ids && r.imported_job_ids.length > 0,
                ),
            ) && (
              <Notice>
                <strong>Duplicate status:</strong> This lead was previously
                imported. Importing again will update the existing job record.
              </Notice>
            )}
            <p>Account: {importSelection.account.account_email}</p>
            <External href={importSelection.lead.url}>
              Inspect source posting
            </External>
            <Field
              label="Actual job title"
              hint="Required to establish candidate application details"
            >
              <Input
                required
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </Field>
            <Field label="Company (if observed)">
              <Input
                value={company}
                onChange={(event) => setCompany(event.target.value)}
              />
            </Field>
            <label className="check-label" htmlFor={confirmationId}>
              <input
                id={confirmationId}
                type="checkbox"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
              />
              I reviewed this selected-message link and supplied the actual job
              details.
            </label>
            {importLead.isError && <ErrorState error={importLead.error} />}
            <Button
              disabled={!reviewed || !title.trim()}
              title={
                !title.trim()
                  ? "Actual job title is required before import"
                  : !reviewed
                    ? "Confirmation checkbox is required"
                    : undefined
              }
              busy={importLead.isPending}
              onClick={() => importLead.mutate()}
            >
              Import reviewed lead
            </Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
