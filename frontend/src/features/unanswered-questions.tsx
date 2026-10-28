"use client";

import { useEffect, useId, useRef, useState } from "react";
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

export type MissingInputItem = Schema<"MissingInputRead">;
export type MissingHistoryEntry = Schema<"MissingInputRevision">;

export function UnansweredQuestionsQueue({
  initialRequestId,
}: { initialRequestId?: string } = {}) {
  const client = useQueryClient();
  const confirmationId = useId();
  const openedInitial = useRef(false);

  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCompany, setSelectedCompany] = useState("all");
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

  const initialRequest = useQuery({
    queryKey: ["missing-question", initialRequestId],
    queryFn: () =>
      api<MissingInputItem>(`application-answers/missing/${initialRequestId}`),
    enabled: !!initialRequestId,
  });
  useEffect(() => {
    if (openedInitial.current || !initialRequestId) return;
    if (initialRequest.data) {
      openedInitial.current = true;
      setSelectedItem(initialRequest.data);
      setAnswerText(initialRequest.data.answer || "");
      setEvidenceNote(initialRequest.data.evidence_note || "");
      setModalOpen(true);
    } else if (missingQuestionsQuery.data?.requests) {
      const match = missingQuestionsQuery.data.requests.find(
        (r) =>
          r.id === initialRequestId ||
          (r as unknown as { field_id?: string }).field_id === initialRequestId,
      );
      if (match) {
        openedInitial.current = true;
        setSelectedItem(match);
        setAnswerText(match.answer || "");
        setEvidenceNote(match.evidence_note || "");
        setModalOpen(true);
      }
    }
  }, [initialRequest.data, missingQuestionsQuery.data, initialRequestId]);
  const hasUnsavedChanges =
    !selectedItem ||
    answerText.trim() !== (selectedItem.answer || "").trim() ||
    evidenceNote.trim() !== (selectedItem.evidence_note || "").trim();

  // Protect against accidental navigation with unsaved changes
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (modalOpen && hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [modalOpen, hasUnsavedChanges]);

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
      setFactualConfirmation(false);
      setActionSuccessMessage(
        "Draft answer saved. Review and confirm factual truthfulness to approve.",
      );
      client.invalidateQueries({ queryKey: ["missing-questions"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (item: MissingInputItem) => {
      if (
        hasUnsavedChanges ||
        item.status !== "draft" ||
        item.stale ||
        saveDraftMutation.isPending
      ) {
        throw new Error("Save and review the current draft before approval.");
      }
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
        "Saved answer approved for this exact question and context. Broader reuse requires separate approval.",
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

  // Group duplicate questions across applications
  const questionOccurrences = rawQuestions.reduce<
    Record<string, { count: number; companies: string[] }>
  >((acc, q) => {
    const key = q.question.trim().toLowerCase();
    if (!acc[key]) acc[key] = { count: 0, companies: [] };
    acc[key].count += 1;
    if (q.company_name && !acc[key].companies.includes(q.company_name)) {
      acc[key].companies.push(q.company_name);
    }
    return acc;
  }, {});

  // Unique companies for filter dropdown
  const companies = Array.from(
    new Set(rawQuestions.map((q) => q.company_name).filter(Boolean)),
  ) as string[];

  const effectiveStatus = (item: MissingInputItem) =>
    item.effective_status ||
    (item.stale && item.status === "approved"
      ? "review_required"
      : item.status);

  const filteredQuestions = rawQuestions.filter((item) => {
    const matchesStatus =
      filterStatus === "all" || effectiveStatus(item) === filterStatus;
    const matchesCompany =
      selectedCompany === "all" ||
      !selectedCompany.trim() ||
      (item.company_name &&
        item.company_name
          .toLowerCase()
          .includes(selectedCompany.trim().toLowerCase()));
    const matchesSearch =
      !searchQuery.trim() ||
      item.question.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (item.company_name &&
        item.company_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (item.reason &&
        item.reason.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesStatus && matchesCompany && matchesSearch;
  });

  const handleOpenItem = (item: MissingInputItem) => {
    setSelectedItem(item);
    setAnswerText(item.answer || "");
    setEvidenceNote(item.evidence_note || "");
    setFactualConfirmation(false);
    setActionSuccessMessage("");
    setShowHistory(false);
    setModalOpen(true);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("missing_input", item.id);
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  };

  const handleCloseModal = () => {
    if (hasUnsavedChanges && typeof window !== "undefined") {
      const confirmClose = window.confirm(
        "You have unsaved draft changes. Closing will discard unsaved text. Are you sure you want to close?",
      );
      if (!confirmClose) return;
    }
    setModalOpen(false);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (url.searchParams.has("missing_input") || url.searchParams.has("id")) {
        url.searchParams.delete("missing_input");
        url.searchParams.delete("id");
        window.history.replaceState({}, "", url.pathname + url.search);
      }
    }
  };

  // Clean up URL search params on unmount
  useEffect(() => {
    return () => {
      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        if (
          url.searchParams.has("missing_input") ||
          url.searchParams.has("id")
        ) {
          url.searchParams.delete("missing_input");
          url.searchParams.delete("id");
          window.history.replaceState({}, "", url.pathname + url.search);
        }
      }
    };
  }, []);

  const countNeedsInput = rawQuestions.filter(
    (q) => effectiveStatus(q) === "needs_input",
  ).length;
  const countDraft = rawQuestions.filter(
    (q) => effectiveStatus(q) === "draft",
  ).length;
  const countReviewRequired = rawQuestions.filter(
    (q) => effectiveStatus(q) === "review_required",
  ).length;
  const countApproved = rawQuestions.filter(
    (q) => effectiveStatus(q) === "approved",
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
            draft. Approval requires explicit factual confirmation and creates
            an answer for this exact question and context.
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
            <strong>Question queue unavailable</strong>
            <p>
              The saved question queue is unavailable. Check the backend
              connection and try again. No answer has been invented.
            </p>
          </div>
        </div>
      )}

      {missingQuestionsQuery.isError && !isContractPending && (
        <ErrorState error={missingQuestionsQuery.error} />
      )}
      {initialRequest.isError && <ErrorState error={initialRequest.error} />}
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

      {/* Search and Company Filters */}
      <div className="form-grid spaced">
        <Field label="SEARCH QUESTIONS">
          <Input
            placeholder="Search question text, company, or stopped reason…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search questions"
          />
        </Field>
        <Field label="COMPANY FILTER">
          <Input
            list="company-filter-list"
            placeholder="All companies (type to filter)"
            value={selectedCompany === "all" ? "" : selectedCompany}
            onChange={(e) => setSelectedCompany(e.target.value.trim() || "all")}
            aria-label="Filter by company"
          />
          <datalist id="company-filter-list">
            {companies.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </Field>
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
                : "No retained questions currently need input. Every application still requires review."
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
            const dupInfo =
              questionOccurrences[item.question.trim().toLowerCase()];
            const isDuplicate = dupInfo && dupInfo.count > 1;
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
                  <div className="tag-list">
                    {isDuplicate && (
                      <Badge tone="neutral">
                        {`Seen in ${dupInfo.count} applications${dupInfo.companies.length > 0 ? ` (${dupInfo.companies.join(", ")})` : ""}`}
                      </Badge>
                    )}
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
        onOpenChange={(open) =>
          !open ? handleCloseModal() : setModalOpen(true)
        }
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
                onChange={(e) => {
                  setAnswerText(e.target.value);
                  setFactualConfirmation(false);
                }}
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
                onChange={(e) => {
                  setEvidenceNote(e.target.value);
                  setFactualConfirmation(false);
                }}
                placeholder="e.g. Backed by Project 'Distributed Cache' and 2024 work at Acme Corp"
                required
              />
            </Field>

            <div className="actions">
              <Button
                onClick={() => saveDraftMutation.mutate(selectedItem)}
                busy={saveDraftMutation.isPending}
                disabled={!answerText.trim() || saveDraftMutation.isPending}
                title={
                  !answerText.trim()
                    ? "Answer text is required to save a draft"
                    : undefined
                }
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
              <div className="stack spaced">
                <ErrorState error={saveDraftMutation.error} />
                <Button
                  variant="secondary"
                  onClick={() => saveDraftMutation.mutate(selectedItem)}
                  busy={saveDraftMutation.isPending}
                >
                  <RefreshCw size={12} />
                  Retry saving draft
                </Button>
              </div>
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
                <div className="stack spaced">
                  <ErrorState error={approveMutation.error} />
                  <Button
                    variant="secondary"
                    onClick={() => approveMutation.mutate(selectedItem)}
                    busy={approveMutation.isPending}
                  >
                    <RefreshCw size={12} />
                    Retry approval
                  </Button>
                </div>
              )}

              <div className="actions">
                <Button
                  variant="primary"
                  disabled={
                    hasUnsavedChanges ||
                    selectedItem.status !== "draft" ||
                    selectedItem.stale ||
                    saveDraftMutation.isPending ||
                    !factualConfirmation ||
                    !answerText.trim() ||
                    !evidenceNote.trim() ||
                    approveMutation.isPending
                  }
                  title={
                    hasUnsavedChanges
                      ? "Save draft changes before approving"
                      : selectedItem.status !== "draft"
                        ? "Save answer as draft before approval"
                        : selectedItem.stale
                          ? "Candidate facts changed; review updated background before approving"
                          : !answerText.trim()
                            ? "Answer text is required"
                            : !evidenceNote.trim()
                              ? "Supporting evidence note is required"
                              : !factualConfirmation
                                ? "Confirmation checkbox required before approval"
                                : undefined
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
              <Button variant="ghost" onClick={handleCloseModal}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
