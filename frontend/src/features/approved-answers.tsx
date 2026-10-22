"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, patch, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Notice,
  Select,
} from "@/components/ui";

type Bank = {
  enabled: boolean;
  owner_approval_available: boolean;
  approvals: Record<string, { approved: boolean; scope: string }>;
};
function SavedAnswer({
  draft,
  profileVersion,
  bank,
}: {
  draft: Schema<"DraftRead">;
  profileVersion: number;
  bank: Bank;
}) {
  const client = useQueryClient();
  const [scope, setScope] = useState(
    draft.job_id ? "same_job" : "general_profile",
  );
  const [confirmed, setConfirmed] = useState(false);
  const approved = bank.approvals[draft.id]?.approved;
  const action = useMutation({
    mutationFn: async (operation: "review" | "approve" | "revoke") => {
      if (operation === "review")
        return patch(`application-answers/drafts/${draft.id}`, {
          review_status: "reviewed",
        });
      return post(
        `application-answers/drafts/${draft.id}/${operation}-reuse`,
        operation === "approve"
          ? {
              expected_profile_version: profileVersion,
              scope,
              confirm_reviewed_answer: confirmed,
            }
          : {},
      );
    },
    onSuccess: () => {
      setConfirmed(false);
      void client.invalidateQueries({ queryKey: ["saved-answer-drafts"] });
      void client.invalidateQueries({ queryKey: ["answer-reuse-bank"] });
    },
  });
  const motivation = ["motivation", "startup_interest"].includes(
    draft.question_category,
  );
  return (
    <article className="panel">
      <strong>{draft.question}</strong>{" "}
      <Badge tone={draft.stale ? "amber" : "neutral"}>
        {draft.stale ? "Stale profile" : readable(draft.review_status)}
      </Badge>
      <p className="preserve-lines">{draft.answer}</p>
      <small>
        {readable(draft.writing_style)} · profile v
        {draft.candidate_profile_version} · {draft.evidence_references.length}{" "}
        evidence references{draft.job_id ? " · saved job context" : ""}
      </small>
      {draft.evidence_references.map((ref, index) => (
        <p key={index}>
          <small>
            {readable(ref.source_type)}: {ref.source_id}
          </small>
        </p>
      ))}
      {approved ? (
        <>
          <Notice>
            Reuse approved for {readable(bank.approvals[draft.id]?.scope)}.
            Reuse still checks the current facts, evidence and question. Every
            new form requires review.
          </Notice>
          <Button
            busy={action.isPending}
            onClick={() => action.mutate("revoke")}
          >
            Revoke reuse approval
          </Button>
        </>
      ) : (
        <>
          {draft.review_status !== "reviewed" && (
            <Button
              disabled={draft.stale}
              busy={action.isPending}
              onClick={() => action.mutate("review")}
            >
              Mark answer reviewed
            </Button>
          )}
          {bank.enabled &&
            bank.owner_approval_available &&
            draft.review_status === "reviewed" &&
            !draft.stale && (
              <>
                <Field label="Reuse scope">
                  <Select
                    value={scope}
                    onChange={(event) => {
                      setScope(event.target.value);
                      setConfirmed(false);
                    }}
                  >
                    {draft.job_id && (
                      <option value="same_job">Only this saved job</option>
                    )}
                    {!motivation && (
                      <option value="general_profile">
                        General profile answer
                      </option>
                    )}
                  </Select>
                </Field>
                {motivation && !draft.job_id ? (
                  <Notice>
                    Company motivation requires an exact saved job before it can
                    be approved for reuse.
                  </Notice>
                ) : (
                  <>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(event) => setConfirmed(event.target.checked)}
                      />
                      I reviewed this answer, its evidence and reuse scope.
                    </label>
                    <Button
                      variant="primary"
                      disabled={!confirmed}
                      busy={action.isPending}
                      onClick={() => action.mutate("approve")}
                    >
                      Approve answer reuse
                    </Button>
                  </>
                )}
              </>
            )}
        </>
      )}
      {action.error && <ErrorState error={action.error} />}
    </article>
  );
}
export function ApprovedAnswers({
  profileVersion,
}: {
  profileVersion: number;
}) {
  const drafts = useQuery({
    queryKey: ["saved-answer-drafts"],
    queryFn: () =>
      api<Schema<"DraftRead">[]>("application-answers/drafts?limit=25"),
  });
  const bank = useQuery({
    queryKey: ["answer-reuse-bank"],
    queryFn: () => api<Bank>("application-answers/reuse-approvals"),
  });
  return (
    <details className="panel">
      <summary>Reviewed application answers</summary>
      <p>
        Review saved drafts and explicitly approve supported question
        paraphrases for reuse. Factual answers and consent never use this bank.
        Editing an application answer does not silently approve it here.
      </p>
      {(drafts.error || bank.error) && (
        <ErrorState error={drafts.error || bank.error} />
      )}
      {bank.data &&
        (!bank.data.enabled || !bank.data.owner_approval_available) && (
          <Notice>
            Reuse approval requires enabled answer reuse and the dashboard owner
            approval key. Saved drafts remain available for manual review.
          </Notice>
        )}
      {drafts.data?.length === 0 && (
        <p>
          No saved answer drafts yet. Generate a grounded application answer
          first.
        </p>
      )}
      {bank.data &&
        drafts.data?.map((draft) => (
          <SavedAnswer
            key={`${draft.id}:${draft.updated_at}`}
            draft={draft}
            profileVersion={profileVersion}
            bank={bank.data}
          />
        ))}
    </details>
  );
}
