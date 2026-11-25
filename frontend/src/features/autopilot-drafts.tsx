"use client";
import { useQuery } from "@tanstack/react-query";
import { api, type Schema } from "@/lib/api";
import {
  Badge,
  Empty,
  ErrorState,
  GmailPermissionBadge,
  Skeleton,
} from "@/components/ui";
import { stamp, stateTone } from "@/features/autopilot-forms";
import { QuotaBar } from "@/features/autopilot-status";

type MailStatus = Schema<"MailStatusRead">;
type EnrichmentStatus = Schema<"EnrichmentStatusRead">;
type EnrichmentProvider = Schema<"EnrichmentProviderRead">;
type DraftPage = Schema<"EmailDraftPage">;
type Draft = Schema<"EmailDraftRead">;

export const MAIL_STATUS_KEY = ["v2-mail-status"] as const;
export const ENRICHMENT_KEY = ["v2-enrichment-status"] as const;
export const DRAFTS_KEY = ["v2-drafts"] as const;
export const DRAFTS_PATH = "v2/drafts?limit=25";

const CHANNEL_LABEL: Record<MailStatus["active_channel"], string> = {
  imap: "IMAP (Gmail Drafts)",
  mail_app: "Mail.app (silent)",
  unconfigured: "Unconfigured",
};

const PROVIDER_LABEL: Record<EnrichmentProvider["provider"], string> = {
  apollo: "Apollo",
  apify: "Apify",
  signalhire: "SignalHire",
};

const PROVIDER_STATE: Record<
  EnrichmentProvider["state"],
  { label: string; tone: "green" | "amber" | "red" | "neutral" }
> = {
  available: { label: "Available", tone: "green" },
  cap_reached: { label: "Daily cap reached", tone: "amber" },
  cooldown: { label: "Cooling down", tone: "red" },
  unconfigured: { label: "Not configured", tone: "neutral" },
};

const DRAFT_STATUS: Record<
  Draft["status"],
  { label: string; tone: "green" | "amber" | "red" }
> = {
  CREATED: { label: "Saved in Drafts", tone: "green" },
  PENDING: { label: "Unconfirmed", tone: "amber" },
  FAILED: { label: "Failed", tone: "red" },
};

export function channelTone(channel: MailStatus["active_channel"]) {
  return channel === "unconfigured" ? ("amber" as const) : ("green" as const);
}

