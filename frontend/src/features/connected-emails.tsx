"use client";

import { useId, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  Briefcase,
  Calendar,
  CheckCircle2,
  Clock,
  ExternalLink,
  Eye,
  FileCheck,
  FilePlus2,
  Filter,
  Inbox,
  Mail,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  XCircle,
} from "lucide-react";
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

function hostnameMatches(host: string, domain: string) {
  return host === domain || host.endsWith(`.${domain}`);
}

export function detectUrlAts(url: string): { name: string; isAts: boolean } {
  try {
    const hostname = new URL(url).hostname.toLowerCase();
    if (hostnameMatches(hostname, "greenhouse.io"))
      return { name: "Greenhouse", isAts: true };
    if (hostnameMatches(hostname, "lever.co"))
      return { name: "Lever", isAts: true };
    if (hostnameMatches(hostname, "ashbyhq.com"))
      return { name: "Ashby", isAts: true };
    if (hostnameMatches(hostname, "smartrecruiters.com"))
      return { name: "SmartRecruiters", isAts: true };
    if (
      hostnameMatches(hostname, "workday.com") ||
      hostnameMatches(hostname, "myworkdayjobs.com")
    )
      return { name: "Workday", isAts: true };
    if (hostnameMatches(hostname, "taleo.net"))
      return { name: "Taleo", isAts: true };
    if (hostnameMatches(hostname, "linkedin.com"))
      return { name: "LinkedIn Jobs", isAts: false };
    return { name: hostname.replace(/^www\./, ""), isAts: false };
  } catch {
    return { name: "Direct Link", isAts: false };
  }
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
  signal_basis?: string;
  status_confirmed?: false;
};

type AccountList = {
  accounts: ReadAccount[];
  workflow: "readonly";
  schema_ready: boolean;
  error_code?: string;
};

type IngestionResult = {
  total_received: number;
  inserted_count: number;
  updated_count: number;
  duplicate_count: number;
  rejected_count: number;
  failed_count: number;
  skipped_count: number;
  job_ids: string[];
  possible_duplicates?: Record<string, string[]>;
  errors?: string[];
};

type Lead = {
  id: string;
  url: string;
  evidence_ids: string[];
  verification_status: "requires_review";
  confirmed_vacancy: false;
  imported_job_ids?: string[];
  import_state?: "imported" | "not_imported" | "legacy_message_import_unknown";
};

type ImportSelection = { account: ReadAccount; lead: Lead };

