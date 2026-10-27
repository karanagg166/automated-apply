"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Coins,
  Cpu,
  Database,
  ExternalLink,
  Eye,
  Info,
  Lock,
  Play,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ZapOff,
} from "lucide-react";
import { api, dateLabel, post, readable } from "@/lib/api";
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
  Select,
  Skeleton,
} from "@/components/ui";
import type {
  SourceConfig,
  JobDiscoveryPreview,
  JobDiscoveryRun,
} from "./job-discovery";

type ProviderRuntime = {
  provider: string;
  configured: boolean;
  authorized: boolean;
  live_verified: boolean;
  capability: string;
  budget: number;
  next_action: string;
};

type ActorDetail = {
  actor_id: string;
  display_name: string;
  description: string;
  status:
    | "available"
    | "configuration_required"
    | "unauthorized"
    | "restricted"
    | "unsupported";
  pricing_model: "PAY_PER_EVENT" | "DIRECT_FREE" | "ACCOUNT_DEPENDENT";
  cost_estimate_usd: number;
  data_source_permission: "verified" | "review_required" | "prohibited";
  last_sync_at: string | null;
  results_count: {
    discovered: number;
    inserted: number;
    duplicate: number;
    failed: number;
  } | null;
  last_error: string | null;
  documentation_url?: string;
  schema_fields: string[];
};

const KNOWN_ACTORS: ActorDetail[] = [
  {
    actor_id: "apify/direct-web-discovery",
    display_name: "Web Job Discovery Adapter",
    description:
      "Bounded public web index lookup for startup postings. Enforces operator review and strict monthly budget.",
    status: "available",
    pricing_model: "PAY_PER_EVENT",
    cost_estimate_usd: 0.05,
    data_source_permission: "verified",
    last_sync_at: null,
    results_count: { discovered: 0, inserted: 0, duplicate: 0, failed: 0 },
    last_error: null,
    documentation_url: "https://docs.apify.com/actors",
    schema_fields: ["keywords", "locations", "limit"],
  },
  {
    actor_id: "apify/naukri-scraper",
    display_name: "Naukri Portal Adapter (Restricted)",
    description:
      "Commercial Indian job portal. Requires verified platform linking protocol. No credential import or automated sessions.",
    status: "restricted",
    pricing_model: "ACCOUNT_DEPENDENT",
    cost_estimate_usd: 0.1,
    data_source_permission: "prohibited",
    last_sync_at: null,
    results_count: null,
    last_error:
      "Platform terms require manual handoff. Automated scraping prohibited.",
    schema_fields: ["query", "location"],
  },
  {
    actor_id: "apify/instahyre-scraper",
    display_name: "Instahyre Portal Adapter (Restricted)",
    description:
      "Curated Indian tech hiring portal. Manual candidate handoff only. Automated messaging and scraping strictly disallowed.",
    status: "restricted",
    pricing_model: "ACCOUNT_DEPENDENT",
    cost_estimate_usd: 0.1,
    data_source_permission: "prohibited",
    last_sync_at: null,
    results_count: null,
    last_error:
      "No approved linking protocol. Use manual handoff on official site.",
    schema_fields: ["skills", "experience"],
  },
  {
    actor_id: "apify/linkedin-jobs-scraper",
    display_name: "LinkedIn Portal Adapter (Unauthorized)",
    description:
      "Strictly prohibited: No LinkedIn login, cookie import, automated invitations, or message sending is permitted.",
    status: "unauthorized",
    pricing_model: "ACCOUNT_DEPENDENT",
    cost_estimate_usd: 0.25,
    data_source_permission: "prohibited",
    last_sync_at: null,
    results_count: null,
    last_error:
      "Safety policy: LinkedIn credential access and automated interaction prohibited.",
    schema_fields: [],
  },
];

