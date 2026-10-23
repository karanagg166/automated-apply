"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { api, post, Schema } from "@/lib/api";
import { Button, Field, Input, Notice, ErrorState } from "@/components/ui";

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
  recovery: string | null;
  automated_submission_enabled: boolean;
  owner_consent_available: boolean;
  opportunity_context_available: boolean;
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

export function BrowserAssistant({ packet }: { packet: Schema<"PacketRead"> }) {
  const client = useQueryClient();
  const [state, setState] = useState<BrowserStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [working, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const epoch = useRef(0);
  const renderEpoch = epoch.current;
  const busy = working || cancelling;
  const [permission, setPermission] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [contextConfirmed, setContextConfirmed] = useState(false);
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
      <Notice>
        Assisted filling uses a dedicated Chrome profile. Submission is manual.
        Required consent, custom controls, embedded forms and additional steps
        need your review on the website.
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
      <div className="actions">
        <Button disabled={busy || !permission} onClick={() => run("open")}>
          Open dedicated browser
        </Button>
        <Button disabled={busy} onClick={() => run("status")}>
          Get status
        </Button>
        <Button
          disabled={busy || !state?.connected || state.page_review_required}
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
          disabled={busy || !state?.connected}
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
          onChange={(e) => setReviewed(e.target.checked)}
        />{" "}
        I reviewed the current answers, destination and selected resume below.
      </label>
      <label>
        <input
          type="checkbox"
          checked={contextConfirmed}
          onChange={(e) => setContextConfirmed(e.target.checked)}
        />{" "}
        I confirmed the actual page belongs to this company and job.
      </label>
      <Button
        disabled={
          busy ||
          !state?.connected ||
          !state.analysis ||
          state.manual ||
          state.page_review_required ||
          !reviewed ||
          !contextConfirmed
        }
        onClick={() => run("fill")}
      >
        Fill supported fields
      </Button>
      {state?.connected && (
        <BrowserPage
          key={`${packet.revision}:${epoch.current}`}
          packetId={packet.id}
          revision={packet.revision}
          blocked={busy}
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
      {state?.page_review_required && (
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
        blocked={busy}
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
        blocked={busy || !state?.connected || !!state?.manual}
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
          packetId={packet.id}
          revision={packet.revision}
          blocked={busy || !state.connected || state.manual}
          ownerAvailable={state.owner_consent_available}
          setBusy={setBusy}
          onSaved={async () => {
            setReviewed(false);
            setContextConfirmed(false);
            await client.invalidateQueries();
            setState(
              await api<BrowserStatus>(`browser-applications/${packet.id}`),
            );
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
                        busy ||
                        !contextConfirmed ||
                        state.manual ||
                        [
                          "submitting",
                          "submission_unknown",
                          "provider_confirmed_submitted",
                        ].includes(packet.lifecycle_state)
                      }
                      onClick={() => consent(f.field_id, true)}
                    >
                      Select on website: {f.question}
                    </Button>
                    <Button
                      disabled={
                        busy ||
                        !contextConfirmed ||
                        state.manual ||
                        [
                          "submitting",
                          "submission_unknown",
                          "provider_confirmed_submitted",
                        ].includes(packet.lifecycle_state)
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
