"use client";
import { ChromeProfiles } from "@/features/chrome-profiles";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, dateLabel, readable } from "@/lib/api";
import { Badge, Button, ErrorState, Notice, Select } from "@/components/ui";

type Connection = {
  name: string;
  group: string;
  configuration_status: string;
  state: string;
  identity_verification: string;
  capability_verification: string;
  capabilities: string[];
  last_verification_time?: string | null;
  actual_evidence_type: string;
  blocker?: string | null;
  latest_error_category?: string | null;
  owner_authorization_required: boolean;
  may_consume_paid_credits: boolean;
  safe_next_action: string;
  help_url?: string | null;
  platform?: string | null;
};
type Policy = {
  version: number;
  default: string;
  platforms: Record<string, string>;
};
const policies = [
  "approve",
  "automatic_preferred",
  "draft_only",
  "manual_only",
  "disabled",
];

export function LocalConnections() {
  const client = useQueryClient();
  const connections = useQuery({
    queryKey: ["local-connections"],
    queryFn: () => api<Connection[]>("local-agent/connections"),
    refetchInterval: 30000,
  });
  const policy = useQuery({
    queryKey: ["local-policy"],
    queryFn: () => api<Policy>("local-agent/policy"),
  });
  const [draft, setDraft] = useState<Policy | null>(null);
  const forget = useMutation({
    mutationFn: (platform: string) =>
      api(`local-agent/platforms/${platform}`, { method: "DELETE" }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["local-connections"] }),
  });
  const acceptManual = useMutation({
    mutationFn: (platform: string) =>
      api(`local-agent/platforms/${platform}/accept-manual`, {
        method: "POST",
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["local-connections"] }),
  });
  const save = useMutation({
    mutationFn: (value: Policy) =>
      api<Policy>("local-agent/policy", {
        method: "PUT",
        body: JSON.stringify({
          expected_version: value.version,
          default: value.default,
          platforms: value.platforms,
        }),
      }),
    onSuccess: (value) => {
      client.setQueryData(["local-policy"], value);
      setDraft(null);
    },
  });
  const value = draft || policy.data;
  return (
    <section className="stack" aria-label="Local foundation connections">
      <ChromeProfiles />
      <Notice>
        The dashboard shows the evidence available for each connection.
        Application and provider permissions are managed in their own controls.
      </Notice>
      {connections.isError && <ErrorState error={connections.error} />}
      {connections.isPending && <p>Checking local connection evidence…</p>}
      {[
        ["core", "Core infrastructure"],
        ["platforms", "Job platforms"],
        ["ai", "AI and outreach"],
      ].map(([group, label]) => (
        <section key={group} className="stack" aria-label={label}>
          <h2>{label}</h2>
          <div className="connection-grid">
            {connections.data
              ?.filter((item) => item.group === group)
              .map((item) => (
                <article className="connection-card" key={item.name}>
                  <h3>{item.name}</h3>
                  <Badge
                    tone={
                      item.state === "capability_verified" ? "neutral" : "amber"
                    }
                  >
                    {(
                      {
                        capability_verified: "Verified",
                        browser_session_observed: "Browser session observed",
                        manual_only: "Manual-only",
                        owner_action_required: "Awaiting approval",
                        owner_authorization_required: "Awaiting approval",
                        authenticated: "Authenticated",
                        degraded: "Degraded",
                        unsupported: "Unsupported",
                      } as Record<string, string>
                    )[item.state] || "Not connected"}
                  </Badge>
                  <dl>
                    <dt>Configuration</dt>
                    <dd>{readable(item.configuration_status)}</dd>
                    <dt>Identity</dt>
                    <dd>{readable(item.identity_verification)}</dd>
                    <dt>Capability evidence</dt>
                    <dd>{readable(item.capability_verification)}</dd>
                    <dt>Supported operations</dt>
                    <dd>
                      {item.capabilities.map(readable).join(", ") ||
                        "None verified"}
                    </dd>
                    <dt>Last verification</dt>
                    <dd>{dateLabel(item.last_verification_time)}</dd>
                    <dt>Evidence type</dt>
                    <dd>{readable(item.actual_evidence_type)}</dd>
                    <dt>Latest error / blocker</dt>
                    <dd>
                      {readable(
                        item.latest_error_category ||
                          item.blocker ||
                          "none_recorded",
                      )}
                    </dd>
                    <dt>Owner authorization required</dt>
                    <dd>{item.owner_authorization_required ? "Yes" : "No"}</dd>
                    <dt>May consume paid credits</dt>
                    <dd>{item.may_consume_paid_credits ? "Yes" : "No"}</dd>
                  </dl>
                  <details>
                    <summary>Safe setup / help</summary>
                    <p>{item.safe_next_action}</p>
                    {item.help_url && (
                      <a href={item.help_url} target="_blank" rel="noreferrer">
                        Official setup page
                      </a>
                    )}
                  </details>
                  {item.platform && item.help_url && (
                    <div className="stack">
                      <a href={item.help_url} target="_blank" rel="noreferrer">
                        Connect {item.name}
                      </a>
                      <p>
                        Sign in yourself, then use “Check this portal session”
                        in the browser extension. This checks visible sign-in
                        indicators.
                      </p>
                      <Button
                        disabled={
                          acceptManual.isPending ||
                          !item.owner_authorization_required
                        }
                        onClick={() => acceptManual.mutate(item.platform!)}
                      >
                        Accept manual-only capability for {item.name}
                      </Button>
                      <Button
                        disabled={forget.isPending}
                        onClick={() => forget.mutate(item.platform!)}
                      >
                        Forget {item.name} metadata
                      </Button>
                    </div>
                  )}
                </article>
              ))}
          </div>
        </section>
      ))}
      {forget.isError && <ErrorState error={forget.error} />}
      {acceptManual.isError && <ErrorState error={acceptManual.error} />}
      {forget.isSuccess && (
        <p role="status" aria-label="Platform metadata status">
          Connection metadata forgotten. Your portal browser session is
          unchanged.
        </p>
      )}
      <section className="stack" aria-label="Approval policies">
        <h2>Approval policies</h2>
        <p>
          Preferences never enable an unsupported capability. Version{" "}
          {value?.version || "—"}.
        </p>
        {policy.isError && <ErrorState error={policy.error} />}
        {value && (
          <>
            <label>
              Default policy
              <Select
                aria-label="Default policy"
                value={value.default}
                onChange={(event) =>
                  setDraft({ ...value, default: event.target.value })
                }
              >
                {policies.map((item) => (
                  <option key={item} value={item}>
                    {readable(item)}
                  </option>
                ))}
              </Select>
            </label>
            {Object.entries(value.platforms).map(([platform, setting]) => (
              <label key={platform}>
                {readable(platform)}
                <Select
                  aria-label={readable(platform)}
                  value={setting}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      platforms: {
                        ...value.platforms,
                        [platform]: event.target.value,
                      },
                    })
                  }
                >
                  {(platform === "gmail"
                    ? ["draft_only", "disabled"]
                    : platform === "linkedin"
                      ? ["manual_only", "disabled"]
                      : policies
                  ).map((item) => (
                    <option key={item} value={item}>
                      {readable(item)}
                    </option>
                  ))}
                </Select>
              </label>
            ))}
            <Button
              disabled={!draft}
              busy={save.isPending}
              onClick={() => save.mutate(value)}
            >
              Save approval preferences
            </Button>
          </>
        )}
        {save.isError && <ErrorState error={save.error} />}
        {save.isSuccess && !draft && (
          <p role="status">Approval preferences saved.</p>
        )}
      </section>
    </section>
  );
}