export function ApifySourceManagement() {
  const client = useQueryClient();
  const consentId = useId();

  const [selectedActor, setSelectedActor] = useState<ActorDetail | null>(null);
  const [inspectModalOpen, setInspectModalOpen] = useState(false);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [costConsent, setCostConsent] = useState(false);
  const [permissionConsent, setPermissionConsent] = useState(false);
  const [keywords, setKeywords] = useState("Python, FastAPI");
  const [locations, setLocations] = useState("India, Remote");
  const [limit, setLimit] = useState(10);
  const [previewResult, setPreviewResult] =
    useState<JobDiscoveryPreview | null>(null);
  const [runResult, setRunResult] = useState<JobDiscoveryRun | null>(null);

  const sourcesQuery = useQuery({
    queryKey: ["discovery-sources"],
    queryFn: () =>
      api<{
        sources: SourceConfig[];
        people_search?: Record<string, unknown>;
      }>("discovery/sources"),
  });

  const connectionsQuery = useQuery({
    queryKey: ["runtime-connections"],
    queryFn: () =>
      api<{ providers: ProviderRuntime[] }>("dashboard/connections"),
  });

  const apifyRuntime = connectionsQuery.data?.providers.find(
    (p) => p.provider === "apify",
  );

  const previewMutation = useMutation({
    mutationFn: (actor: ActorDetail) =>
      post<JobDiscoveryPreview>("discovery/preview", {
        source: "apify",
        query: {
          keywords: keywords
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean),
          locations: locations
            .split(",")
            .map((l) => l.trim())
            .filter(Boolean),
          remote_preference: "any",
          employment_types: [],
          page: 1,
          limit,
          max_age_days: null,
        },
        idempotency_key: `preview_apify_${Date.now()}`,
        allow_paid: false,
        use_profile: false,
        manual_jobs: [],
      }),
    onSuccess: (data) => {
      setPreviewResult(data);
    },
  });

  const executeMutation = useMutation({
    mutationFn: (actor: ActorDetail) => {
      if (actor.status !== "available" || !apifyRuntime?.authorized) {
        throw new Error(
          "Triggering an unavailable or unauthorized actor is strictly forbidden.",
        );
      }
      return post<JobDiscoveryRun>("discovery/runs", {
        source: "apify",
        query: {
          keywords: keywords
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean),
          locations: locations
            .split(",")
            .map((l) => l.trim())
            .filter(Boolean),
          remote_preference: "any",
          employment_types: [],
          page: 1,
          limit,
          max_age_days: null,
        },
        idempotency_key: `run_apify_${Date.now()}`,
        allow_paid: true,
        use_profile: false,
        manual_jobs: [],
      });
    },
    onSuccess: (data) => {
      setRunResult(data);
      setRunModalOpen(false);
      setCostConsent(false);
      setPermissionConsent(false);
      client.invalidateQueries({ queryKey: ["jobs"] });
      client.invalidateQueries({ queryKey: ["startups"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const monthlyBudget = apifyRuntime ? apifyRuntime.budget : 5.0;
  const isApifyConfigured = Boolean(apifyRuntime?.configured);
  const isApifyAuthorized = Boolean(apifyRuntime?.authorized);

  return (
    <div className="stack spaced" aria-label="Apify source management">
      <div className="panel panel-body">
        <div className="split">
          <div>
            <h3>Apify Source & Actor Management</h3>
            <p className="section-intro">
              Explicit, operator-reviewed Actor controls. Distinguishes free
              metadata lookup from chargeable execution.
            </p>
          </div>
          <Badge
            tone={isApifyConfigured && isApifyAuthorized ? "green" : "amber"}
          >
            {isApifyConfigured
              ? isApifyAuthorized
                ? "Configured & Authorized"
                : "Authorization Required"
              : "Unconfigured"}
          </Badge>
        </div>

        <Notice>
          <strong>Credit & Policy Notice:</strong> Free subscription tier does
          not imply zero cost. Certain Actors consume platform credits.
          Triggering unavailable or unauthorized Actors is disabled. No LinkedIn
          login, cookie import, automated invitations or messaging is permitted.
        </Notice>

        <div className="metrics spaced">
          <div className="metric">
            <div className="metric-label">
              LOCAL BUDGET CAP
              <Coins size={14} />
            </div>
            <strong>${monthlyBudget.toFixed(2)}</strong>
            <small>USD per month max</small>
          </div>
          <div className="metric">
            <div className="metric-label">
              EXECUTION PRICING
              <Database size={14} />
            </div>
            <strong style={{ fontSize: "1rem" }}>PAY_PER_EVENT</strong>
            <small>Strict per-item caps enforced</small>
          </div>
          <div className="metric">
            <div className="metric-label">
              PERMISSION STATUS
              <ShieldCheck size={14} />
            </div>
            <strong>
              {isApifyAuthorized ? "Operator Reviewed" : "Review Required"}
            </strong>
            <small>{apifyRuntime?.next_action || "Check backend/.env"}</small>
          </div>
        </div>
      </div>

      <div className="company-grid" role="list" aria-label="Actor catalog">
        {KNOWN_ACTORS.map((actor) => {
          const isAvailable =
            actor.status === "available" &&
            isApifyConfigured &&
            isApifyAuthorized;
          const isRestricted =
            actor.status === "restricted" ||
            actor.data_source_permission === "prohibited";
          const isUnauthorized =
            actor.status === "unauthorized" || !isApifyAuthorized;

          return (
            <article
              className="company-card"
              key={actor.actor_id}
              role="listitem"
            >
              <div className="company-top">
                <span className="row-icon">
                  <Cpu size={20} />
                </span>
                <div>
                  <h4>{actor.display_name}</h4>
                  <p
                    className="muted"
                    style={{ fontSize: "0.8rem", wordBreak: "break-all" }}
                  >
                    {actor.actor_id}
                  </p>
                </div>
                <Badge
                  tone={
                    isAvailable
                      ? "green"
                      : isRestricted
                        ? "red"
                        : isUnauthorized
                          ? "amber"
                          : "neutral"
                  }
                >
                  {readable(actor.status)}
                </Badge>
              </div>

              <p className="company-description">{actor.description}</p>

              <dl>
                <dt>Pricing model</dt>
                <dd>
                  {actor.pricing_model === "PAY_PER_EVENT" ? (
                    <Badge tone="amber">
                      PAY_PER_EVENT (~${actor.cost_estimate_usd}/run)
                    </Badge>
                  ) : actor.pricing_model === "DIRECT_FREE" ? (
                    <Badge tone="green">Direct API Free</Badge>
                  ) : (
                    <Badge tone="neutral">
                      Account dependent (credits apply)
                    </Badge>
                  )}
                </dd>
                <dt>Data-source permission</dt>
                <dd>
                  <Badge
                    tone={
                      actor.data_source_permission === "verified"
                        ? "green"
                        : "red"
                    }
                  >
                    {readable(actor.data_source_permission)}
                  </Badge>
                </dd>
                <dt>Last successful sync</dt>
                <dd>{dateLabel(actor.last_sync_at)}</dd>
                <dt>Last recorded error</dt>
                <dd
                  className="preserve-lines"
                  style={{ fontSize: "0.8rem", color: "var(--red)" }}
                >
                  {actor.last_error || "None"}
                </dd>
              </dl>

              <div className="actions" style={{ marginTop: "1rem" }}>
                <Button
                  onClick={() => {
                    setSelectedActor(actor);
                    setInspectModalOpen(true);
                  }}
                  title="Free metadata and schema inspection"
                >
                  <Eye size={13} />
                  Inspect metadata (Free)
                </Button>

                <Button
                  variant="primary"
                  disabled={!isAvailable}
                  title={
                    !isAvailable
                      ? "Execution blocked: Actor is unauthorized, restricted, or unconfigured."
                      : "Preview and execute bounded search"
                  }
                  onClick={() => {
                    setSelectedActor(actor);
                    setCostConsent(false);
                    setPermissionConsent(false);
                    setPreviewResult(null);
                    setRunModalOpen(true);
                  }}
                >
                  {isAvailable ? (
                    <>
                      <Play size={13} />
                      Configure & Run
                    </>
                  ) : (
                    <>
                      <Lock size={13} />
                      Blocked by policy
                    </>
                  )}
                </Button>
              </div>
            </article>
          );
        })}
      </div>

      {runResult && (
        <Notice>
          <div className="split">
            <div>
              <strong>Last Execution Completed:</strong> {runResult.id} (Status:{" "}
              {runResult.status})
              <p>
                Discovered: {runResult.counts.discovered ?? 0} · Inserted:{" "}
                {runResult.counts.inserted ?? 0} · Duplicates:{" "}
                {runResult.counts.duplicate ?? 0}
              </p>
            </div>
            <Badge tone={runResult.status === "completed" ? "green" : "amber"}>
              {runResult.status}
            </Badge>
          </div>
        </Notice>
      )}

      {/* Metadata Inspection Modal (Free) */}
      <Modal
        open={inspectModalOpen}
        onOpenChange={setInspectModalOpen}
        title={`Actor Metadata: ${selectedActor?.display_name || ""}`}
        description="Free schema and capability review. Metadata inspection does not invoke the provider or consume credits."
      >
        {selectedActor && (
          <div className="stack">
            <dl>
              <dt>Actor Identifier</dt>
              <dd>
                <code>{selectedActor.actor_id}</code>
              </dd>
              <dt>Execution Charge Model</dt>
              <dd>
                {selectedActor.pricing_model === "PAY_PER_EVENT"
                  ? "Chargeable via Apify platform credits (Pay Per Event). Requires explicit run consent."
                  : "Direct public read or manual handoff only."}
              </dd>
              <dt>Supported Field Mappings</dt>
              <dd>
                {selectedActor.schema_fields.length > 0 ? (
                  <div className="tag-list">
                    {selectedActor.schema_fields.map((f) => (
                      <Badge key={f}>{f}</Badge>
                    ))}
                  </div>
                ) : (
                  <span className="muted">No schema fields permitted</span>
                )}
              </dd>
              <dt>Platform Rights & Licensing</dt>
              <dd>
                {selectedActor.data_source_permission === "verified"
                  ? "Verified: Source conforms to public index access policies."
                  : "Prohibited: Portal terms require manual handoff. No automated access."}
              </dd>
            </dl>

            <Notice>
              Automated apply never rotates accounts to evade platform limits or
              terms. All credentials remain on your private backend.
            </Notice>

            <Button onClick={() => setInspectModalOpen(false)}>
              Close metadata
            </Button>
          </div>
        )}
      </Modal>

      {/* Execution Modal with Strict Consent */}
      <Modal
        open={runModalOpen}
        onOpenChange={setRunModalOpen}
        title={`Execute Actor: ${selectedActor?.display_name || ""}`}
        description="Verify estimated usage, required criteria, and explicit consent before execution."
      >
        {selectedActor && (
          <div className="stack">
            <Field
              label="Titles / Technologies"
              hint="Comma-separated keywords for bounded search"
            >
              <Input
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
              />
            </Field>

            <Field
              label="Target Locations"
              hint="Comma-separated cities or regions"
            >
              <Input
                value={locations}
                onChange={(e) => setLocations(e.target.value)}
              />
            </Field>

            <Field
              label="Max Results Limit"
              hint="Strict per-run result limit (max 20)"
            >
              <Input
                type="number"
                min={1}
                max={20}
                value={limit}
                onChange={(e) =>
                  setLimit(Math.min(20, Math.max(1, Number(e.target.value))))
                }
              />
            </Field>

            <div className="actions">
              <Button
                onClick={() => previewMutation.mutate(selectedActor)}
                busy={previewMutation.isPending}
              >
                Preview Cost & Scope
              </Button>
            </div>

            {previewMutation.isError && (
              <ErrorState error={previewMutation.error} />
            )}

            {previewResult && (
              <div className="panel panel-body spaced">
                <h4>Preview Estimation</h4>
                <p>
                  {previewResult.message || "Estimated provider calls bounded."}
                </p>
                <dl>
                  <dt>Estimated Cost</dt>
                  <dd>
                    {previewResult.estimated_usd !== null
                      ? `$${previewResult.estimated_usd.toFixed(4)} USD`
                      : `~$${selectedActor.cost_estimate_usd} USD`}
                  </dd>
                  <dt>Provider Calls</dt>
                  <dd>{previewResult.provider_calls}</dd>
                </dl>
              </div>
            )}

            <label
              className="check-label"
              htmlFor={`cost-consent-${consentId}`}
            >
              <input
                id={`cost-consent-${consentId}`}
                type="checkbox"
                checked={costConsent}
                onChange={(e) => setCostConsent(e.target.checked)}
              />
              I understand this execution consumes platform credits up to the
              configured monthly limit of ${monthlyBudget.toFixed(2)}.
            </label>

            <label
              className="check-label"
              htmlFor={`perm-consent-${consentId}`}
            >
              <input
                id={`perm-consent-${consentId}`}
                type="checkbox"
                checked={permissionConsent}
                onChange={(e) => setPermissionConsent(e.target.checked)}
              />
              I confirm I have reviewed data-source rights and this search
              complies with official terms.
            </label>

            {executeMutation.isError && (
              <ErrorState error={executeMutation.error} />
            )}

            <div className="actions">
              <Button
                variant="primary"
                disabled={
                  !costConsent ||
                  !permissionConsent ||
                  selectedActor.status !== "available" ||
                  executeMutation.isPending
                }
                busy={executeMutation.isPending}
                onClick={() => executeMutation.mutate(selectedActor)}
              >
                Execute approved run
              </Button>
              <Button variant="ghost" onClick={() => setRunModalOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
