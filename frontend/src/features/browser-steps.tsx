"use client";
import { useState } from "react";
import { post } from "@/lib/api";
import { Button, ErrorState, Notice } from "@/components/ui";

type Preview = {
  label: string;
  preview_digest: string;
  expected_revision: number;
  complete: boolean;
  warning: string;
  values: {
    question: string;
    kind: string;
    value: string;
    complete: boolean;
    required: boolean;
    consent: boolean;
  }[];
};
export function BrowserSteps({
  packetId,
  revision,
  enabled,
  ownerAvailable,
  blocked,
  setBusy,
  refresh,
}: {
  packetId: string;
  revision: number;
  enabled: boolean;
  ownerAvailable: boolean;
  blocked: boolean;
  setBusy: (value: boolean) => void;
  refresh: () => Promise<void>;
}) {
  const [view, setView] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  async function run(advance: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (advance && view && confirmed) {
        await post(`browser-applications/${packetId}/advance-step`, {
          expected_revision: view.expected_revision,
          preview_digest: view.preview_digest,
          idempotency_key: requestKey,
          confirm_values_and_consents: true,
        });
        setView(null);
        setConfirmed(false);
        await refresh();
      } else if (!advance) {
        setView(
          await post<Preview>(`browser-applications/${packetId}/step-preview`, {
            expected_revision: revision,
          }),
        );
        setRequestKey(crypto.randomUUID());
        setConfirmed(false);
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  if (!enabled && !view) return null;
  return (
    <details className="panel">
      <summary>Review next application step</summary>
      <p>
        Only a single in-page Next or Continue button is supported. Navigation,
        draft-saving requests and submission remain blocked. Inspect the actual
        form before authorizing a step.
      </p>
      <Button disabled={blocked || !enabled} onClick={() => run(false)}>
        Preview next step
      </Button>
      {view && (
        <>
          <Notice>{view.warning}</Notice>
          <table>
            <thead>
              <tr>
                <th>Question</th>
                <th>Actual browser value</th>
                <th>Validation</th>
              </tr>
            </thead>
            <tbody>
              {view.values.map((value, index) => (
                <tr key={index}>
                  <td>
                    {value.question}
                    {value.consent ? " · owner consent" : ""}
                  </td>
                  <td>{value.value || "Unanswered"}</td>
                  <td>{value.complete ? "Complete" : "Needs attention"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I reviewed the actual values and every selected consent before
            advancing this step.
          </label>
          <Button
            variant="primary"
            disabled={
              blocked ||
              !confirmed ||
              !view.complete ||
              !ownerAvailable ||
              view.expected_revision !== revision
            }
            onClick={() => run(true)}
          >
            Authorize {view.label}
          </Button>
          {!view.complete && (
            <Notice>
              Complete required fields and resolve validation on the current
              step first.
            </Notice>
          )}
        </>
      )}
      {!!error && <ErrorState error={error} />}
    </details>
  );
}
