"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  Eye,
  FileQuestion,
  FileText,
  History,
  MessageSquare,
  RefreshCw,
  Save,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { api, dateLabel, patch, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  Modal,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";

export type MissingInputItem = {
  id: string;
  candidate_profile_id: string;
  question: string;
  question_category: string;
  job_id?: string | null;
  company_name?: string | null;
  packet_id?: string | null;
  missing_information: string[];
  reason: string;
  required_input_type:
    "text" | "number" | "choice" | "evidence" | "profile_edit";
  created_at: string;
  status: "needs_input" | "draft" | "approved" | "review_required";
  version: number;
  profile_version: number;
  context_digest: string;
  answer?: string | null;
  evidence_note?: string;
  draft_id?: string | null;
  stale?: boolean;
  href: string;
};

export type MissingHistoryEntry = {
  request_id: string;
  candidate_profile_id: string;
  operation: string;
  version: number;
  previous: Record<string, unknown>;
  recorded_at: string;
};

export function UnansweredQuestionsQueue() {
  const client = useQueryClient();
  const confirmationId = useId();

  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [selectedItem, setSelectedItem] = useState<MissingInputItem | null>(
    null,
  );
  const [modalOpen, setModalOpen] = useState(false);

  // Form states for answering
  const [answerText, setAnswerText] = useState("");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [factualConfirmation, setFactualConfirmation] = useState(false);
  const [actionSuccessMessage, setActionSuccessMessage] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<Schema<"CandidateProfileRead">>("profile"),
  });

  const missingQuestionsQuery = useQuery({
    queryKey: ["missing-questions"],
    queryFn: () =>
      api<{ requests: MissingInputItem[]; offset: number; limit: number }>(
        "application-answers/missing",
      ),
  });

  const historyQuery = useQuery({
    queryKey: ["missing-question-history", selectedItem?.id],
    queryFn: () =>
      api<{ history: MissingHistoryEntry[] }>(
        `application-answers/missing/${selectedItem!.id}/history`,
      ),
    enabled: !!selectedItem && showHistory,
  });

  const saveDraftMutation = useMutation({
    mutationFn: (item: MissingInputItem) =>
      patch<MissingInputItem>(`application-answers/missing/${item.id}`, {
        expected_version: item.version,
        answer: answerText.trim(),
        evidence_note: evidenceNote.trim(),
      }),
    onSuccess: (updated) => {
      setSelectedItem(updated);
      setActionSuccessMessage(
        "Draft answer saved. Review and confirm factual truthfulness to approve.",
      );
      client.invalidateQueries({ queryKey: ["missing-questions"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (item: MissingInputItem) => {
      if (!factualConfirmation) {
        throw new Error(
          "Explicit factual confirmation required before approving answer.",
        );
      }
      if (!profileQuery.data) {
        throw new Error("Candidate profile is required for version check.");
      }
      return post<MissingInputItem>(
        `application-answers/missing/${item.id}/approve`,
        {
          expected_version: item.version,
          expected_profile_version: profileQuery.data.version,
          factual_confirmation: true,
        },
      );
    },
    onSuccess: (updated) => {
      setSelectedItem(updated);
      setActionSuccessMessage(
        "Answer approved and added to reusable bank for this exact context.",
      );
      setFactualConfirmation(false);
      client.invalidateQueries({ queryKey: ["missing-questions"] });
      client.invalidateQueries({ queryKey: ["saved-answer-drafts"] });
    },
  });

  const isContractPending =
    missingQuestionsQuery.isError &&
    (missingQuestionsQuery.error as { status?: number }).status === 404;

  const rawQuestions = missingQuestionsQuery.data?.requests || [];
  const filteredQuestions = rawQuestions.filter((q) => {
    if (filterStatus === "all") return true;
    return q.status === filterStatus;
  });

  const handleOpenItem = (item: MissingInputItem) => {
    setSelectedItem(item);
    setAnswerText(item.answer || "");
    setEvidenceNote(item.evidence_note || "");
    setFactualConfirmation(false);
    setActionSuccessMessage("");
    setShowHistory(false);
    setModalOpen(true);
  };

  const countNeedsInput = rawQuestions.filter(
    (q) => q.status === "needs_input",
  ).length;
  const countDraft = rawQuestions.filter((q) => q.status === "draft").length;
  const countReviewRequired = rawQuestions.filter(
    (q) => q.status === "review_required" || q.stale,
  ).length;
  const countApproved = rawQuestions.filter(
    (q) => q.status === "approved" && !q.stale,
  ).length;

  return (
    <div className="stack spaced" aria-label="Codex Needs Your Answer Queue">
      <PageTitle
        eyebrow="HUMAN-IN-THE-LOOP QUALITY GATE"
        title="Codex needs your answer."
        description="When automated answer generation stops due to missing facts or unverified claims, supply truthful knowledge and review before approval."
        actions={
          <div className="actions">
            <Button
              onClick={() => missingQuestionsQuery.refetch()}
              busy={missingQuestionsQuery.isFetching}
            >
              <RefreshCw size={13} />
              Refresh queue
            </Button>
          </div>
        }
      />

      <Notice>
        <div className="split">
          <div>
            <strong>Zero Silent Hallucinations:</strong> The assistant never
            invents facts when evidence is missing. Entering text creates a
            draft. Approval requires explicit factual confirmation and creates a
            reusable context answer.
          </div>
          <Badge tone="green">
            <ShieldCheck size={12} />
            TRUTH PRESERVED
          </Badge>
        </div>
      </Notice>

      {/* Contract Pending Warning */}
      {isContractPending && (
        <div className="error-state" role="alert">
          <AlertCircle size={20} />
          <div>
            <strong>Codex Missing Inputs Contract Pending</strong>
            <p>
              The backend unanswered questions endpoint (
              <code>/api/v1/application-answers/missing</code>) is currently
              being developed by Codex in{" "}
              <code>feat/phase3-codex-integrations</code>. The frontend is built
              to exact specification and will connect seamlessly once the
              backend branch is merged.
            </p>
          </div>
        </div>
      )}

      {/* Summary Metrics */}
      <div className="metrics spaced">
        <div className="metric">
          <div className="metric-label">NEEDS INPUT</div>
          <strong>{countNeedsInput}</strong>
          <small>Missing factual evidence</small>
        </div>
        <div className="metric">
          <div className="metric-label">DRAFTS IN PROGRESS</div>
          <strong>{countDraft}</strong>
          <small>Awaiting factual review</small>
        </div>
        <div className="metric">
          <div className="metric-label">REVIEW REQUIRED</div>
          <strong>{countReviewRequired}</strong>
          <small>Profile facts updated</small>
        </div>
        <div className="metric">
          <div className="metric-label">APPROVED REUSABLE</div>
          <strong>{countApproved}</strong>
          <small>Exact-context verified</small>
        </div>
      </div>

      {/* Filter Tabs */}
      <div
        className="status-tabs"
        role="tablist"
        aria-label="Filter unanswered questions"
      >
        {[
          ["all", `All questions (${rawQuestions.length})`],
          ["needs_input", `Needs input (${countNeedsInput})`],
          ["draft", `Drafts (${countDraft})`],
          ["review_required", `Review required (${countReviewRequired})`],
          ["approved", `Approved (${countApproved})`],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={filterStatus === key}
            className={filterStatus === key ? "selected" : ""}
            onClick={() => setFilterStatus(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {missingQuestionsQuery.isPending && !isContractPending && <Skeleton />}

      {!missingQuestionsQuery.isPending &&
        filteredQuestions.length === 0 &&
        !isContractPending && (
          <Empty
            title="All questions resolved"
            description={
              filterStatus !== "all"
                ? `No questions currently in "${readable(filterStatus)}" state.`
                : "No application questions are blocked on candidate input. Automated applications are proceeding with approved facts."
            }
          />
        )}

      {/* Questions List */}
      {filteredQuestions.length > 0 && (
        <div
          className="stack spaced"
          role="list"
          aria-label="Unanswered questions list"
        >
          {filteredQuestions.map((item) => {
            const isStale = item.stale || item.status === "review_required";
            return (
              <article
                className="panel panel-body"
                key={item.id}
                role="listitem"
              >
                <div className="split">
                  <div>
                    <h3 style={{ fontSize: "1.1rem" }}>{item.question}</h3>
                    <p
                      className="muted"
                      style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}
                    >
                      {item.company_name && (
                        <strong>{item.company_name} · </strong>
                      )}
                      Category: {readable(item.question_category)} · Created{" "}
                      {dateLabel(item.created_at)}
                    </p>
                  </div>
                  <Badge
                    tone={
                      isStale
                        ? "red"
                        : item.status === "approved"
                          ? "green"
                          : item.status === "draft"
                            ? "neutral"
                            : "amber"
                    }
                  >
                    {isStale
                      ? "Review Required (Stale Profile)"
                      : readable(item.status)}
                  </Badge>
                </div>

                {isStale && (
                  <Notice>
                    <strong>Stale Answer Warning:</strong> Your candidate
                    profile facts have changed since this answer was approved.
                    Review the new facts and re-confirm before citing this
                    answer.
                  </Notice>
                )}

                <div
                  className="detail-section"
                  style={{ marginTop: "0.75rem" }}
                >
                  <p>
                    <strong>Reason stopped:</strong> {item.reason}
                  </p>
                  {item.missing_information.length > 0 && (
                    <div style={{ marginTop: "0.5rem" }}>
                      <strong>Missing factual detail:</strong>
                      <ul>
                        {item.missing_information.map((info, idx) => (
                          <li key={idx}>{info}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {item.answer && (
                  <div
                    className="preserve-lines panel panel-body"
                    style={{
                      marginTop: "0.5rem",
                      background: "var(--surface)",
                    }}
                  >
                    <strong>Current Answer ({readable(item.status)}):</strong>
                    <p style={{ marginTop: "0.25rem" }}>{item.answer}</p>
                    {item.evidence_note && (
                      <small
                        className="muted"
                        style={{ display: "block", marginTop: "0.25rem" }}
                      >
                        Evidence Note: {item.evidence_note}
                      </small>
                    )}
                  </div>
                )}

                <div className="actions" style={{ marginTop: "1rem" }}>
                  <Button
                    variant="primary"
                    onClick={() => handleOpenItem(item)}
                  >
                    <MessageSquare size={13} />
                    {item.status === "approved"
                      ? "Review or edit answer"
                      : "Supply truthful answer"}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* Answer & Resolution Modal */}
      <Modal
        open={modalOpen}
        onOpenChange={setModalOpen}
        title={
          selectedItem
            ? `Answer Question: ${selectedItem.question}`
            : "Answer question"
        }
        description="Supply truthful knowledge and evidence. Text entry creates a draft; approval requires explicit factual confirmation."
      >
        {selectedItem && (
          <div className="stack">
            {actionSuccessMessage && (
              <Notice>
                <div className="split">
                  <span>{actionSuccessMessage}</span>
                  <CheckCircle2 size={16} style={{ color: "var(--green)" }} />
                </div>
              </Notice>
            )}

            {(selectedItem.stale ||
              selectedItem.status === "review_required") && (
              <div className="error-state" role="alert">
                <AlertTriangle size={18} />
                <div>
                  <strong>Dependent Facts Changed</strong>
                  <p>
                    Candidate profile facts were updated. Please review the
                    answer and supporting evidence below to ensure full
                    alignment with your latest background.
                  </p>
                </div>
              </div>
            )}

            <div
              className="panel panel-body"
              style={{ background: "var(--surface)" }}
            >
              <dl>
                <dt>Original Question</dt>
                <dd>
                  <strong>{selectedItem.question}</strong>
                </dd>

                {selectedItem.company_name && (
                  <>
                    <dt>Associated Company</dt>
                    <dd>{selectedItem.company_name}</dd>
                  </>
                )}

                <dt>Why answer stopped</dt>
                <dd>{selectedItem.reason}</dd>

                <dt>Missing facts</dt>
                <dd>
                  {selectedItem.missing_information.join(", ") ||
                    "Specific candidate context"}
                </dd>

                <dt>Required input type</dt>
                <dd>
                  <Badge>{readable(selectedItem.required_input_type)}</Badge>
                </dd>
              </dl>
            </div>

            <Field
              label="Your Truthful Answer"
              hint="Provide truthful, accurate information based on your real experience"
            >
              <textarea
                className="input preserve-lines"
                rows={5}
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                placeholder="Write your comprehensive, truthful answer here…"
                required
              />
            </Field>

            <Field
              label="Supporting Evidence / Project Context"
              hint="Reference specific projects, metrics, or factual sources"
            >
              <Input
                value={evidenceNote}
                onChange={(e) => setEvidenceNote(e.target.value)}
                placeholder="e.g. Backed by Project 'Distributed Cache' and 2024 work at Acme Corp"
                required
              />
            </Field>

            <div className="actions">
              <Button
                onClick={() => saveDraftMutation.mutate(selectedItem)}
                busy={saveDraftMutation.isPending}
                disabled={!answerText.trim() || saveDraftMutation.isPending}
              >
                <Save size={13} />
                Save as draft
              </Button>

              <Button
                variant="ghost"
                onClick={() => setShowHistory(!showHistory)}
              >
                <History size={13} />
                {showHistory
                  ? "Hide revision history"
                  : "View revision history"}
              </Button>
            </div>

            {saveDraftMutation.isError && (
              <ErrorState error={saveDraftMutation.error} />
            )}

            {/* Revision History */}
            {showHistory && (
              <div
                className="panel panel-body spaced"
                aria-label="Revision history"
              >
                <h4>Revision History</h4>
                {historyQuery.isPending && <Skeleton />}
                {historyQuery.data?.history &&
                historyQuery.data.history.length > 0 ? (
                  <ul>
                    {historyQuery.data.history.map((rev, idx) => (
                      <li key={idx}>
                        <strong>
                          v{rev.version} ({readable(rev.operation)}):
                        </strong>{" "}
                        Recorded at {dateLabel(rev.recorded_at)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">
                    No prior revisions recorded for this question.
                  </p>
                )}
              </div>
            )}

            {/* Factual Approval Step */}
            <div
              className="panel panel-body stack"
              style={{ border: "1px solid var(--green)", marginTop: "1rem" }}
            >
              <h4>Review and Approve Answer</h4>
              <p className="section-intro">
                Approving this answer authorizes its reuse for this exact job
                context. Text alone does not approve.
              </p>

              <label
                className="check-label"
                htmlFor={`confirm-fact-${confirmationId}`}
              >
                <input
                  id={`confirm-fact-${confirmationId}`}
                  type="checkbox"
                  checked={factualConfirmation}
                  onChange={(e) => setFactualConfirmation(e.target.checked)}
                />
                I confirm this answer is completely truthful, accurate, and
                supported by personal knowledge and evidence.
              </label>

              {approveMutation.isError && (
                <ErrorState error={approveMutation.error} />
              )}

              <div className="actions">
                <Button
                  variant="primary"
                  disabled={
                    !factualConfirmation ||
                    !answerText.trim() ||
                    !evidenceNote.trim() ||
                    approveMutation.isPending
                  }
                  busy={approveMutation.isPending}
                  onClick={() => approveMutation.mutate(selectedItem)}
                >
                  <Check size={14} />
                  Approve answer for this context
                </Button>
              </div>
            </div>

            <div className="actions" style={{ justifyContent: "flex-end" }}>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
