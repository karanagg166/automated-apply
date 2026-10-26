"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { Button, ErrorState, Notice } from "@/components/ui";

type Preview = {
  packet_revision: number;
  preview_digest: string;
  destination: string;
  company: string | null;
  job_title: string;
  fields: {
    field_id: string;
    question: string;
    value: string;
    source: string;
    sha256?: string;
  }[];
  consents: {
    consent_id: string;
    question: string;
    checked: boolean;
    required: boolean;
  }[];
};
type Grant = { grant_id: string; grant_token: string; expires_at: string };
export type Execution = {
  state: string;
  adapter: string;
  recovery_required: boolean;
  receipt: { receipt_reference: string; fixture: string } | null;
  diagnostic: string | null;
};

export function BrowserSubmission({
  packetId,
  revision,
  enabled,
  execution,
  refresh,
  blocked,
}: {
  packetId: string;
  revision: number;
  enabled: boolean;
  execution: Execution | null;
  refresh: () => Promise<void>;
  blocked: boolean;
}) {
  const query = useQueryClient();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [consents, setConsents] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  const current = preview?.packet_revision === revision;
  async function run(action: "preview" | "authorize" | "submit" | "recover") {
    setBusy(true);
    setError(null);
    try {
      const route = `browser-applications/${packetId}`;
      if (action === "preview") {
        setGrant(null);
        setConsents([]);
        setConfirmed(false);
        setPreview(
          await post<Preview>(`${route}/submission-preview`, {
            expected_revision: revision,
            confirm_page_context: true,
          }),
        );
      } else if (action === "authorize") {
        setGrant(
          await post<Grant>(`${route}/authorize-submission`, {
            expected_revision: revision,
            preview_digest: preview!.preview_digest,
            confirm_exact_application: confirmed,
            reviewed_consent_ids: consents,
          }),
        );
      } else {
        if (action === "submit") {
          await post(`${route}/submit`, {
            expected_revision: revision,
            grant_id: grant!.grant_id,
            grant_token: grant!.grant_token,
            idempotency_key: key,
          });
        } else await post(`${route}/recover-submission`);
        setGrant(null);
        setPreview(null);
        setConfirmed(false);
        setConsents([]);
        await refresh();
        await query.invalidateQueries();
      }
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  if (!enabled)
    return (
      <Button
        disabled
        title="No real employer submission adapter is authorized"
      >
        Submit
      </Button>
    );
  return (
    <section aria-label="Mock submission review">
      <Notice>
        This is a fictional local employer demonstration. Real employer
        submission remains disabled.
      </Notice>
      {execution && (
        <>
          <p role="status">Mock submission: {execution.state}</p>
          {execution.receipt && (
            <p>Verified mock receipt: {execution.receipt.receipt_reference}</p>
          )}
          {execution.recovery_required && (
            <>
              <Notice>
                The outcome needs reconciliation. Do not submit again. Receipt
                recovery never clicks Submit.
              </Notice>
              <Button disabled={busy || blocked} onClick={() => run("recover")}>
                Check submission receipt
              </Button>
            </>
          )}
        </>
      )}
      {!execution && (
        <>
          <Button disabled={busy || blocked} onClick={() => run("preview")}>
            Review exact submission
          </Button>
          {preview && (
            <>
              <p>
                {preview.company} · {preview.job_title} · {preview.destination}
              </p>
              <ul>
                {preview.fields.map((f) => (
                  <li key={f.field_id}>
                    <strong>{f.question}:</strong> {f.value} · {f.source}
                    {f.sha256 && ` · SHA256 ${f.sha256}`}
                  </li>
                ))}
              </ul>
              {preview.consents
                .filter((c) => c.checked)
                .map((c) => (
                  <label key={c.consent_id}>
                    <input
                      type="checkbox"
                      checked={consents.includes(c.consent_id)}
                      onChange={(e) =>
                        setConsents(
                          e.target.checked
                            ? [...consents, c.consent_id]
                            : consents.filter((id) => id !== c.consent_id),
                        )
                      }
                    />{" "}
                    I reviewed this selected consent or answer: {c.question}
                  </label>
                ))}
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />{" "}
                I authorize this exact fictional application, including its
                destination, answers and resume.
              </label>
              <Button
                disabled={
                  busy ||
                  blocked ||
                  !current ||
                  !confirmed ||
                  consents.length !==
                    preview.consents.filter((c) => c.checked).length
                }
                onClick={() => run("authorize")}
              >
                Authorize mock submission
              </Button>
              {grant && (
                <p>
                  Authorization expires at{" "}
                  {new Date(grant.expires_at).toLocaleTimeString()}.
                </p>
              )}
            </>
          )}
          <Button
            disabled={busy || blocked || !current || !grant || !confirmed}
            onClick={() => run("submit")}
          >
            Submit
          </Button>
        </>
      )}
      {error && <ErrorState error={error} />}
    </section>
  );
}
