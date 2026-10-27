"use client";

import { useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, externalUrl, post, readable, Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
} from "@/components/ui";

import { BrowserSubmission, Execution } from "@/features/browser-submission";
import { OpportunityContext } from "@/features/opportunity-context";
import { BrowserSteps } from "@/features/browser-steps";
import { BrowserPage } from "@/features/browser-page";

type BrowserStatus = {
  packet: Schema<"PacketRead">;
  connected: boolean;
  manual: boolean;
  page_review_required?: boolean;
  in_page_network_isolation?: boolean;
  cancellation_pending?: boolean;
  assets?: {
    sealed: boolean;
    requests: number;
    bytes: number;
    blocked: number;
    pending: number;
  } | null;
  recovery: string | null;
  automated_submission_enabled: boolean;
  owner_consent_available: boolean;
  opportunity_context_available: boolean;
  company_source_urls?: string[];
  execution: Execution | null;
  analysis: {
    diagnostic: string;
    page_context: { url: string; title: string; heading: string };
    warnings: string[];
    fields: {
      field_id: string;
      question: string;
      supported: boolean;
      kind: string;
      manual_reason: string | null;
    }[];
    steps?: { label: string; supported: boolean }[];
    validation: {
      field_id: string;
      complete: boolean;
      reason: string | null;
    }[];
  } | null;
};

const closedPackets = new Set<Schema<"PacketRead">["lifecycle_state"]>([
  "user_reported_submitted",
  "provider_confirmed_submitted",
  "submitting",
  "submission_unknown",
  "withdrawn",
  "abandoned",
]);

export function BrowserIntake() {
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [packet, setPacket] = useState<Schema<"PacketRead"> | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [requestKey] = useState(() => crypto.randomUUID());
  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      setPacket(
        await post<Schema<"PacketRead">>("browser-applications", {
          application_url: url,
          company_name: company,
          job_title: title,
          idempotency_key: requestKey,
        }),
      );
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel panel-body">
      <h2>Employer application URL</h2>
      <p>
        Prepare a packet using your saved facts. A dedicated browser opens only
        after your explicit approval. Destinations require configured
        permission.
      </p>
      <Field label="Application URL">
        <Input value={url} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <Field label="Company">
        <Input value={company} onChange={(e) => setCompany(e.target.value)} />
      </Field>
      <Field label="Job title">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Button disabled={busy || !url || !company || !title} onClick={prepare}>
        Prepare application
      </Button>
      {error && <ErrorState error={error} />}
      {packet && (
        <Link className="button primary" href={`/applications/${packet.id}`}>
          Open application assistant
        </Link>
      )}
    </section>
  );
}

