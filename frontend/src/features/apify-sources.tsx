"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, dateLabel, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Modal,
  Notice,
  Skeleton,
} from "@/components/ui";
import type { SourceConfig } from "./job-discovery";

type ApifyStatus = Schema<"ApifyStatus">;
type ActorMetadata = Schema<"ActorMetadata">;

export function ApifySourceManagement() {
  const client = useQueryClient();
  const [metadata, setMetadata] = useState<ActorMetadata | null>(null);
  const status = useQuery({
    queryKey: ["apify-status"],
    queryFn: () => api<ApifyStatus>("integrations/providers/apify"),
  });
  const sources = useQuery({
    queryKey: ["discovery-sources"],
    queryFn: () => api<{ sources: SourceConfig[] }>("discovery/sources"),
  });
  const inspect = useMutation({
    mutationFn: (actor_id: string) =>
      post<ActorMetadata>("integrations/providers/apify/actors/inspect", {
        actor_id,
      }),
    onSuccess: setMetadata,
  });
  const inspectAccount = useMutation({
    mutationFn: () =>
      post<Record<string, unknown>>("integrations/providers/apify/inspect"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["apify-status"] }),
  });
  if (status.isPending) return <Skeleton />;
  if (status.isError) return <ErrorState error={status.error} />;
  const account = status.data;
  const portals =
    sources.data?.sources.filter((s) => s.adapter_type === "apify") || [];
  return (
    <div className="stack spaced" aria-label="Apify source management">
      <section className="panel panel-body stack">
        <div className="split">
          <h3>Apify Source & Actor Management</h3>
          <Badge tone="amber">Execution blocked in this workflow</Badge>
        </div>
        <Notice>
          Metadata inspection uses official provider reads and does not run an
          Actor. A credential or metadata result does not establish collection
          rights, current pricing, or free credits. Chargeable execution
          requires a separate reviewed workflow.
        </Notice>
        <div className="metrics spaced">
          <div className="metric">
            <div className="metric-label">LOCAL BUDGET CAP</div>
            <strong>${account.monthly_limit_usd.toFixed(2)}</strong>
            <small>USD per month max; one shared account budget</small>
            <p>
              ${account.local_budget.reserved_usd.toFixed(2)} reserved · $
              {account.local_budget.remaining_local_usd.toFixed(2)} local
              allowance remaining
            </p>
          </div>
          <div className="metric">
            <div className="metric-label">PER-RUN CAP</div>
            <strong>${account.per_run_cap_usd.toFixed(2)}</strong>
            <small>Local cap is not a provider credit balance</small>
          </div>
          <div className="metric">
            <div className="metric-label">PROVIDER ALLOWANCE</div>
            <strong>
              {account.last_account_inspection
                ? "Inspection recorded"
                : "Unknown"}
            </strong>
            <small>Collection rights and pricing require current review</small>
          </div>
        </div>
        <p>
          Local credential:{" "}
          {account.local_token_configured ? "Configured" : "Not configured"}.
          LinkedIn collection remains disabled. No LinkedIn login, personal
          cookies, automated invitations, or account rotation to evade quotas is
          supported.
        </p>
        <Button
          disabled={!account.local_token_configured}
          busy={inspectAccount.isPending}
          onClick={() => inspectAccount.mutate()}
        >
          Inspect account limits (read only)
        </Button>
        {inspectAccount.isError && <ErrorState error={inspectAccount.error} />}
        {account.last_account_inspection && (
          <details>
            <summary>Observed provider limits and usage</summary>
            <p>
              Provider observations do not authorize collection or establish
              free credits.
            </p>
            <pre className="preserve-lines">
              {JSON.stringify(account.last_account_inspection, null, 2)}
            </pre>
          </details>
        )}
      </section>
      {sources.isError && <ErrorState error={sources.error} />}
      <section className="panel panel-body">
        <h4>Configured discovery sources</h4>
        {portals.length ? (
          <ul>
            {portals.map((s) => (
              <li key={s.id}>
                {s.display_name} · <Badge>{readable(s.availability)}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title="No Apify source configuration observed"
            description="Source availability is supplied by the backend. No execution permission is inferred."
          />
        )}
      </section>
      <div className="company-grid" role="list" aria-label="Actor catalog">
        {account.investigated_actors.map((actor) => (
          <article className="company-card" role="listitem" key={actor}>
            <h4>{actor}</h4>
            <Badge tone="amber">Metadata review only</Badge>
            <p>
              Price, schema, and collection rights are unknown until inspected
              and reviewed. Public metadata does not authorize LinkedIn
              collection.
            </p>
            <div className="actions">
              <Button
                busy={inspect.isPending}
                onClick={() => inspect.mutate(actor)}
              >
                Inspect metadata (read only)
              </Button>
              <Button disabled>Blocked by policy</Button>
            </div>
          </article>
        ))}
      </div>
      {inspect.isError && <ErrorState error={inspect.error} />}
      <Modal
        open={!!metadata}
        onOpenChange={(open) => !open && setMetadata(null)}
        title={`Actor Metadata: ${metadata?.title || metadata?.actor_id || ""}`}
        description="Observed provider metadata. No Actor execution or collection authorization."
      >
        {metadata && (
          <div className="stack">
            <dl>
              <dt>Actor</dt>
              <dd>{metadata.actor_id}</dd>
              <dt>Observed</dt>
              <dd>{dateLabel(metadata.observed_at)}</dd>
              <dt>Collection</dt>
              <dd>{readable(metadata.collection_status)}</dd>
              <dt>Pricing observation</dt>
              <dd>
                {metadata.pricing?.length ? (
                  <pre className="preserve-lines">
                    {JSON.stringify(metadata.pricing, null, 2)}
                  </pre>
                ) : (
                  "Unknown; execution remains blocked"
                )}
              </dd>
              <dt>Input schema</dt>
              <dd>
                {metadata.input_schema
                  ? "Observed; requires review"
                  : "Unknown"}
              </dd>
            </dl>
            <External href={metadata.source_url}>
              Provider metadata source
            </External>
            <Button onClick={() => setMetadata(null)}>Close metadata</Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
