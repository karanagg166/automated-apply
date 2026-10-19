"use client";
import { useState } from "react";
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
export type Contact = {
  id: string;
  company_id: string;
  company: string;
  full_name: string;
  role_title: string;
  linkedin_url?: string | null;
  email?: string | null;
  email_status: string;
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
    [researchConsent, setResearchConsent] = useState(false);
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
    queryFn: () => api<Record<string, unknown>>(`contacts/${evidenceId}`),
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
    mutationFn: () =>
      post<{ state: string; errors: string[] }>(
        `companies/${companyId}/contacts/enrich`,
        { ...payload, idempotency_key: crypto.randomUUID() },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["contacts", companyId] });
      setApproved(false);
    },
  });
  const draft = useMutation({
    mutationFn: (id: string) =>
      post<{ id: string }>("outreach/drafts", {
        contact_id: id,
        purpose: "exploratory",
        writing_style: "concise",
        use_llm: false,
        idempotency_key: crypto.randomUUID(),
      }),
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
  return (
    <>
      <div className="split detail-section">
        <div>
          <h3>People with context</h3>
          <p>
            Authorized professional evidence. LinkedIn activity stays manual.
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
      {contacts.isPending ? (
        <Skeleton />
      ) : contacts.isError ? (
        <ErrorState error={contacts.error} />
      ) : !contacts.data.contacts.length ? (
        <Empty
          title="A name needs evidence."
          description="No retained professional contacts exist for this team. Review an authorized research plan or configure an enrichment provider."
        />
      ) : (
        <div className="company-grid">
          {contacts.data.contacts.map((c) => (
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
                    c.do_not_contact
                      ? "red"
                      : c.confidence === "supported"
                        ? "green"
                        : "amber"
                  }
                >
                  {c.do_not_contact ? "Suppressed" : readable(c.confidence)}
                </Badge>
              </div>
              <div className="tag-list">
                <Badge>{readable(c.email_status)} mailbox</Badge>
                <Badge>{readable(c.source)}</Badge>
                {c.retention_expired && (
                  <Badge tone="amber">Retention expired</Badge>
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
                    {c.suppression_reason}
                  </>
                )}
              </p>
              <div className="actions">
                {c.manual_linkedin_available && c.linkedin_url ? (
                  <External href={c.linkedin_url}>
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
          ))}
        </div>
      )}
      {draft.isError && <ErrorState error={draft.error} />}{" "}
      {people.isError && <ErrorState error={people.error} />}{" "}
      {!!people.data?.people.length && (
        <section className="detail-section spaced">
          <h3>Retained public research</h3>
          {people.data.people.map((p, i) => (
            <div className="evidence-item" key={`${p.evidence_url}-${i}`}>
              <div className="split">
                <strong>
                  {p.name || "Identity requires review"} ·{" "}
                  {p.role || "Role not established"}
                </strong>
                <Badge>{readable(p.verification_status)}</Badge>
              </div>
              <p>
                {readable(p.source)} · {dateLabel(p.observed_at)}
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
          {preview.data && (
            <>
              <pre className="source-text">
                {JSON.stringify(preview.data, null, 2)}
              </pre>
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
                disabled={!approved}
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
          <pre className="source-text">
            {JSON.stringify(evidence.data, null, 2)}
          </pre>
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
