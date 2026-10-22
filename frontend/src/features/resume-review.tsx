"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ErrorState, Field, Notice, Skeleton } from "@/components/ui";
import { api, post, readable, type Schema } from "@/lib/api";
import { ResumeFactsEditor } from "./resume-facts-editor";

export function ResumeReview({
  versionId,
  onClose,
}: {
  versionId: string;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["resume-review", versionId],
    queryFn: () =>
      api<Schema<"ResumeReviewRead">>(
        `dashboard/resume-sync/versions/${versionId}/review`,
      ),
    staleTime: 0,
  });
  if (query.isPending) return <Skeleton />;
  if (query.isError) return <ErrorState error={query.error} />;
  return (
    <ReviewForm
      key={`${versionId}:${query.data.expected_profile_version}:${query.data.expected_generation}`}
      review={query.data}
      onClose={onClose}
      reload={() => query.refetch()}
    />
  );
}

function ReviewForm({
  review,
  onClose,
  reload,
}: {
  review: Schema<"ResumeReviewRead">;
  onClose: () => void;
  reload: () => void;
}) {
  const client = useQueryClient();
  const [profile, setProfile] = useState<
    Schema<"CandidateProfileCreate-Input">
  >(
    review.proposed_profile || {
      full_name: review.suggested_identity.full_name,
      email: review.suggested_identity.email,
      verified_skills: review.suggested_identity.verified_skills,
    },
  );
  const [confirmed, setConfirmed] = useState(false),
    [removals, setRemovals] = useState(false);
  const [achievements, setAchievements] = useState(""),
    [claims, setClaims] = useState("");
  const approve = useMutation({
    retry: false,
    mutationFn: () =>
      post(`dashboard/resume-sync/versions/${review.version.id}/approve`, {
        owner_confirmed: true,
        primary: true,
        expected_generation: review.expected_generation,
        expected_profile_version: review.expected_profile_version,
        profile,
        allow_skill_removals: removals,
        evidence: [
          ...(achievements.trim()
            ? [
                {
                  evidence_type: "achievement",
                  title: "Reviewed resume achievements",
                  content: achievements.trim(),
                  user_confirmed: true,
                },
              ]
            : []),
          ...(claims.trim()
            ? [
                {
                  evidence_type: "resume_note",
                  title: "Reviewed resume claims",
                  content: claims.trim(),
                  user_confirmed: true,
                },
              ]
            : []),
        ],
      }),
    onSuccess: () => {
      client.invalidateQueries();
      onClose();
    },
  });
  const edit = () => setConfirmed(false);
  return (
    <section className="panel">
      <div className="panel-body stack">
        <h2>Review Changes</h2>
        {review.warnings.map((warning) => (
          <p key={warning}>{warning}</p>
        ))}
        <a
          className="button"
          href={`/api/backend/dashboard/resumes/${review.version.private_resume_id}`}
        >
          Download new PDF privately
        </a>
        <Notice>
          {review.stale_packet_count} existing packets and{" "}
          {review.stale_answer_count} saved answers will need a freshness check
          after approval. Their saved contents and history are preserved.
        </Notice>
        {review.differences.map((change) => (
          <details key={change.category} className="evidence-item">
            <summary>
              {readable(change.category)} · {change.added.length} added ·{" "}
              {change.removed.length} omitted or removed
            </summary>
            <div className="form-grid">
              <div>
                <h3>Current verified facts</h3>
                <pre className="source-text">
                  {change.current_verified?.join("\n") ||
                    "No confirmed facts in this category"}
                </pre>
              </div>
              <div>
                <h3>Previous resume evidence</h3>
                <pre className="source-text">
                  {change.before.join("\n") || "No previous evidence"}
                </pre>
              </div>
              <div>
                <h3>New resume evidence</h3>
                <pre className="source-text">
                  {change.after.join("\n") ||
                    "No extracted evidence; manual review needed"}
                </pre>
              </div>
            </div>
          </details>
        ))}
        <details>
          <summary>Review full extracted source text</summary>
          <pre className="source-text">
            {review.text ||
              "No extractable text. Review the downloaded PDF manually."}
          </pre>
        </details>
        {review.current_profile && (
          <details>
            <summary>Current verified facts</summary>
            <p>
              {review.current_profile.full_name} ·{" "}
              {review.current_profile.verified_skills?.join(", ")}
            </p>
            <p>
              Existing experience, education, projects, links and preferences
              are retained in the form below.
            </p>
          </details>
        )}
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (confirmed) approve.mutate();
          }}
        >
          <ResumeFactsEditor
            value={profile}
            onChange={(value) => {
              setProfile(value);
              edit();
            }}
          />
          <Field
            label="Additional reviewed achievements"
            hint="Optional. Only enter claims you explicitly confirm; existing evidence is preserved."
          >
            <textarea
              className="input"
              maxLength={4000}
              value={achievements}
              onChange={(e) => {
                setAchievements(e.target.value);
                edit();
              }}
            />
          </Field>
          <Field
            label="Other reviewed resume-backed claims"
            hint="Optional. Unentered source text remains unverified."
          >
            <textarea
              className="input"
              maxLength={4000}
              value={claims}
              onChange={(e) => {
                setClaims(e.target.value);
                edit();
              }}
            />
          </Field>
          <label className="check-label">
            <input
              type="checkbox"
              checked={removals}
              onChange={(e) => {
                setRemovals(e.target.checked);
                edit();
              }}
            />
            <span>
              I explicitly approve any human-confirmed skills I removed from the
              form.
            </span>
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              I reviewed the PDF, differences and every fact above. Save these
              facts and make this the active resume.
            </span>
          </label>
          {approve.isError && <ErrorState error={approve.error} />}
          <div className="actions">
            <Button
              variant="primary"
              type="submit"
              busy={approve.isPending}
              disabled={!confirmed}
            >
              Approve New Resume Version
            </Button>
            <Button type="button" onClick={reload}>
              Reload review
            </Button>
            <Button type="button" onClick={onClose}>
              Close review
            </Button>
          </div>
        </form>
      </div>
    </section>
  );
}