export function BrowserAssistant({
  packet,
  hasUnsavedAnswers = false,
}: {
  packet: Schema<"PacketRead">;
  hasUnsavedAnswers?: boolean;
}) {
  const client = useQueryClient();
  const [state, setState] = useState<BrowserStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [working, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const epoch = useRef(0);
  const renderEpoch = epoch.current;
  const busy = working || cancelling;
  const closed =
    closedPackets.has(packet.lifecycle_state) ||
    (!!state && closedPackets.has(state.packet.lifecycle_state));
  const [permission, setPermission] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [contextConfirmed, setContextConfirmed] = useState(false);
  useLayoutEffect(() => {
    setReviewed(false);
    setContextConfirmed(false);
  }, [packet.revision, hasUnsavedAnswers]);
  const [approvedAssetPolicy, setApprovedAssetPolicy] = useState<string | null>(
    null,
  );
  const browserPolicy = useQuery({
    queryKey: ["browser-policy"],
    queryFn: () =>
      api<{ origins: string[]; digest: string }>("browser-applications/policy"),
    retry: false,
  });
  const assetPermission =
    !!browserPolicy.data && approvedAssetPolicy === browserPolicy.data.digest;
  async function consent(fieldId: string, checked: boolean) {
    const generation = epoch.current;
    setBusy(true);
    setError(null);
    try {
      if (!contextConfirmed)
        throw new Error(
          "Confirm the actual company and job before selecting consent.",
        );
      const result = await post<BrowserStatus>(
        `browser-applications/${packet.id}/consent`,
        {
          expected_revision: packet.revision,
          field_id: fieldId,
          checked,
          confirm_page_context: contextConfirmed,
        },
      );
      if (generation !== epoch.current) return;
      setState(result);
      await client.invalidateQueries();
    } catch (e) {
      if (generation === epoch.current) setError(e as Error);
    } finally {
      if (generation === epoch.current) setBusy(false);
    }
  }
  async function cancel() {
    epoch.current++;
    setCancelling(true);
    setCancelled(false);
    setError(null);
    try {
      const route = `browser-applications/${packet.id}`;
      const control = await api<{
        packet_revision: number;
        active_operation: {
          id: string;
          expected_revision: number | null;
        } | null;
      }>(`${route}/operation`);
      setState(
        await post<BrowserStatus>(`${route}/actions`, {
          action: "cancel",
          expected_revision:
            control.active_operation?.expected_revision ??
            control.packet_revision,
          operation_id: control.active_operation?.id ?? null,
        }),
      );
      setReviewed(false);
      setContextConfirmed(false);
      setCancelled(true);
      await client.invalidateQueries();
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
      setCancelling(false);
    }
  }
  async function run(action: string) {
    const generation = epoch.current;
    setBusy(true);
    if (action === "open") setCancelled(false);
    setError(null);
    try {
      const result =
        action === "status"
          ? await api<BrowserStatus>(`browser-applications/${packet.id}`)
          : action === "open"
            ? await post<BrowserStatus>(
                `browser-applications/${packet.id}/open`,
                {
                  expected_revision: packet.revision,
                  approve_dedicated_profile: permission,
                  confirm_destination_permission: permission,
                  confirm_asset_permissions: assetPermission,
                  asset_policy_digest: browserPolicy.data?.digest,
                },
              )
            : await post<BrowserStatus>(
                `browser-applications/${packet.id}/actions`,
                {
                  expected_revision: packet.revision,
                  action,
                  confirm_reviewed_values: reviewed,
                  confirm_page_context: contextConfirmed,
                },
              );
      if (generation !== epoch.current) return;
      setState(result);
      setReviewed(false);
      setContextConfirmed(false);
      await client.invalidateQueries();
    } catch (e) {
      if (generation === epoch.current) setError(e as Error);
    } finally {
      if (generation === epoch.current) setBusy(false);
    }
  }
  return (
    <section className="panel panel-body">
      <h2>Local browser assistant</h2>
      {packet.snapshot && (
        <div
          className="panel panel-body spaced"
          aria-label="Application context"
        >
          <div className="split">
            <div>
              <h3>{packet.snapshot.job_title}</h3>
              <p>
                <strong>
                  {packet.snapshot.company_name || "Company unverified"}
                </strong>
              </p>
              <p>
                Official destination:{" "}
                {packet.snapshot.destination?.application_url ? (
                  <External href={packet.snapshot.destination.application_url}>
                    {packet.snapshot.destination.application_url}
                  </External>
                ) : (
                  <span className="muted">None configured</span>
                )}
              </p>
              <small>
                Source: {readable(packet.snapshot.source_platform)}
                {packet.snapshot.original_job_url && (
                  <span>
                    {" "}
                    ·{" "}
                    <External href={packet.snapshot.original_job_url}>
                      Original posting
                    </External>
                  </span>
                )}
              </small>
            </div>
            <div>
              <h4>Selected resume</h4>
              <p>
                <strong>
                  {packet.snapshot.resume?.selected?.label || "None selected"}
                </strong>{" "}
                <Badge
                  tone={
                    packet.snapshot.resume?.selected?.confirmed
                      ? "green"
                      : "amber"
                  }
                >
                  {packet.snapshot.resume?.selected?.confirmed
                    ? "Confirmed & Verified"
                    : "Needs Confirmation"}
                </Badge>
              </p>
              <small className="muted">
                The dedicated browser can attach the approved canonical PDF when
                upload checks pass. Chrome extension attachments remain manual.
              </small>
            </div>
          </div>
        </div>
      )}
      <Notice>
        Assisted filling uses a dedicated Chrome profile. Submission is manual.
        Required consent, custom controls, embedded forms and additional steps
        need your review on the website. Supported dropdowns may open briefly
        during analysis. Analysis pauses page networking and selects no answer.
        If a page changes values or needs server-loaded choices, use Take Over,
        inspect the values and load the choices yourself before analyzing again.
      </Notice>
      <Notice>
        Non-submission notice: Autofill does NOT submit your application. It
        only populates reviewed fields in your local Chrome session. You must
        inspect every field on the website and submit manually.
      </Notice>
      <Notice>
        Field preservation: Assisted filling preserves existing values already
        entered on the website. Review those values directly on the website;
        assisted filling does not overwrite them.
      </Notice>
      <label>
        <input
          type="checkbox"
          checked={permission}
          onChange={(e) => setPermission(e.target.checked)}
        />{" "}
        I approve a dedicated browser profile and have checked this destination
        permits assistance.
      </label>
      {!!browserPolicy.data?.origins.length && (
        <div>
          <p>
            Approved public script, style and font origins:{" "}
            {browserPolicy.data.origins.join(", ")}
          </p>
          <label>
            <input
              type="checkbox"
              checked={assetPermission}
              onChange={(event) =>
                setApprovedAssetPolicy(
                  event.target.checked ? browserPolicy.data!.digest : null,
                )
              }
            />{" "}
            I approve credential-free loading from these origins before
            analysis. This does not approve third-party APIs or account access.
          </label>
        </div>
      )}
      {browserPolicy.isError && (
        <Notice>
          Browser policy is unavailable. Check the local assistant configuration
          before opening a session.
        </Notice>
      )}
      <div className="actions">
        <Button
          disabled={
            busy ||
            closed ||
            !permission ||
            !browserPolicy.data ||
            (!!browserPolicy.data.origins.length && !assetPermission)
          }
          onClick={() => run("open")}
        >
          Open dedicated browser
        </Button>
        <Button disabled={busy} onClick={() => run("status")}>
          Get status
        </Button>
        <Button
          disabled={
            busy || closed || !state?.connected || state.page_review_required
          }
          onClick={() => run("analyze")}
        >
          Analyze Application
        </Button>
        <Button
          disabled={busy || !state?.connected}
          onClick={() => run("preview")}
        >
          Review
        </Button>
        <Button
          disabled={busy || closed || !state?.connected}
          onClick={() => run("take_over")}
        >
          Take Over
        </Button>
        <Button disabled={cancelling} onClick={cancel}>
          Cancel
        </Button>
      </div>
      {cancelling && (
        <p role="status">
          Cancelling browser work and checking durable status…
        </p>
      )}
      {cancelled && (
        <Notice>
          Browser work closed. Your application history and saved receipts are
          retained.
        </Notice>
      )}
      {state?.cancellation_pending && (
        <Notice>
          Cancellation needs reconciliation. Inspect status before starting new
          browser work.
        </Notice>
      )}
      <label>
        <input
          type="checkbox"
          checked={reviewed}
          disabled={busy || hasUnsavedAnswers || closed}
          onChange={(e) => setReviewed(e.target.checked)}
        />{" "}
        I reviewed the current answers, destination and selected resume below.
      </label>
      <label>
        <input
          type="checkbox"
          checked={contextConfirmed}
          disabled={busy || hasUnsavedAnswers || closed}
          onChange={(e) => setContextConfirmed(e.target.checked)}
        />{" "}
        I confirmed the actual page belongs to this company and job.
      </label>
      <Button
        disabled={
          busy ||
          closed ||
          !state?.connected ||
          !state.analysis ||
          state.manual ||
          state.page_review_required ||
          !reviewed ||
          hasUnsavedAnswers ||
          !contextConfirmed
        }
        onClick={() => run("fill")}
      >
        Fill supported fields
      </Button>
      {state?.connected && !closed && (
        <BrowserPage
          key={`${packet.revision}:${epoch.current}`}
          packetId={packet.id}
          revision={packet.revision}
          blocked={busy || hasUnsavedAnswers}
          ownerAvailable={state.owner_consent_available}
          setBusy={(value) => {
            if (renderEpoch === epoch.current) setBusy(value);
          }}
          refresh={async () => {
            if (renderEpoch !== epoch.current) return;
            const fresh = await api<BrowserStatus>(
              `browser-applications/${packet.id}`,
            );
            if (renderEpoch !== epoch.current) return;
            setReviewed(false);
            setContextConfirmed(false);
            setState(fresh);
            await client.invalidateQueries();
          }}
        />
      )}
      {state?.page_review_required && !closed && (
        <Notice>
          The browser reached another document. Preview and authorize the
          current page before resuming assistance.
        </Notice>
      )}
      <BrowserSubmission
        key={packet.revision}
        packetId={packet.id}
        revision={packet.revision}
        enabled={state?.automated_submission_enabled || false}
        blocked={busy || hasUnsavedAnswers}
        execution={state?.execution || null}
        refresh={async () =>
          setState(
            await api<BrowserStatus>(`browser-applications/${packet.id}`),
          )
        }
      />
      <BrowserSteps
        packetId={packet.id}
        revision={packet.revision}
        enabled={
          state?.analysis?.steps?.some((step) => step.supported) || false
        }
        ownerAvailable={state?.owner_consent_available || false}
        blocked={
          busy ||
          hasUnsavedAnswers ||
          closed ||
          !state?.connected ||
          !!state?.manual
        }
        setBusy={setBusy}
        refresh={async () => {
          setReviewed(false);
          setContextConfirmed(false);
          setState(
            await api<BrowserStatus>(`browser-applications/${packet.id}`),
          );
          await client.invalidateQueries();
        }}
      />
      {state?.opportunity_context_available && (
        <OpportunityContext
          key={epoch.current}
          sourceUrls={state.company_source_urls || []}
          packetId={packet.id}
          revision={packet.revision}
          blocked={busy || closed || !state.connected || state.manual}
          ownerAvailable={state.owner_consent_available}
          setBusy={(value) => {
            if (renderEpoch === epoch.current) setBusy(value);
          }}
          onSaved={async () => {
            if (renderEpoch !== epoch.current) return;
            setReviewed(false);
            setContextConfirmed(false);
            await client.invalidateQueries();
            const fresh = await api<BrowserStatus>(
              `browser-applications/${packet.id}`,
            );
            if (renderEpoch === epoch.current) setState(fresh);
          }}
        />
      )}
      {error && <ErrorState error={error} />}
      {state?.recovery && <Notice>{state.recovery}</Notice>}
      {state?.in_page_network_isolation && (
        <Notice>
          During filling and in-page step review, this browser pauses page
          network activity. Use Take Over for steps that need a server save or
          navigation.
        </Notice>
      )}
      {state?.assets && state.assets.requests > 0 && (
        <Notice>
          Public asset loading {state.assets.sealed ? "closed" : "open"}:{" "}
          {state.assets.requests} requests, {state.assets.blocked} blocked.
          Analysis and Take Over close this loading phase; later external assets
          require manual handoff.
        </Notice>
      )}
      {state?.analysis && (
        <>
          <p>
            Observed page:{" "}
            {state.analysis.page_context?.heading ||
              state.analysis.page_context?.title ||
              "No heading"}{" "}
            · {state.analysis.page_context?.url}
          </p>
          <p role="status">{state.analysis.diagnostic.replaceAll("_", " ")}</p>
          {state.analysis.warnings.map((w) => (
            <Notice key={w}>{w}</Notice>
          ))}
          <ul>
            {state.analysis.fields.map((f) => (
              <li key={f.field_id}>
                {f.question}
                {!f.supported && ` — ${f.manual_reason}`}
                {f.kind === "checkbox" && state.owner_consent_available && (
                  <span className="actions">
                    <Button
                      disabled={
                        busy || closed || !contextConfirmed || state.manual
                      }
                      onClick={() => consent(f.field_id, true)}
                    >
                      Select on website: {f.question}
                    </Button>
                    <Button
                      disabled={
                        busy || closed || !contextConfirmed || state.manual
                      }
                      onClick={() => consent(f.field_id, false)}
                    >
                      Clear on website: {f.question}
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          {state.analysis.validation.some((v) => !v.complete) && (
            <div
              className="stack spaced"
              aria-label="Unfilled mandatory questions"
            >
              <h4>Unfilled or incomplete questions needing attention</h4>
              <ul>
                {state.analysis.validation
                  .filter((v) => !v.complete)
                  .map((v) => (
                    <li key={v.field_id}>
                      {
                        state.analysis?.fields.find(
                          (f) => f.field_id === v.field_id,
                        )?.question
                      }
                      : {v.reason}
                    </li>
                  ))}
              </ul>
            </div>
          )}
          {state.analysis.fields.some((f) => !f.supported) && (
            <div className="stack spaced" aria-label="Unsupported controls">
              <h4>Unsupported fields requiring manual entry</h4>
              <p className="section-intro">
                Unsupported uploads, complex dropdowns, CAPTCHAs, and
                unsupported widgets require manual completion on the website.
                Supported canonical PDF uploads use the approved resume checks:
              </p>
              <ul>
                {state.analysis.fields
                  .filter((f) => !f.supported)
                  .map((f) => (
                    <li key={f.field_id}>
                      <strong>{f.question}</strong> ({readable(f.kind)}):{" "}
                      <span className="muted">
                        {f.manual_reason || "Requires manual entry"}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          )}
          <p>
            Edit and review detected answers in Application fields below. Use
            next-step review for supported in-page forms. Use Take Over for
            server-dependent navigation or unsupported controls, then use Resume
            after manual navigation to review the page you reached. After manual
            submission, record the receipt using the existing submission report.
          </p>
        </>
      )}
    </section>
  );
}