export function ConnectedEmails() {
  const client = useQueryClient();
  const confirmationId = useId();

  // Dialog & Connection States
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

  // Filters & Selection
  const [selectedAccount, setSelectedAccount] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState<
    "all" | "alerts" | "recruiters" | "interviews" | "status" | "links"
  >("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [dateFreshness, setDateFreshness] = useState<
    "all" | "1" | "7" | "14" | "30"
  >("all");
  const [selectedRecordDetail, setSelectedRecordDetail] = useState<{
    record: JobEmailEvidence;
    account: ReadAccount;
  } | null>(null);

  // Lead Import States
  const [importSelection, setImportSelection] =
    useState<ImportSelection | null>(null);
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [imported, setImported] = useState(false);
  const [importResult, setImportResult] = useState<IngestionResult | null>(
    null,
  );

  // Queries
  const accountsQuery = useQuery({
    queryKey: ["gmail-read-accounts"],
    queryFn: () => api<AccountList>("integrations/gmail/accounts"),
  });

  const accounts = accountsQuery.data?.accounts || [];

  const refresh = () => {
    client.invalidateQueries({ queryKey: ["gmail-read-accounts"] });
    client.invalidateQueries({ queryKey: ["gmail-evidence"] });
    client.invalidateQueries({ queryKey: ["jobs"] });
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
      post<IngestionResult>(
        `integrations/gmail/accounts/${importSelection!.account.id}/evidence/${importSelection!.lead.evidence_ids[0]}/import`,
        {
          job_url: importSelection!.lead.url,
          title: title.trim(),
          company_name: company.trim() || null,
          reviewed_job_evidence: reviewed,
        },
      ),
    onSuccess: (data: IngestionResult) => {
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

  // Filter evidence based on category, freshness, and search query
  const filteredEvidence = useMemo(() => {
    if (!evidence.data) return [];
    return evidence.data.map(({ account, records, leads }) => {
      let filteredRecords = records;

      // Category filter
      if (categoryFilter !== "all") {
        filteredRecords = filteredRecords.filter((rec) => {
          const sigs = rec.signals.map((s) => s.toLowerCase());
          if (categoryFilter === "alerts") {
            return sigs.some(
              (s) =>
                s.includes("job") ||
                s.includes("alert") ||
                s.includes("vacancy"),
            );
          }
          if (categoryFilter === "recruiters") {
            return sigs.some(
              (s) =>
                s.includes("recruiter") ||
                s.includes("outreach") ||
                s.includes("sourcer"),
            );
          }
          if (categoryFilter === "interviews") {
            return sigs.some(
              (s) =>
                s.includes("interview") ||
                s.includes("meeting") ||
                s.includes("calendar"),
            );
          }
          if (categoryFilter === "status") {
            return sigs.some(
              (s) =>
                s.includes("status") ||
                s.includes("received") ||
                s.includes("reject") ||
                s.includes("offer"),
            );
          }
          if (categoryFilter === "links") {
            return rec.links.length > 0;
          }
          return true;
        });
      }

      // Date freshness filter
      if (dateFreshness !== "all") {
        const days = Number(dateFreshness);
        const threshold = Date.now() - days * 24 * 60 * 60 * 1000;
        filteredRecords = filteredRecords.filter((rec) => {
          const t = new Date(rec.received_at || rec.observed_at).getTime();
          return !isNaN(t) && t >= threshold;
        });
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        filteredRecords = filteredRecords.filter((rec) => {
          return (
            rec.message_id.toLowerCase().includes(q) ||
            rec.thread_id.toLowerCase().includes(q) ||
            rec.signals.some((s) => s.toLowerCase().includes(q)) ||
            rec.links.some((l) => l.toLowerCase().includes(q))
          );
        });
      }

      return { account, records: filteredRecords, leads };
    });
  }, [evidence.data, categoryFilter, dateFreshness, searchQuery]);

  return (
    <div
      className="stack spaced"
      aria-label="Connected read-only Gmail accounts"
    >
      <PageTitle
        eyebrow="JOB INBOX & SELECTED MESSAGE EVIDENCE"
        title="Gmail Job Inbox"
        description="Independent read-only accounts with selected labels, bounded reads, recruiter signal detection, and account-attributed evidence."
        actions={
          <div className="actions">
            <Button
              disabled={!schemaReady}
              title={
                !schemaReady
                  ? "Read-only Gmail setup required before connecting accounts"
                  : undefined
              }
              onClick={() => {
                setExpectedEmail("");
                setConnectOpen(true);
                setReadBody(false);
                setAccountConsent(false);
              }}
            >
              <Mail size={14} />
              Connect secondary account
            </Button>
          </div>
        }
      />

      {/* Strict Read-Only Notice */}
      <Notice>
        <strong>Strict Read-Only Boundary:</strong> This Job Inbox cannot send,
        reply, compose, draft, modify, archive, or delete Gmail messages.
        Disconnect revokes this account's authorization; it does not delete
        mail. Extracted links remain unverified vacancy leads until reviewed.
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
          action={
            <Button
              onClick={() => {
                setExpectedEmail("");
                setConnectOpen(true);
                setReadBody(false);
                setAccountConsent(false);
              }}
            >
              Connect Gmail account
            </Button>
          }
        />
      )}

      {imported && importResult && (
        <Notice>
          <div className="split">
            <span>
              {importResult.duplicate_count > 0
                ? `Lead updated as existing record (${importResult.duplicate_count} duplicate recognized). Current vacancy and submission remain unconfirmed.`
                : `Reviewed lead imported into workspace (${importResult.inserted_count} ${importResult.inserted_count === 1 ? "vacancy" : "vacancies"} added). Current vacancy and submission remain unconfirmed.`}
              {importResult.job_ids.length > 0
                ? ` Job ID: ${importResult.job_ids.join(", ")}`
                : ""}
            </span>
            <div className="actions">
              <Badge tone="green">Reviewed</Badge>
              <Link className="button" href="/jobs">
                View in Jobs
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </div>
        </Notice>
      )}

      {/* Account Cards Section */}
      <div
        className="company-grid"
        role="list"
        aria-label="Read-only Gmail accounts"
      >
        {accounts.map((account) => (
          <article className="company-card" role="listitem" key={account.id}>
            <div className="split">
              <h3>{account.account_email}</h3>
              {account.status === "connected" && (
                <span title="Google Verified OAuth">
                  <ShieldCheck size={16} className="text-green-600" />
                </span>
              )}
            </div>

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
              <div className="stack" style={{ marginTop: "0.25rem" }}>
                <p role="alert" className="text-xs text-red-600">
                  Sync error: {readable(account.sync.last_error)}
                </p>
                <Button
                  variant="ghost"
                  className="text-xs"
                  onClick={() => sync.mutate(account.id)}
                  busy={sync.isPending}
                >
                  <RefreshCw size={12} />
                  Retry sync
                </Button>
              </div>
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

      {/* Inbox Evidence & Leads View */}
      {accounts.length > 0 && (
        <section
          className="panel panel-body stack"
          aria-label="Selected email evidence"
        >
          <div className="split">
            <div>
              <h4>Selected-message evidence and candidate links</h4>
              <p className="text-sm muted">
                Raw senders, subjects, and message bodies are not retained.
                Extracted vacancy links and detected recruiter signals require
                review before import.
              </p>
            </div>
            <Badge tone="green">Read-only Stream</Badge>
          </div>

          {/* Account Filter, Category Tabs, Search, and Date Filters */}
          <div
            className="filter-panel"
            style={{
              padding: "0.75rem",
              background: "var(--surface-sunken, rgba(0,0,0,0.02))",
            }}
          >
            <div className="filter-grid">
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

              <Field label="SEARCH INBOX EVIDENCE">
                <Input
                  placeholder="Search URL, message ID, signals…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </Field>

              <Field label="DATE FRESHNESS">
                <Select
                  value={dateFreshness}
                  onChange={(e) => setDateFreshness(e.target.value as any)}
                >
                  <option value="all">All received time</option>
                  <option value="1">Last 24 hours</option>
                  <option value="7">Last 7 days</option>
                  <option value="14">Last 14 days</option>
                  <option value="30">Last 30 days</option>
                </Select>
              </Field>
            </div>

            {/* Signal Categories Bar */}
            <div className="tag-list" style={{ marginTop: "0.5rem" }}>
              <span className="text-xs muted">Signal Categories:</span>
              <button
                type="button"
                className={`badge ${categoryFilter === "all" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("all")}
              >
                All Messages
              </button>
              <button
                type="button"
                className={`badge ${categoryFilter === "alerts" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("alerts")}
              >
                🔔 Job Alerts
              </button>
              <button
                type="button"
                className={`badge ${categoryFilter === "recruiters" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("recruiters")}
              >
                👤 Recruiter Outreach
              </button>
              <button
                type="button"
                className={`badge ${categoryFilter === "interviews" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("interviews")}
              >
                📅 Interview Invitations
              </button>
              <button
                type="button"
                className={`badge ${categoryFilter === "status" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("status")}
              >
                📝 Status Updates
              </button>
              <button
                type="button"
                className={`badge ${categoryFilter === "links" ? "green" : "neutral"} cursor-pointer`}
                onClick={() => setCategoryFilter("links")}
              >
                🔗 Career Links
              </button>
            </div>
          </div>

          {evidence.isPending && <Skeleton />}
          {evidence.isError && <ErrorState error={evidence.error} />}

          {filteredEvidence.map(({ account, records, leads }) => (
            <section
              key={account.id}
              className="stack spaced"
              aria-label={`Evidence from ${account.account_email}`}
            >
              <h5>Account: {account.account_email}</h5>
              {records.length === 0 && (
                <Empty
                  title="No retained evidence"
                  description="Sync only reads messages matching this account's selected policy."
                />
              )}

              {/* Records List */}
              {records.map((record) => {
                const isImported =
                  record.imported_job_ids && record.imported_job_ids.length > 0;

                return (
                  <div className="panel panel-body" key={record.id}>
                    <div className="split">
                      <div className="tag-list">
                        <Badge tone="amber">Requires review</Badge>
                        {isImported && (
                          <Badge tone="green">
                            Message has imported link (Job ID:{" "}
                            {record.imported_job_ids!.join(", ")})
                          </Badge>
                        )}
                        <Badge tone="neutral">
                          Tentative signals; status unconfirmed
                        </Badge>
                        {record.signals.map((sig) => (
                          <Badge key={sig} tone="neutral">
                            {readable(sig)}
                          </Badge>
                        ))}
                      </div>
                      <Button
                        variant="ghost"
                        className="text-xs"
                        onClick={() =>
                          setSelectedRecordDetail({ record, account })
                        }
                      >
                        <Eye size={12} />
                        Message details
                      </Button>
                    </div>

                    <p
                      className="text-xs muted"
                      style={{ marginTop: "0.25rem" }}
                    >
                      Message ID: {record.message_id} · Thread ID:{" "}
                      {record.thread_id}
                    </p>
                    <p className="text-xs">
                      Received {dateLabel(record.received_at)} · Retention
                      expires {dateLabel(record.expires_at)}
                    </p>

                    {record.links.map((url) => {
                      const atsInfo = detectUrlAts(url);
                      return (
                        <div
                          key={url}
                          className="split"
                          style={{ marginTop: "0.25rem" }}
                        >
                          <External href={url}>
                            Inspect retained source link
                          </External>
                          {atsInfo.isAts && (
                            <Badge tone="green">Detected: {atsInfo.name}</Badge>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })}

              {/* Candidate Leads List */}
              {leads.map((lead) => {
                const isImported = lead.import_state === "imported";
                const atsInfo = detectUrlAts(lead.url);

                return (
                  <article key={lead.id} className="panel panel-body">
                    <div className="tag-list">
                      <Badge tone="amber">Unconfirmed vacancy lead</Badge>
                      {isImported && (
                        <Badge tone="neutral">Already imported</Badge>
                      )}
                      {lead.import_state ===
                        "legacy_message_import_unknown" && (
                        <Badge tone="amber">
                          Historical link import mapping unknown
                        </Badge>
                      )}
                      {atsInfo.isAts && (
                        <Badge tone="green">{atsInfo.name} ATS</Badge>
                      )}
                    </div>
                    <p className="text-sm">
                      <External href={lead.url}>{lead.url}</External>
                    </p>
                    <p className="text-xs muted">
                      Source evidence: {lead.evidence_ids.join(", ")}
                    </p>
                    <div className="actions" style={{ marginTop: "0.5rem" }}>
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
                    </div>
                  </article>
                );
              })}
            </section>
          ))}
        </section>
      )}

      {/* Message Detail Modal */}
      <Modal
        open={Boolean(selectedRecordDetail)}
        onOpenChange={(open) => !open && setSelectedRecordDetail(null)}
        title="Read-Only Message Detail"
        description="Metadata and observed vacancy links extracted under read-only authorization."
      >
        {selectedRecordDetail && (
          <div className="stack spaced">
            <Notice>
              <strong>Read-Only Notice:</strong> Message bodies and raw headers
              are not retained on disk. You cannot reply, compose, send, or
              modify this message.
            </Notice>

            <dl className="grid-2">
              <div>
                <dt>Account</dt>
                <dd>{selectedRecordDetail.account.account_email}</dd>
              </div>
              <div>
                <dt>Message ID</dt>
                <dd className="text-xs font-mono">
                  {selectedRecordDetail.record.message_id}
                </dd>
              </div>
              <div>
                <dt>Thread ID</dt>
                <dd className="text-xs font-mono">
                  {selectedRecordDetail.record.thread_id}
                </dd>
              </div>
              <div>
                <dt>Received</dt>
                <dd>{dateLabel(selectedRecordDetail.record.received_at)}</dd>
              </div>
              <div>
                <dt>Observed</dt>
                <dd>{dateLabel(selectedRecordDetail.record.observed_at)}</dd>
              </div>
              <div>
                <dt>Retention Expires</dt>
                <dd>{dateLabel(selectedRecordDetail.record.expires_at)}</dd>
              </div>
            </dl>

            <div className="stack">
              <strong>Detected Signals:</strong>
              <div className="tag-list">
                {selectedRecordDetail.record.signals.map((sig) => (
                  <Badge key={sig} tone="neutral">
                    {readable(sig)}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="stack">
              <strong>Extracted Vacancy Links:</strong>
              {selectedRecordDetail.record.links.map((link) => {
                const ats = detectUrlAts(link);
                const isDup = evidence.data
                  ?.find(
                    (group) =>
                      group.account.id === selectedRecordDetail.account.id,
                  )
                  ?.leads.some(
                    (lead) =>
                      lead.url === link && lead.import_state === "imported",
                  );
                return (
                  <div key={link} className="panel panel-body stack">
                    <div className="split">
                      <span className="text-xs font-bold">{ats.name}</span>
                      {isDup && (
                        <Badge tone="neutral">Already in pipeline</Badge>
                      )}
                    </div>
                    <External href={link}>{link}</External>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Modal>

      {/* Connect Account Modal */}
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

      {/* Policy Modal */}
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
          <div className="split">
            <Field label="Backfill (days, 1–30)">
              <Input
                type="number"
                min={1}
                max={30}
                value={backfill}
                onChange={(event) =>
                  setBackfill(
                    Math.max(1, Math.min(30, Number(event.target.value) || 1)),
                  )
                }
              />
            </Field>
            <Field label="Retention (days, 1–90)">
              <Input
                type="number"
                min={1}
                max={90}
                value={retention}
                onChange={(event) =>
                  setRetention(
                    Math.max(1, Math.min(90, Number(event.target.value) || 1)),
                  )
                }
              />
            </Field>
          </div>
          {policy.isError && <ErrorState error={policy.error} />}
          <Button
            disabled={
              policyAccount?.status !== "connected" ||
              (!labels.trim() && !senders.trim())
            }
            title={
              policyAccount?.status !== "connected"
                ? "Account must be connected"
                : !labels.trim() && !senders.trim()
                  ? "At least one label or sender allowlist entry is required"
                  : undefined
            }
            busy={policy.isPending}
            onClick={() => policy.mutate()}
          >
            Save policy
          </Button>
        </div>
      </Modal>

      {/* Review Lead Import Modal */}
      <Modal
        open={!!importSelection}
        onOpenChange={(open) => !open && setImportSelection(null)}
        title="Review candidate vacancy lead"
        description="Inspect the posting and supply its actual title. Email evidence alone does not confirm a current vacancy."
      >
        {importSelection && (
          <div className="stack">
            {Boolean(importSelection.lead.import_state === "imported") && (
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
