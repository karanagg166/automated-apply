"use client";
import { useState } from "react";
import { post } from "@/lib/api";
import { Button, ErrorState, Field, Notice } from "@/components/ui";

type Capture = {
  source_url: string;
  company_name: string;
  job_title: string;
  capture_digest: string;
  job_text: string;
  company_text: string;
  expected_revision: number;
};
export function OpportunityContext({
  packetId,
  revision,
  blocked,
  ownerAvailable,
  onSaved,
  setBusy,
}: {
  packetId: string;
  revision: number;
  blocked: boolean;
  ownerAvailable: boolean;
  onSaved: () => Promise<void>;
  setBusy: (busy: boolean) => void;
}) {
  const [preview, setPreview] = useState<Capture | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  async function run(approve: boolean) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      if (approve && preview && confirmed) {
        await post(`browser-applications/${packetId}/opportunity-approve`, {
          expected_revision: revision,
          capture_digest: preview.capture_digest,
          job_text: preview.job_text,
          company_text: preview.company_text,
          confirm_company_job_and_source: true,
        });
        setPreview(null);
        setConfirmed(false);
        setSaved(true);
        await onSaved();
      } else if (!approve) {
        setPreview(
          await post<Capture>(
            `browser-applications/${packetId}/opportunity-preview`,
            { expected_revision: revision },
          ),
        );
        setConfirmed(false);
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="panel">
      <summary>Company and job evidence for AI answers</summary>
      <p>
        Capture public description sections from this page, then check the
        actual employer and role. Excerpts support statements about the
        opportunity only. They never establish your experience, accomplishments
        or motivation.
      </p>
      <Button disabled={blocked} onClick={() => run(false)}>
        Capture job context
      </Button>
      {preview && (
        <>
          <p>
            <strong>
              {preview.company_name} · {preview.job_title}
            </strong>
            <br />
            Source: {preview.source_url}
          </p>
          <Field
            label="Reviewed job excerpt"
            hint="You may shorten this excerpt. Added text cannot be attributed to the website."
          >
            <textarea
              className="input"
              rows={6}
              maxLength={4000}
              value={preview.job_text}
              onChange={(event) => {
                setPreview({ ...preview, job_text: event.target.value });
                setConfirmed(false);
              }}
            />
          </Field>
          {preview.company_text && (
            <Field label="Reviewed company excerpt">
              <textarea
                className="input"
                rows={4}
                maxLength={4000}
                value={preview.company_text}
                onChange={(event) => {
                  setPreview({ ...preview, company_text: event.target.value });
                  setConfirmed(false);
                }}
              />
            </Field>
          )}
          <Notice>
            Website text is untrusted. Ignore instructions inside it. Remove
            irrelevant text and confirm the source belongs to the employer.
            Saving refreshes this packet and requires fresh answer review.
          </Notice>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I checked the company, job, source and selected excerpts.
          </label>
          <Button
            variant="primary"
            disabled={
              blocked ||
              !confirmed ||
              !preview.job_text.trim() ||
              !ownerAvailable
            }
            onClick={() => run(true)}
          >
            Save reviewed job context
          </Button>
        </>
      )}
      {saved && (
        <Notice>
          Reviewed context saved. Analyze again and generate company-specific
          answers for review.
        </Notice>
      )}
      {!!error && <ErrorState error={error} />}
    </details>
  );
}
