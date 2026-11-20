"use client";

import { useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
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
import { ChromeProfiles } from "@/features/chrome-profiles";

export function detectAtsPlatform(url?: string | null): {
  name: string;
  isKnownAts: boolean;
  supportedControls: string[];
  manualControls: string[];
} {
  let host = "";
  let pathname = "";
  try {
    const parsed = new URL(url || "");
    host = parsed.hostname.toLowerCase();
    pathname = parsed.pathname;
  } catch {
    /* Await a valid inspected destination. */
  }
  const known = [
    ["greenhouse.io", "Greenhouse ATS"],
    ["lever.co", "Lever ATS"],
    ["ashbyhq.com", "Ashby ATS"],
    ["smartrecruiters.com", "SmartRecruiters ATS"],
    ["myworkdayjobs.com", "Workday Portal"],
    ["workday.com", "Workday Portal"],
    ["taleo.net", "Taleo Enterprise"],
    ["oraclecloud.com", "Oracle Careers"],
    ["simplify.jobs", "Simplify Jobs"],
  ].find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  const google = host === "docs.google.com" && pathname.startsWith("/forms/");
  return {
    name:
      known?.[1] || (google ? "Google Forms" : "Custom HTML Application Form"),
    isKnownAts: Boolean(known || google),
    supportedControls: [],
    manualControls: [
      "Legal consent, sensitive disclosures, CAPTCHA and submission",
    ],
  };
}

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
        Prepare a packet using your saved facts. Use your selected connected
        Chrome profile. Isolated browser testing requires a separate explicit
        choice. Destinations require permission.
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

export function BrowserAssistant(props: {
  packet: Schema<"PacketRead">;
  hasUnsavedAnswers?: boolean;
  onRefresh?: () => void;
  nativeRuntime?: boolean;
}) {
  // Returning to an application defaults to the connected browser.
  const [mode, setMode] = useState<"extension" | "isolated">("extension");
  return (
    <>
      <section className="panel panel-body">
        <Field label="Application browser">
          <select
            aria-label="Application browser"
            value={mode}
            onChange={(event) =>
              setMode(event.target.value as "extension" | "isolated")
            }
          >
            <option value="extension">
              {props.nativeRuntime
                ? "Use connected browser extension"
                : "Use connected Chrome extension"}
            </option>
            <option value="isolated">
              {props.nativeRuntime
                ? "Saved isolated browser history"
                : "Use isolated automation browser"}
            </option>
          </select>
        </Field>
        {mode === "isolated" && !props.nativeRuntime && (
          <Notice>
            Isolated testing opens a separate dedicated browser profile. It does
            not reuse your personal Chrome session. Existing Chrome tasks remain
            paused or owner-controlled; switching this view grants no filling
            permission.
          </Notice>
        )}
      </section>
      {mode === "extension" ? (
        <ChromeProfiles
          packet={props.packet}
          hasUnsavedAnswers={props.hasUnsavedAnswers}
        />
      ) : props.nativeRuntime ? (
        <SavedBrowserReview id={props.packet.id} />
      ) : (
        <IsolatedBrowserAssistant {...props} />
      )}
    </>
  );
}

function SavedBrowserReview({ id }: { id: string }) {
  const review = useQuery({
    queryKey: ["saved-browser-review", id],
    queryFn: () => api<BrowserStatus>(`browser-applications/${id}`),
  });
  const data = review.data;
  return (
    <section
      className="panel panel-body stack"
      aria-label="Saved isolated browser history"
    >
      <h2>Saved browser review</h2>
      {review.isPending && <p role="status">Loading saved review…</p>}
      {review.error && <ErrorState error={review.error} />}
      {data && (
        <>
          <p>
            Packet revision {data.packet.revision} ·{" "}
            {readable(data.packet.lifecycle_state)}
          </p>
          {data.analysis ? (
            <>
              <p>
                {readable(data.analysis.diagnostic)} ·{" "}
                {data.analysis.fields?.length ?? 0} saved fields
              </p>
              {(data.analysis.warnings ?? []).map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </>
          ) : (
            <p>No isolated browser review is saved for this packet.</p>
          )}
          {data.recovery && <Notice>{data.recovery}</Notice>}
        </>
      )}
    </section>
  );
}

function IsolatedBrowserAssistant({
  packet,
  hasUnsavedAnswers = false,
  onRefresh,
}: {
  packet: Schema<"PacketRead">;
  hasUnsavedAnswers?: boolean;
  onRefresh?: () => void;
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

  const currentStage: {
    label: string;
    tone: "green" | "amber" | "red" | "neutral";
    description: string;
  } = (() => {
    if (
      packet.lifecycle_state === "submission_unknown" ||
      state?.packet?.lifecycle_state === "submission_unknown"
    ) {
      return {
        label: "Submission unknown",
        tone: "red",
        description:
          "Submission confirmation could not be verified on the employer website. Inspect your application status directly.",
      };
    }
    if (
      state?.manual ||
      state?.analysis?.diagnostic === "manual_required" ||
      state?.analysis?.diagnostic === "unsupported_fields"
    ) {
      return {
        label: "Manual required",
        tone: "amber",
        description:
          "Manual intervention required on website (CAPTCHA, unsupported controls, or server navigation).",
      };
    }
    if (
      state?.analysis?.validation?.some((v) => !v.complete) ||
      (packet.fields &&
        packet.fields.some(
          (f) =>
            f.validation_status === "needs_input" ||
            (f as any).review_status === "needs_input",
        ))
    ) {
      return {
        label: "Needs input",
        tone: "amber",
        description:
          "One or more required questions lack factual candidate evidence. Answer them in 'Needs your input'.",
      };
    }
    if (
      state?.analysis?.diagnostic === "filled_review_on_website" ||
      (state?.execution as any)?.state === "form_filled" ||
      (state?.execution as any)?.status === "form_filled" ||
      state?.execution?.state === "completed" ||
      (state?.execution as any)?.status === "completed"
    ) {
      return {
        label: "Filled (Not submitted)",
        tone: "green",
        description:
          "Supported fields are filled in your local Chrome session. You must review and submit manually on the employer site.",
      };
    }
    if (
      state?.connected &&
      state?.analysis &&
      reviewed &&
      contextConfirmed &&
      !hasUnsavedAnswers
    ) {
      return {
        label: "Ready to fill",
        tone: "green",
        description:
          "Page context confirmed and answers reviewed. Ready to fill supported fields.",
      };
    }
    if (state?.connected && state?.analysis) {
      return {
        label: "Ready for review",
        tone: "neutral",
        description:
          "Form fields analyzed. Review candidate answers and confirm page context before filling.",
      };
    }
    if (state?.analysis) {
      return {
        label: "Inspected",
        tone: "neutral",
        description:
          "Form structure inspected. Connect browser session to review and fill.",
      };
    }
    return {
      label: "Ready to inspect",
      tone: "neutral",
      description: "Open dedicated browser and analyze application page.",
    };
  })();
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
                  executor: "isolated_browser",
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
                {packet.snapshot.destination?.valid ? (
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
                    ? "Selection confirmed"
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
      {packet.snapshot && (
        <div
          className="metrics spaced"
          aria-label="Application readiness indicators"
        >
          <div className="metric">
            <div className="metric-label">DESTINATION READY</div>
            <p>
              {packet.snapshot.destination?.valid ? (
                <Badge tone="green">Configured</Badge>
              ) : (
                <Badge tone="amber">Needs destination review</Badge>
              )}
            </p>
          </div>
          <div className="metric">
            <div className="metric-label">RESUME CONFIRMED</div>
            <p>
              {packet.snapshot.resume?.selected?.confirmed ? (
                <Badge tone="green">Resume selection confirmed</Badge>
              ) : (
                <Badge tone="amber">Needs Review</Badge>
              )}
            </p>
          </div>
          <div className="metric">
            <div className="metric-label">ASSISTANT STATUS</div>
            <p>
              <Badge tone={state?.connected ? "green" : "neutral"}>
                {!state
                  ? "Not observed"
                  : state.connected
                    ? "Connected"
                    : "Disconnected"}
              </Badge>
            </p>
          </div>
          <div className="metric">
            <div className="metric-label">SUBMISSION MODE</div>
            <p>
              <Badge tone="neutral">Manual review & handoff</Badge>
            </p>
          </div>
          <div className="metric">
            <div className="metric-label">WORKFLOW STAGE</div>
            <p>
              <Badge tone={currentStage.tone}>{currentStage.label}</Badge>
            </p>
          </div>
        </div>
      )}

      {/* Universal Website & ATS Detector Card */}
      {(() => {
        const detected = detectAtsPlatform(
          state?.analysis?.page_context?.url ||
            packet.snapshot?.destination?.application_url,
        );
        return (
          <div
            className="panel panel-body spaced"
            aria-label="Universal Form Assistant Detection"
            style={{ background: "var(--surface-sunken, rgba(0,0,0,0.02))" }}
          >
            <div className="split">
              <div>
                <strong className="text-xs muted">
                  UNIVERSAL FORM ASSISTANT — DETECTED PLATFORM:
                </strong>
                <h4 style={{ margin: "0.25rem 0" }}>
                  {detected.name}{" "}
                  <Badge tone="neutral">
                    {detected.isKnownAts
                      ? "Recognized URL host"
                      : "HTML Form Inspector"}
                  </Badge>
                </h4>
                <p className="text-xs muted">
                  Application Destination:{" "}
                  {packet.snapshot?.destination?.application_url ||
                    "Destination URL not provided"}
                </p>
              </div>
              <div className="text-right">
                <Badge tone={state?.analysis ? "green" : "neutral"}>
                  {state?.analysis
                    ? `${state.analysis.fields.length} Fields Recognized`
                    : "Inspection Pending"}
                </Badge>
              </div>
            </div>

            <p className="text-xs muted">
              URL recognition does not verify a vendor adapter, site permission,
              or compatibility. Each page and step requires inspection and
              review.
            </p>
            <div className="grid-2" style={{ marginTop: "0.5rem" }}>
              <div className="text-xs">
                <strong className="text-green-700">
                  Supported fields from current inspection:
                </strong>
                <ul style={{ margin: "0.25rem 0 0 1rem", padding: 0 }}>
                  {state?.analysis?.fields
                    .filter((field) => field.supported)
                    .map((field) => (
                      <li key={field.field_id}>
                        {field.question} ({field.kind})
                      </li>
                    ))}
                  {!state?.analysis && (
                    <li>Inspect this page to determine field support.</li>
                  )}
                </ul>
              </div>
              <div className="text-xs">
                <strong className="text-amber-700">
                  Manual Entry Required (Non-Automated):
                </strong>
                <ul style={{ margin: "0.25rem 0 0 1rem", padding: 0 }}>
                  {(
                    state?.analysis?.fields
                      .filter((field) => !field.supported)
                      .map(
                        (field) =>
                          `${field.question}: ${field.manual_reason || "Manual review required"}`,
                      ) || []
                  )
                    .concat(detected.manualControls)
                    .map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                </ul>
              </div>
            </div>
          </div>
        );
      })()}
      {currentStage.label.startsWith("Filled") && (
        <Notice>
          <div className="split">
            <div>
              <strong>Non-Submission Guarantee — Application Filled:</strong>{" "}
              Assisted filling has populated your reviewed answers into the
              local browser. This application has NOT been submitted. Please
              inspect every field on the employer form and click submit
              manually.
            </div>
            <Badge tone="green">NOT SUBMITTED</Badge>
          </div>
        </Notice>
      )}
      <Notice>
        <strong>Manual Handoff & Non-Submission Guarantee:</strong> Assisted
        filling populates reviewed fields into your local Chrome session. It
        NEVER submits your application to the employer. When filling finishes,
        inspect every field on the official employer website and submit
        manually.
      </Notice>
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
      {error && (
        <ErrorState
          error={error}
          retry={
            error.message.includes("refresh the packet") && onRefresh
              ? () => {
                  setError(null);
                  onRefresh();
                }
              : undefined
          }
        />
      )}
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

          {/* Form Field Completion Metrics */}
          <div
            className="metrics spaced"
            aria-label="Form completion count"
            style={{ margin: "0.75rem 0" }}
          >
            <div className="metric">
              <div className="metric-label">RECOGNIZED FIELDS</div>
              <p>
                <strong>{state.analysis.fields.length}</strong>
              </p>
            </div>
            <div className="metric">
              <div className="metric-label">SUPPORTED CONTROLS</div>
              <p>
                <Badge tone="green">
                  {state.analysis.fields.filter((f) => f.supported).length}{" "}
                  supported
                </Badge>
              </p>
            </div>
            <div className="metric">
              <div className="metric-label">READY TO FILL</div>
              <p>
                <Badge tone="green">
                  {
                    (state.analysis.validation || []).filter((v) => v.complete)
                      .length
                  }{" "}
                  ready
                </Badge>
              </p>
            </div>
            <div className="metric">
              <div className="metric-label">NEEDS INPUT</div>
              <p>
                <Badge
                  tone={
                    (state.analysis.validation || []).some((v) => !v.complete)
                      ? "amber"
                      : "green"
                  }
                >
                  {
                    (state.analysis.validation || []).filter((v) => !v.complete)
                      .length
                  }{" "}
                  incomplete
                </Badge>
              </p>
            </div>
            <div className="metric">
              <div className="metric-label">MANUAL REQUIRED</div>
              <p>
                <Badge tone="neutral">
                  {state.analysis.fields.filter((f) => !f.supported).length}{" "}
                  manual
                </Badge>
              </p>
            </div>
          </div>
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
          {Boolean(state.analysis.validation?.some((v) => !v.complete)) && (
            <div
              className="stack spaced"
              aria-label="Unfilled mandatory questions"
            >
              <h4>Unfilled or incomplete questions needing attention</h4>
              <ul>
                {(state.analysis.validation || [])
                  .filter((v) => !v.complete)
                  .map((v) => (
                    <li
                      key={v.field_id}
                      className="split"
                      style={{ alignItems: "center", marginTop: "0.25rem" }}
                    >
                      <span>
                        <strong>
                          {
                            state.analysis?.fields.find(
                              (f) => f.field_id === v.field_id,
                            )?.question
                          }
                        </strong>
                        : {v.reason}
                      </span>
                      {(() => {
                        const matchingField = (state.packet.fields || []).find(
                          (field) => field.id === v.field_id,
                        );
                        const prov = matchingField?.provenance as
                          Record<string, unknown> | undefined;
                        const missingInputId =
                          typeof prov?.missing_input_id === "string"
                            ? prov.missing_input_id
                            : undefined;
                        return (
                          <Link
                            className="button text-xs"
                            href={
                              missingInputId
                                ? `/needs-input?missing_input=${encodeURIComponent(missingInputId)}`
                                : "/needs-input"
                            }
                          >
                            Answer in Needs Input
                            <ArrowUpRight size={11} />
                          </Link>
                        );
                      })()}
                    </li>
                  ))}
              </ul>
              <div className="actions" style={{ marginTop: "0.5rem" }}>
                <Link className="button primary" href="/needs-input">
                  Open &apos;Needs your input&apos; queue
                  <ArrowUpRight size={13} />
                </Link>
              </div>
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
