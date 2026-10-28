"use client";
import { LocalConnections } from "@/features/local-connections";
import { ConnectedEmails } from "@/features/connected-emails";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, KeyRound, Mail, Plug, ShieldCheck } from "lucide-react";
import { api, dateLabel, externalUrl, post, readable } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Modal,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";
type Connector = {
  platform: string;
  live_verified: boolean;
  capabilities: Record<string, string | boolean>;
  discovery_connection?: {
    state: string;
    last_check?: { finished_at?: string; error_category?: string } | null;
  } | null;
};
type Gmail = {
  status: string;
  account_email?: string;
  granted_scopes?: string[];
  last_verified_at?: string | null;
  send_capability: string;
  oauth_configured: boolean;
  sending_enabled: boolean;
  live_verified: boolean;
};
type Runtime = {
  provider: string;
  configured: boolean;
  authorized: boolean;
  live_verified: boolean;
  capability: string;
  budget: number;
  next_action: string;
};
type Enricher = {
  provider: string;
  enabled: boolean;
  credentials_configured: boolean;
  configuration_status: string;
  budget: {
    monthly_limit: number;
    remaining_local_budget: number;
    credits_per_lookup_estimate: number | null;
    cooldown_until: string | null;
  };
  live_verification: string;
  billing_configuration_required: boolean;
};
export function Connections() {
  const client = useQueryClient(),
    [tab, setTab] = useState<"connectors" | "mailboxes">("connectors"),
    [detail, setDetail] = useState<string | null>(null),
    [email, setEmail] = useState(""),
    [mode, setMode] = useState("metadata"),
    [consent, setConsent] = useState(false);
  const registry = useQuery({
    queryKey: ["connections"],
    queryFn: () => api<{ connectors: Connector[] }>("integrations"),
  });
  const runtime = useQuery({
    queryKey: ["runtime-connections"],
    queryFn: () => api<{ providers: Runtime[] }>("dashboard/connections"),
  });
  const enrichment = useQuery({
    queryKey: ["enrichment-status"],
    queryFn: () =>
      api<{ providers: Enricher[] }>("contact-enrichment/providers"),
  });
  const gmail = useQuery({
    queryKey: ["gmail-status"],
    queryFn: () => api<Gmail>("integrations/gmail/status"),
  });
  const connect = useMutation({
    mutationFn: () =>
      post<{ authorization_url: string }>("integrations/gmail/connect/start", {
        expected_email: email,
        authorization_mode: mode,
      }),
    onSuccess: (result) => {
      const url = externalUrl(result.authorization_url);
      if (url && new URL(url).hostname === "accounts.google.com")
        window.location.assign(url);
      else throw new Error("Invalid OAuth authorization URL");
    },
  });
  const verify = useMutation({
    mutationFn: () => post("integrations/gmail/verify"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["gmail-status"] });
      client.invalidateQueries({ queryKey: ["connections"] });
    },
  });
  const disconnect = useMutation({
    mutationFn: () => post("integrations/gmail/disconnect"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["gmail-status"] });
      client.invalidateQueries({ queryKey: ["connections"] });
    },
  });
  const cards = registry.data?.connectors || [];
  return (
    <>
      <PageTitle
        eyebrow="CONNECTED, WITH CLARITY"
        title="The right tools. Clear permissions."
        description="Configuration, authorization and live verification are separate states."
        actions={
          <Badge>
            <ShieldCheck size={12} />
            Credentials stay server-side
          </Badge>
        }
      />
      <div className="status-tabs" role="tablist" aria-label="Connection views">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "connectors"}
          className={tab === "connectors" ? "selected" : ""}
          onClick={() => setTab("connectors")}
        >
          Platform connectors
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "mailboxes"}
          className={tab === "mailboxes" ? "selected" : ""}
          onClick={() => setTab("mailboxes")}
        >
          Connected mailboxes (Read-Only)
        </button>
      </div>
      {tab === "mailboxes" ? (
        <ConnectedEmails />
      ) : (
        <>
          <LocalConnections />
          <Notice>
            Portals without a verified linking protocol use Manual Handoff.
            There is no portal-password collection or LinkedIn account
            connection. Gmail requires a separately authorized secondary
            account.
          </Notice>
          {registry.isPending ? (
            <Skeleton />
          ) : registry.isError ? (
            <ErrorState error={registry.error} />
          ) : (
            <div className="connection-grid">
              {cards.map((c) => {
                const enrich = enrichment.data?.providers.find(
                  (p) => p.provider === c.platform,
                );
                const manual = [
                  "naukri",
                  "instahyre",
                  "wellfound",
                  "internshala",
                  "work_at_a_startup",
                  "linkedin",
                ].includes(c.platform);
                const state =
                  c.platform === "gmail"
                    ? gmail.data?.status || "not_connected"
                    : enrich
                      ? enrich.credentials_configured
                        ? "configured_not_live_verified"
                        : "not_connected"
                      : manual
                        ? "manual_handoff_only"
                        : c.discovery_connection?.state ||
                          "requires_configuration";
                return (
                  <article className="connection-card" key={c.platform}>
                    <div className="split">
                      <span className="row-icon">
                        {c.platform === "gmail" ? (
                          <Mail size={19} />
                        ) : (
                          <Plug size={19} />
                        )}
                      </span>
                      <Badge
                        tone={
                          c.live_verified
                            ? "green"
                            : state === "not_connected"
                              ? "amber"
                              : "neutral"
                        }
                      >
                        {readable(state)}
                      </Badge>
                    </div>
                    <h3>
                      {c.platform === "gmail"
                        ? "Secondary Gmail"
                        : readable(c.platform)}
                    </h3>
                    <p>
                      {c.platform === "gmail"
                        ? "Local drafts, OAuth identity and exact-content send confirmation."
                        : enrich
                          ? "Optional professional contact enrichment. Returned addresses require separate mailbox verification."
                          : manual
                            ? "Prepare a packet, review evidence and continue manually on the official website."
                            : "Read public job-board listings through the existing permitted adapter."}
                    </p>
                    <dl>
                      <dt>Live verified</dt>
                      <dd>{c.live_verified ? "Yes" : "No"}</dd>
                      <dt>Credential state</dt>
                      <dd>
                        {enrich
                          ? enrich.credentials_configured
                            ? "Available"
                            : "Missing"
                          : c.platform === "gmail"
                            ? gmail.data?.oauth_configured
                              ? "OAuth configured"
                              : "OAuth missing"
                            : manual
                              ? "No linking protocol"
                              : "Source configuration"}
                      </dd>
                      <dt>Cost / budget</dt>
                      <dd>
                        {enrich
                          ? `${enrich.budget.remaining_local_budget} / ${enrich.budget.monthly_limit} local credits`
                          : c.platform === "greenhouse"
                            ? "Public read API"
                            : "Operation dependent"}
                      </dd>
                      <dt>Last verification</dt>
                      <dd>
                        {dateLabel(
                          c.platform === "gmail"
                            ? gmail.data?.last_verified_at
                            : c.discovery_connection?.last_check?.finished_at,
                        )}
                      </dd>
                      <dt>Last error</dt>
                      <dd>
                        {c.discovery_connection?.last_check?.error_category ||
                          "None recorded"}
                      </dd>
                    </dl>
                    <Button
                      onClick={() => {
                        setDetail(c.platform);
                        setConsent(false);
                      }}
                    >
                      Review capabilities
                      <ArrowUpRight size={13} />
                    </Button>
                  </article>
                );
              })}
              {runtime.data?.providers.map((p) => (
                <article className="connection-card" key={p.provider}>
                  <div className="split">
                    <span className="row-icon">
                      <KeyRound size={18} />
                    </span>
                    <Badge tone={p.configured ? "neutral" : "amber"}>
                      {p.configured ? "Configured" : "Not connected"}
                    </Badge>
                  </div>
                  <h3>{p.provider}</h3>
                  <p>{p.next_action}</p>
                  <dl>
                    <dt>Capability</dt>
                    <dd>{readable(p.capability)}</dd>
                    <dt>Permission configured</dt>
                    <dd>
                      {p.authorized
                        ? "Yes · operation consent required"
                        : "Review required"}
                    </dd>
                    <dt>Live verified</dt>
                    <dd>{p.live_verified ? "Yes" : "No"}</dd>
                    <dt>Local budget</dt>
                    <dd>
                      {p.budget}
                      {p.provider === "apify" ? " USD / month" : " / month"}
                    </dd>
                  </dl>
                  <Button onClick={() => setDetail(p.provider)}>
                    Review setup
                    <ArrowUpRight size={13} />
                  </Button>
                </article>
              ))}
            </div>
          )}
          {runtime.isError && <ErrorState error={runtime.error} />}{" "}
          {enrichment.isError && <ErrorState error={enrichment.error} />}
        </>
      )}
      <Modal
        open={!!detail}
        onOpenChange={(v) => !v && setDetail(null)}
        title={
          detail === "gmail"
            ? "Connect secondary Gmail"
            : `${readable(detail)} · capabilities & setup`
        }
        description="Only the backend’s recorded state determines availability. Setup does not imply a verified connection."
      >
        {detail === "gmail" ? (
          <div className="stack">
            {gmail.isError ? (
              <ErrorState error={gmail.error} />
            ) : (
              <>
                <div className="tag-list">
                  <Badge>{readable(gmail.data?.status)}</Badge>
                  <Badge>{readable(gmail.data?.send_capability)}</Badge>
                </div>
                <p className="section-intro">
                  {gmail.data?.account_email ||
                    "No secondary Gmail account authorized"}
                </p>
                <details>
                  <summary>Granted OAuth scopes</summary>
                  <ul>
                    {gmail.data?.granted_scopes?.map((s) => (
                      <li className="section-intro" key={s}>
                        {s}
                      </li>
                    )) || <li>No scopes granted</li>}
                  </ul>
                </details>
                <Field label="Expected secondary Gmail address">
                  <Input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="off"
                  />
                </Field>
                <Field label="Authorization mode">
                  <Select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="metadata">
                      Connect account identity first
                    </option>
                    <option value="compose">
                      Authorize future draft creation (existing connected
                      identity)
                    </option>
                  </Select>
                </Field>
                <Notice>
                  Use a separately authorized secondary account. Identity
                  connection does not enable sending. Every send still requires
                  exact-content approval and a short-lived confirmation
                  challenge.
                </Notice>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  This is my designated secondary account. I authorize opening
                  Google’s official consent flow for the selected mode.
                </label>
                <Button
                  variant="primary"
                  disabled={!consent || !email || !gmail.data?.oauth_configured}
                  busy={connect.isPending}
                  onClick={() => connect.mutate()}
                >
                  Continue to Google consent
                  <ArrowUpRight size={14} />
                </Button>
                {!gmail.data?.oauth_configured && (
                  <Notice>
                    Operator setup required: OAuth client, reviewed redirect
                    URI, encryption key ring and expected secondary address.
                    Configure these privately in backend/.env.
                  </Notice>
                )}
                <div className="actions">
                  <Button
                    disabled={gmail.data?.status !== "connected"}
                    busy={verify.isPending}
                    onClick={() => verify.mutate()}
                  >
                    Verify account identity
                  </Button>
                  <Button
                    variant="danger"
                    disabled={gmail.data?.status !== "connected"}
                    busy={disconnect.isPending}
                    onClick={() => disconnect.mutate()}
                  >
                    Disconnect account
                  </Button>
                </div>
              </>
            )}
            {connect.isError && <ErrorState error={connect.error} />}{" "}
            {verify.isError && <ErrorState error={verify.error} />}{" "}
            {disconnect.isError && <ErrorState error={disconnect.error} />}
          </div>
        ) : (
          <div className="stack">
            {cards.find((c) => c.platform === detail) && (
              <div>
                {Object.entries(
                  cards.find((c) => c.platform === detail)!.capabilities,
                ).map(([key, value]) => (
                  <div className="preference-row" key={key}>
                    <strong>{readable(key)}</strong>
                    <Badge>{readable(String(value))}</Badge>
                  </div>
                ))}
              </div>
            )}
            {runtime.data?.providers.find((p) => p.provider === detail) && (
              <Notice>
                {
                  runtime.data.providers.find((p) => p.provider === detail)!
                    .next_action
                }
              </Notice>
            )}
            {enrichment.data?.providers.find((p) => p.provider === detail) && (
              <Notice>
                Credentials:{" "}
                {enrichment.data.providers.find((p) => p.provider === detail)!
                  .credentials_configured
                  ? "available"
                  : "missing"}
                . Permission state:{" "}
                {readable(
                  enrichment.data.providers.find((p) => p.provider === detail)!
                    .configuration_status,
                )}
                . Cost per lookup:{" "}
                {enrichment.data.providers.find((p) => p.provider === detail)!
                  .budget.credits_per_lookup_estimate ?? "not configured"}
                . Account terms and credit costs require review before
                execution.
              </Notice>
            )}
            <p className="section-intro">
              Operator configuration is server-side. Review backend/.env.example
              and docs/phase7-account-connections.md. This screen never requests
              provider passwords or writes deployment secrets.
            </p>
            <Link
              className="button"
              href={detail === "notifications" ? "/settings" : "/discover"}
            >
              {detail === "notifications"
                ? "Notification preferences"
                : "Review discovery options"}
              <ArrowUpRight size={13} />
            </Link>
          </div>
        )}
      </Modal>
    </>
  );
}