function MailBridge({ mail }: { mail: MailStatus }) {
  return (
    <div className="portal-status" aria-label="Mail bridge status">
      <div className="split">
        <h3>Mail bridge</h3>
        <Badge tone={channelTone(mail.active_channel)}>
          {CHANNEL_LABEL[mail.active_channel]}
        </Badge>
      </div>
      <dl className="worker-facts">
        <div>
          <dt>IMAP</dt>
          <dd>
            {mail.imap_configured
              ? `Configured · ${mail.imap_email ?? mail.imap_host}`
              : "Not configured"}
          </dd>
        </div>
        <div>
          <dt>Mail.app fallback</dt>
          <dd>
            {mail.mail_app_disabled
              ? "Disabled"
              : mail.mail_app_available
                ? "Available (never opens a window)"
                : "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Resume attachment</dt>
          <dd>{mail.resume_attachment_configured ? "Attached" : "Not set"}</dd>
        </div>
      </dl>
      {mail.active_channel === "unconfigured" && (
        <p className="portal-hint">
          Add <code>GMAIL_IMAP_EMAIL</code> +{" "}
          <code>GMAIL_IMAP_APP_PASSWORD</code> (a Gmail App Password) to the
          private env file. Jobs are still queued for tomorrow without a draft.
        </p>
      )}
    </div>
  );
}

function ProviderMeter({ provider }: { provider: EnrichmentProvider }) {
  const state = PROVIDER_STATE[provider.state];
  const name = PROVIDER_LABEL[provider.provider];
  return (
    <div className="portal-status" aria-label={`${name} enrichment`}>
      <div className="split">
        <h3>{name}</h3>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      {provider.configured ? (
        <>
          <QuotaBar
            label="Free credits today"
            used={provider.used_today}
            max={provider.daily_cap}
            hit={provider.used_today >= provider.daily_cap}
          />
          {provider.cooldown_until && (
            <p className="portal-hint">
              Skipped until {stamp(provider.cooldown_until)}
              {provider.last_error ? ` · ${provider.last_error}` : ""}
            </p>
          )}
        </>
      ) : (
        <p className="muted small-print">
          Add <code>{provider.key_env}</code> to enable (free tier, capped at{" "}
          {provider.daily_cap}/day).
        </p>
      )}
    </div>
  );
}

function DraftRow({ draft }: { draft: Draft }) {
  const status = DRAFT_STATUS[draft.status];
  const job = [draft.company_name, draft.role_title]
    .filter(Boolean)
    .join(" · ");
  return (
    <tr>
      <td className="reason-cell">
        {job || "—"}
        {draft.platform && <small className="muted"> · {draft.platform}</small>}
      </td>
      <td>{draft.recipient_email ?? "—"}</td>
      <td className="reason-cell">{draft.subject ?? "—"}</td>
      <td>
        {draft.channel === "mail_app"
          ? "Mail.app"
          : draft.channel === "imap"
            ? "IMAP"
            : "—"}
      </td>
      <td>
        <span title={draft.last_error ?? undefined}>
          <Badge tone={status.tone}>{status.label}</Badge>
        </span>
      </td>
      <td>
        {draft.application_state && (
          <Badge tone={stateTone(draft.application_state)}>
            {draft.application_state.replace(/_/g, " ").toLowerCase()}
          </Badge>
        )}
        <div>
          <small>
            {draft.application_state === "DRAFTED_AND_QUEUED"
              ? `Retry ${stamp(draft.retry_after, "—")}`
              : stamp(draft.created_at, "—")}
          </small>
        </div>
      </td>
    </tr>
  );
}

export function QuotaFallbackPanel() {
  const mail = useQuery({
    queryKey: MAIL_STATUS_KEY,
    queryFn: () => api<MailStatus>("v2/mail/status"),
    refetchInterval: 60000,
  });
  const enrichment = useQuery({
    queryKey: ENRICHMENT_KEY,
    queryFn: () => api<EnrichmentStatus>("v2/enrichment/status"),
    refetchInterval: 60000,
  });
  const drafts = useQuery({
    queryKey: DRAFTS_KEY,
    queryFn: () => api<DraftPage>(DRAFTS_PATH),
    refetchInterval: 30000,
  });
  return (
    <section className="panel" aria-labelledby="drafts-heading">
      <div className="panel-header">
        <div>
          <h2 id="drafts-heading">
            Gmail Drafts &amp; Enrichment (Quota Fallback)
          </h2>
          <p>
            When a portal hits its daily cap, each parked job gets one Gmail
            draft to the recruiter (if an email is found) and is retried on the
            portal tomorrow. Drafts are never sent — review them in Gmail.
          </p>
        </div>
        <div className="tag-list">
          <GmailPermissionBadge />
          {drafts.data && (
            <Badge tone="neutral">{drafts.data.total} drafts</Badge>
          )}
        </div>
      </div>
      <div className="panel-body stack">
        <div className="portal-grid">
          {mail.isPending ? (
            <Skeleton />
          ) : mail.isError ? (
            <ErrorState error={mail.error} retry={() => mail.refetch()} />
          ) : (
            <MailBridge mail={mail.data} />
          )}
          {enrichment.isPending ? (
            <Skeleton />
          ) : enrichment.isError ? (
            <ErrorState
              error={enrichment.error}
              retry={() => enrichment.refetch()}
            />
          ) : (
            enrichment.data.providers.map((provider) => (
              <ProviderMeter key={provider.provider} provider={provider} />
            ))
          )}
        </div>
        {enrichment.data && (
          <p className="muted small-print">
            {enrichment.data.cached_domains} company domains cached (30 days; 7
            days when no email was found). Job descriptions and careers pages
            are checked first at zero cost.
          </p>
        )}
        <h3>Recent Gmail drafts</h3>
        {drafts.isPending ? (
          <Skeleton />
        ) : drafts.isError ? (
          <ErrorState error={drafts.error} retry={() => drafts.refetch()} />
        ) : drafts.data.items.length === 0 ? (
          <Empty
            title="No drafts yet"
            description="Drafts appear here after a portal hits its daily limit and a recruiter email is found."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">
                Gmail drafts created by the quota fallback, with the next portal
                retry
              </caption>
              <thead>
                <tr>
                  <th scope="col">JOB</th>
                  <th scope="col">RECIPIENT</th>
                  <th scope="col">SUBJECT</th>
                  <th scope="col">CHANNEL</th>
                  <th scope="col">DRAFT</th>
                  <th scope="col">PORTAL RETRY</th>
                </tr>
              </thead>
              <tbody>
                {drafts.data.items.map((draft) => (
                  <DraftRow key={draft.id} draft={draft} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
