"use client";
import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { Button, ErrorState, Notice } from "@/components/ui";

type PagePreview = {
  capture_digest: string;
  expected_revision: number;
  display_url: string;
  heading: string;
  title: string;
  warning: string;
  questions: { question: string; required: boolean; supported: boolean }[];
};

export function BrowserPage({
  packetId,
  revision,
  blocked,
  ownerAvailable,
  setBusy,
  refresh,
}: {
  packetId: string;
  revision: number;
  blocked: boolean;
  ownerAvailable: boolean;
  setBusy: (value: boolean) => void;
  refresh: () => Promise<void>;
}) {
  const [view, setView] = useState<PagePreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  async function run(resume: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (resume && view && confirmed) {
        await post(`browser-applications/${packetId}/resume-page`, {
          expected_revision: view.expected_revision,
          capture_digest: view.capture_digest,
          confirm_same_application: true,
        });
        setView(null);
        setConfirmed(false);
      } else if (!resume) {
        setView(
          await post<PagePreview>(
            `browser-applications/${packetId}/page-preview`,
            {
              expected_revision: revision,
            },
          ),
        );
        setConfirmed(false);
      }
    } catch (failure) {
      setError(failure);
    } finally {
      if (live.current) {
        try {
          await refresh();
        } catch (failure) {
          setError(failure);
        }
      }
      setBusy(false);
    }
  }
  return (
    <details className="panel">
      <summary>Resume after manual navigation</summary>
      <p>
        Use Take Over to navigate or save a step yourself. Then preview the page
        you reached and confirm it belongs to this application. Assistance
        resumes with a fresh analysis and answer review.
      </p>
      <Button disabled={blocked} onClick={() => run(false)}>
        Preview current page
      </Button>
      {view && (
        <>
          <Notice>{view.warning}</Notice>
          <p>
            {view.heading || view.title} · {view.display_url}
          </p>
          <ul>
            {view.questions.map((question, index) => (
              <li key={index}>
                {question.question}
                {question.required ? " · required" : ""}
                {!question.supported ? " · manual" : ""}
              </li>
            ))}
          </ul>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I checked this page is part of the same company, role and
            application. I want to resume assistance here.
          </label>
          <Button
            variant="primary"
            disabled={
              blocked ||
              !confirmed ||
              !ownerAvailable ||
              view.expected_revision !== revision
            }
            onClick={() => run(true)}
          >
            Authorize page and analyze
          </Button>
        </>
      )}
      {!!error && <ErrorState error={error} />}
    </details>
  );
}
