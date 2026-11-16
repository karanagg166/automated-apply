"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Mail, Search, ShieldCheck, Users } from "lucide-react";
import { api, dateLabel, post, readable } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Field,
  Modal,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";
import type { Startup } from "./startups";
import { ContactReview, type ContactDetail } from "./contact-review";
import { recoverLocalDraft } from "./outreach-draft-attempt";
import {
  clearReviewedLookupAttempt,
  readLookupAttempt,
  runLookupAttempt,
  type LookupAttempt,
} from "./contact-lookup-attempt";
export type Contact = {
  id: string;
  company_id: string;
  company: string;
  full_name: string;
  role_title: string;
  linkedin_url?: string | null;
  email?: string | null;
  email_status: string;
  email_evidence_status?: string;
  email_publication_url?: string | null;
  source: string;
  last_checked_at?: string | null;
  confidence: string;
  do_not_contact: boolean;
  suppression_reason?: string | null;
  manual_linkedin_available: boolean;
  manual_outreach_review_available: boolean;
  email_send_ready: boolean;
  retention_expired: boolean;
  professional_url?: string | null;
};
type EnrichmentPreview = {
  providers?: Array<Record<string, unknown>>;
  provider_plan?: Array<{
    provider: string;
    lookup_count_upper_bound: number;
    reserved_credit_upper_bound: number | null;
    configured: boolean;
  }>;
  cached_contacts?: unknown[];
  discovered_people?: unknown[];
  blockers?: string[];
  [key: string]: unknown;
};
export function CompanyPeople({
  companyId,
  companyName,
  domain,
}: {
  companyId: string;
  companyName: string;
  domain?: string | null;
}) {
  const client = useQueryClient(),
    router = useRouter(),
    [enrichOpen, setEnrichOpen] = useState(false),
    [provider, setProvider] = useState("apollo"),
    [approved, setApproved] = useState(false),
    [evidenceId, setEvidenceId] = useState<string | null>(null),
    [evidenceReview, setEvidenceReview] = useState(0),
    [roleFilter, setRoleFilter] = useState("all"),
    [researchConsent, setResearchConsent] = useState(false);
  const [lookupAttempt, setLookupAttempt] = useState<LookupAttempt | null>(
    null,
  );
  const [lookupStorageError, setLookupStorageError] = useState<unknown>(null);
  const [lookupHistoryReviewed, setLookupHistoryReviewed] = useState(false);
  useEffect(() => {
    try {
      const attempt = readLookupAttempt(companyId);
      setLookupAttempt(attempt);
      if (attempt) setProvider(attempt.provider);
    } catch (error) {
      setLookupStorageError(error);
    }
  }, [companyId]);
  const contacts = useQuery({
    queryKey: ["contacts", companyId],
    queryFn: () =>
      api<{ contacts: Contact[] }>(`companies/${companyId}/contacts`),
  });
  const people = useQuery({
    queryKey: ["people", companyId],
    queryFn: () =>
      api<{
        people: Array<{
          name: string | null;
          role: string | null;
          linkedin_url: string | null;
          evidence_url: string;
          source: string;
          observed_at: string;
          verification_status: string;
        }>;
      }>(`companies/${companyId}/people`),
  });
  const evidence = useQuery({
    queryKey: ["contact-evidence", evidenceId],
    queryFn: () => api<ContactDetail>(`contacts/${evidenceId}`),
    enabled: !!evidenceId,
  });
  const payload = {
    providers: [provider],
    max_people: 1,
    target_roles: ["founder", "cto"],
    allow_paid: true,
    allow_fallback: false,
    include_candidates: false,
  };
  const preview = useMutation({
    mutationFn: () =>
      post<EnrichmentPreview>(
        `companies/${companyId}/contacts/preview`,
        payload,
      ),
  });
  const execute = useMutation({
    retry: false,
    mutationFn: () => runLookupAttempt(companyId, provider),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["contacts", companyId] });
      setApproved(false);
    },
    onSettled: () => {
      try {
        setLookupAttempt(readLookupAttempt(companyId));
      } catch (error) {
        setLookupStorageError(error);
      }
    },
  });
  const draft = useMutation({
    retry: false,
    mutationFn: recoverLocalDraft,
    onSuccess: (d) => router.push(`/outreach/${d.id}`),
  });
  const research = useMutation({
    mutationFn: () =>
      post<Record<string, unknown>>("discovery/people/search", {
        company_name: companyName,
        company_domain: domain || undefined,
        roles: ["founder", "cto", "engineering manager", "recruiter"],
        source: "public_search",
        research_mode: "official_company",
        permission_confirmed: true,
        allow_paid: true,
        limit: 5,
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["people", companyId] });
      client.invalidateQueries({ queryKey: ["contacts", companyId] });
      setResearchConsent(false);
    },
  });
  const matchesRole = (title?: string | null) => {
    if (roleFilter === "all") return true;
    const t = (title || "").toLowerCase();
    if (roleFilter === "founder")
      return (
        t.includes("founder") ||
        t.includes("ceo") ||
        t.includes("co-founder") ||
        t.includes("president")
      );
    if (roleFilter === "cto")
      return (
        t.includes("cto") ||
        t.includes("chief") ||
        t.includes("head") ||
        t.includes("vp") ||
        t.includes("director")
      );
    if (roleFilter === "engineer")
      return (
        t.includes("engineer") ||
        t.includes("developer") ||
        t.includes("architect") ||
        t.includes("lead")
      );
    if (roleFilter === "recruiter")
      return (
        t.includes("recruiter") ||
        t.includes("talent") ||
        t.includes("hiring") ||
        t.includes("people") ||
        t.includes("hr")
      );
    return true;
  };

  const filteredContacts = (contacts.data?.contacts || []).filter((c) =>
    matchesRole(c.role_title),
  );
  const filteredResearch = (people.data?.people || []).filter((p) =>
    matchesRole(p.role),
  );

  return (
    <>
      <div className="split detail-section">
        <div>
          <h3>People with context</h3>
          <p>
            Founders, engineering leaders, engineers and recruiters. LinkedIn
            activity and profile review stay manual.
          </p>
        </div>
        <Button
          onClick={() => {
            setEnrichOpen(true);
            preview.reset();
            execute.reset();
            setApproved(false);
          }}
        >
          Find business email
        </Button>
      </div>
      <div
        className="status-tabs"
        role="group"
        aria-label="Role category filter"
      >
        {[
          ["all", "All roles"],
          ["founder", "Founders & CEOs"],
          ["cto", "CTOs & Leaders"],
          ["engineer", "Engineers"],
          ["recruiter", "Recruiters"],
        ].map(([val, label]) => (
          <button
            key={val}
            className={roleFilter === val ? "selected" : ""}
            aria-pressed={roleFilter === val}
            onClick={() => setRoleFilter(val)}
          >
            {label}
          </button>
        ))}
      </div>
      {contacts.isPending ? (
        <Skeleton />
      ) : contacts.isError ? (
        <ErrorState error={contacts.error} />
      ) : !filteredContacts.length ? (
        <Empty
          title="A name needs evidence."
          description={
            roleFilter !== "all"
              ? `No contacts match the "${roleFilter}" role filter for this team. Select "All roles" or review public research below.`
              : "No retained professional contacts exist for this team. Review an authorized research plan or configure an enrichment provider."
          }
        />
      ) : (
        <div className="company-grid">
          {filteredContacts.map((c) => {
            const unavailable =
              c.do_not_contact ||
              c.retention_expired ||
              c.email_evidence_status === "suppressed_or_stale";
            const isVerifiedMail =
              !unavailable &&
              c.email_evidence_status === "verified_using_authorized_method";
            const isPublishedMail =
              !unavailable &&
              c.email_evidence_status === "published_source_supported";
            const isGuessedMail = c.email_status === "guessed";
            const isProviderMail =
              !unavailable && c.email_evidence_status === "provider_reported";
            const profileUrl = c.linkedin_url || c.professional_url;
            return (
              <article className="company-card" key={c.id}>
                <div className="company-top">
                  <span className="avatar">{c.full_name.slice(0, 1)}</span>
                  <div>
                    <h3>{c.full_name}</h3>
                    <p>
                      {c.role_title} · {c.company}
                    </p>
                  </div>
                  <Badge
                    tone={
                      unavailable
                        ? "amber"
                        : c.confidence === "supported"
                          ? "green"
                          : c.confidence === "provider_reported"
                            ? "neutral"
                            : "amber"
                    }
                  >
                    {unavailable
                      ? c.do_not_contact
                        ? "Suppressed"
                        : "Stale source evidence"
                      : c.confidence === "supported"
                        ? "Supported identity evidence"
                        : c.confidence === "provider_reported"
                          ? "Provider reported"
                          : readable(c.confidence)}
                  </Badge>
                </div>
                {isPublishedMail && c.email_publication_url && (
                  <External href={c.email_publication_url}>
                    Published email source
                  </External>
                )}
                <div className="tag-list">
                  {unavailable ? (
                    <Badge tone="amber">
                      Suppressed or stale email evidence
                    </Badge>
                  ) : isPublishedMail ? (
                    <Badge tone="neutral">
                      Published source supported · mailbox unverified
                    </Badge>
                  ) : isVerifiedMail ? (
                    <Badge tone="green">Verified using authorized method</Badge>
                  ) : isGuessedMail ? (
                    <Badge tone="amber">Guessed email (Unverified)</Badge>
                  ) : isProviderMail ? (
                    <Badge tone="neutral">Provider reported mailbox</Badge>
                  ) : (
                    <Badge tone="neutral">
                      {c.email_status === "verified"
                        ? "Mailbox verification not established"
                        : readable(c.email_status)}{" "}
                      mailbox
                    </Badge>
                  )}
                  <Badge>{readable(c.source)}</Badge>
                  {c.retention_expired && (
                    <Badge tone="amber">Retention expired · Stale</Badge>
                  )}
                </div>
                <p className="section-intro">
                  {c.email
                    ? `Business email: ${c.email}`
                    : "Business email not available"}
                  <br />
                  Last observed {dateLabel(c.last_checked_at)}
                  {c.suppression_reason && (
                    <>
                      <br />
                      <strong>Suppression: </strong>
                      {c.suppression_reason}
                    </>
                  )}
                </p>
                <div className="actions">
                  {profileUrl ? (
                    <External href={profileUrl}>
                      Open professional profile
                    </External>
                  ) : (
                    <small className="muted">No permitted profile link</small>
                  )}
                  <Button onClick={() => setEvidenceId(c.id)}>
                    <ShieldCheck size={12} />
                    Contact evidence
                  </Button>
                  <Button
                    disabled={
                      !c.manual_outreach_review_available || c.do_not_contact
                    }
                    title={
                      c.do_not_contact
                        ? "Contact is suppressed"
                        : !c.manual_outreach_review_available
                          ? "Current recipient and company evidence required"
                          : ""
                    }
                    onClick={() => draft.mutate(c.id)}
                    busy={draft.isPending}
                  >
                    <Mail size={12} />
                    Prepare local draft
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {draft.isError && <ErrorState error={draft.error} />}{" "}
      {people.isError && <ErrorState error={people.error} />}{" "}
      {!!filteredResearch.length && (
        <section className="detail-section spaced">
          <h3>Retained public research</h3>
          {filteredResearch.map((p, i) => (
            <div className="evidence-item" key={`${p.evidence_url}-${i}`}>
              <div className="split">
                <strong>
                  {p.name || "Identity requires review"} ·{" "}
                  {p.role || "Role not established"}
                </strong>
                <Badge
                  tone={
                    p.verification_status === "verified"
                      ? "green"
                      : p.verification_status === "stale"
                        ? "amber"
                        : "neutral"
                  }
                >
                  {readable(p.verification_status)}
                </Badge>
              </div>
              <p>
                Source: {readable(p.source)} · Observed{" "}
                {dateLabel(p.observed_at)}
              </p>
              <External href={p.evidence_url}>Evidence source</External>
              {p.linkedin_url && (
                <div className="spaced">
                  <External href={p.linkedin_url}>
                    Open professional profile manually
                  </External>
                </div>
              )}
            </div>
          ))}
        </section>
      )}
      <details className="spaced">
        <summary>Review an optional founder / leader research plan</summary>
        <Notice>
          Search independently authorized company sources with Serper, limited
          to 5 results. This may cost credits. The backend must have rights,
          credentials and budget configured. No LinkedIn profiles are fetched.
        </Notice>
        <label className="check-label">
          <input
            type="checkbox"
            checked={researchConsent}
            onChange={(e) => setResearchConsent(e.target.checked)}
          />
          I authorize this limited official-company research and its configured
          credit cost.
        </label>
        <Button
          className="spaced"
          disabled={!researchConsent}
          busy={research.isPending}
          onClick={() => research.mutate()}
        >
          <Search size={13} />
          Run approved research
        </Button>
        {research.isError && <ErrorState error={research.error} />}{" "}
        {research.data && (
          <Notice>
            Research completed. Review the actual result before relying on it.
            <pre className="source-text">
              {JSON.stringify(research.data, null, 2)}
            </pre>
          </Notice>
        )}
      </details>
      <Modal
        open={enrichOpen}
        onOpenChange={setEnrichOpen}
        title="Find a professional business contact"
        description="Review existing evidence first. Enrichment is limited to one person; no fallback or bulk lookup."
      >
        <div className="stack">
          <Field label="Provider">
            <Select
              value={provider}
              disabled={
                !!lookupAttempt ||
                execute.isPending ||
                lookupStorageError != null
              }
              onChange={(e) => {
                setProvider(e.target.value);
                preview.reset();
                setApproved(false);
              }}
            >
              <option value="apollo">Apollo</option>
              <option value="signalhire">SignalHire</option>
            </Select>
          </Field>
          <Button onClick={() => preview.mutate()} busy={preview.isPending}>
            Preview permissions and cost
          </Button>
          {preview.isError && <ErrorState error={preview.error} />}{" "}
          {lookupStorageError != null && (
            <ErrorState error={lookupStorageError} />
          )}
          {lookupAttempt && (
            <Notice>
              A lookup request is retained in this browser. Recover its saved
              result before preparing another request.
            </Notice>
          )}
          {lookupAttempt && (
            <Button busy={execute.isPending} onClick={() => execute.mutate()}>
              Recover prior lookup result
            </Button>
          )}
          {preview.data && (
            <>
              <p>
                Saved contacts: {preview.data.cached_contacts?.length ?? 0}.
                Saved public profiles:{" "}
                {preview.data.discovered_people?.length ?? 0}.
              </p>
              {preview.data.provider_plan?.map((plan) => (
                <article key={plan.provider} className="panel panel-body">
                  <strong>{readable(plan.provider)}</strong>
                  <p>
                    Up to {plan.lookup_count_upper_bound} lookup(s). Maximum
                    locally reserved credits:{" "}
                    {plan.reserved_credit_upper_bound ??
                      "account cost review required"}
                    .
                  </p>
                  <p>
                    {plan.configured
                      ? "Provider configuration is present; current account access and balance still require verification."
                      : "Provider credentials or enablement are missing."}
                  </p>
                </article>
              ))}
              {preview.data.blockers?.map((blocker) => (
                <Notice key={blocker}>{readable(blocker)}</Notice>
              ))}
              <Notice>
                Provider-returned email is not mailbox verification. Required
                credentials, terms, account costs and budgets are enforced again
                at execution.
              </Notice>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={approved}
                  onChange={(e) => setApproved(e.target.checked)}
                />
                Approve one lookup using the displayed provider plan and
                configured maximum cost.
              </label>
              <Button
                variant="primary"
                disabled={
                  !approved || !!lookupAttempt || lookupStorageError != null
                }
                busy={execute.isPending}
                onClick={() => execute.mutate()}
              >
                Execute approved lookup
              </Button>
            </>
          )}
          {execute.isError && <ErrorState error={execute.error} />}{" "}
          {execute.data && (
            <Notice>
              Actual result: {readable(execute.data.state)}
              {execute.data.errors?.map((e) => (
                <p key={e}>{e}</p>
              ))}
            </Notice>
          )}
          {execute.data &&
            lookupAttempt &&
            !["billing_uncertain", "queued", "running"].includes(
              execute.data.state,
            ) && (
              <>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={lookupHistoryReviewed}
                    onChange={(e) => setLookupHistoryReviewed(e.target.checked)}
                  />
                  I reviewed the retained lookup result and its remaining
                  blockers
                </label>
                <Button
                  disabled={!lookupHistoryReviewed}
                  onClick={() => {
                    try {
                      clearReviewedLookupAttempt(companyId, execute.data);
                      setLookupAttempt(null);
                      setLookupHistoryReviewed(false);
                      setApproved(false);
                      preview.reset();
                      execute.reset();
                    } catch (error) {
                      setLookupStorageError(error);
                    }
                  }}
                >
                  Prepare another reviewed lookup
                </Button>
              </>
            )}
        </div>
      </Modal>
      <Modal
        open={!!evidenceId}
        onOpenChange={(v) => !v && setEvidenceId(null)}
        title="Contact evidence"
        description="Review provenance, mailbox claims and suppression before preparing outreach."
      >
        {evidence.isPending ? (
          <Skeleton />
        ) : evidence.isError ? (
          <ErrorState error={evidence.error} />
        ) : (
          <ContactReview
            key={`${evidenceId}:${evidenceReview}:${evidence.data.review_version}`}
            contact={evidence.data}
            onRefresh={async () => {
              const result = await evidence.refetch();
              if (result.error) throw result.error;
              setEvidenceReview((value) => value + 1);
            }}
            onSaved={() => {
              client.invalidateQueries({ queryKey: ["contacts"] });
              client.invalidateQueries({ queryKey: ["recommended-contacts"] });
            }}
          />
        )}
      </Modal>
    </>
  );
}
export function People() {
  const [companyId, setCompanyId] = useState("");
  const result = useQuery({
    queryKey: ["people-companies"],
    queryFn: () =>
      post<{ startups: Startup[] }>("startups/search", {
        max_employees: null,
        use_profile: false,
        limit: 100,
      }),
  });
  const selected = result.data?.startups.find(
    (s) => s.company_id === companyId,
  );
  return (
    <>
      <PageTitle
        eyebrow="START WITH A REAL CONNECTION"
        title="The people behind the team."
        description="Founders, engineering leaders and recruiters. Every identity needs a source."
      />
      {result.isPending ? (
        <Skeleton />
      ) : result.isError ? (
        <ErrorState error={result.error} />
      ) : (
        <section className="panel">
          <div className="panel-body">
            <Field label="Choose a saved company">
              <Select
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
              >
                <option value="">Select a company…</option>
                {result.data.startups.map((s) => (
                  <option value={s.company_id} key={s.company_id}>
                    {s.company_name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </section>
      )}
      {selected ? (
        <div className="spaced">
          <CompanyPeople
            companyId={selected.company_id}
            companyName={selected.company_name}
            domain={selected.company_domain}
          />
        </div>
      ) : (
        <div className="spaced">
          <Empty
            title="Good conversations start with context."
            description="Select a saved company to review its professional contacts and source evidence. No LinkedIn login, scraping, automated follows or messages."
          />
        </div>
      )}
    </>
  );
}
