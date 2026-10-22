"use client";

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { api, post, Schema } from "@/lib/api";
import { Button, Field, Input, Notice, ErrorState } from "@/components/ui";

type BrowserStatus = {
  packet: Schema<"PacketRead">;
  connected: boolean;
  manual: boolean;
  recovery: string | null;
  analysis: {
    diagnostic: string;
    page_context: { url: string; title: string; heading: string };
    warnings: string[];
    fields: {
      field_id: string;
      question: string;
      supported: boolean;
      manual_reason: string | null;
    }[];
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
  const [busy, setBusy] = useState(false);
  const [permission, setPermission] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [contextConfirmed, setContextConfirmed] = useState(false);
  async function run(action: string) {
    setBusy(true);
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
      setState(result);
      setReviewed(false);
      setContextConfirmed(false);
      await client.invalidateQueries();
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
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
          disabled={busy || !state?.connected}
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
        <Button disabled={busy} onClick={() => run("cancel")}>
          Cancel
        </Button>
        <Button disabled title="No employer submission adapter is authorized">
          Submit
        </Button>
      </div>
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
          !reviewed ||
          !contextConfirmed
        }
        onClick={() => run("fill")}
      >
        Fill supported fields
      </Button>
      {error && <ErrorState error={error} />}
      {state?.recovery && <Notice>{state.recovery}</Notice>}
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
            Edit and review detected answers in Application fields below. For
            another step, use Take Over to navigate, then Analyze again. After
            manual submission, record the receipt using the existing submission
            report.
          </p>
        </>
      )}
    </section>
  );
}
