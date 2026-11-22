"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { PublicDiscovery } from "@/features/public-discovery";
import { workflowApi } from "@/lib/workflow-api";
import type {
  WorkflowCapabilities,
  WorkflowControl,
  WorkflowPlan,
  WorkflowRun,
} from "@/lib/workflow-types";

const stages = [
  [
    "planning",
    "Plan",
    "Discovery selects saved jobs and hands source references to matching.",
  ],
  [
    "reasoning",
    "Decide",
    "Specialists propose typed decisions. Optional model-backed planning and review use bounded factual summaries.",
  ],
  [
    "validation",
    "Validate",
    "Check source bindings, verified facts, tool permissions and budgets.",
  ],
  [
    "acting",
    "Use tool",
    "Run one permitted tool with a durable effect identifier.",
  ],
  [
    "observation",
    "Observe",
    "Save the observed result before choosing another action.",
  ],
  [
    "review",
    "Review / replan",
    "Review evidence or return to discovery, matching or answers within the loop limit.",
  ],
  [
    "human_approval",
    "Human approval",
    "Approve these exact results, request changes, or reject the run.",
  ],
  [
    "finished",
    "Finish",
    "Preserve the outcome, audit trail and all spent budgets.",
  ],
] as const;
const box = {
  border: "1px solid var(--line, #94a3b8)",
  background: "var(--surface)",
  borderRadius: 12,
  padding: 16,
  marginBottom: 16,
};
export function ReviewCheckpoint({
  plan,
  busy,
  decide,
}: {
  plan: WorkflowPlan;
  busy: boolean;
  decide: (id: string, decision: string) => void;
}) {
  const [reviewed, setReviewed] = useState(false);
  const pending = plan.graph.approvals.find(
    (item) => item.status === "pending",
  );
  const preparation = plan.prepared_results.find(
    (result) => result.tool === "prepare_application",
  );
  const inspection = plan.prepared_results.find(
    (result) => result.tool === "inspect_application",
  );
  const inspected = inspection?.data;
  const packetId =
    inspected && typeof inspected === "object" && "packet_id" in inspected
      ? inspected.packet_id
      : null;
  useEffect(() => setReviewed(false), [plan.revision, pending?.id]);
  return (
    <section style={box} aria-label="Prepared plan and human decision">
      <h2>Review prepared results</h2>
      <p>
        Plan {plan.graph.plan_revision} · checkpoint {plan.revision}. Approval
        applies to these results and preserves application limits and backend
        checks.
      </p>
      {plan.prepared_results.length === 0 && (
        <p>Tools have not produced reviewable results yet.</p>
      )}
      {typeof packetId === "string" &&
        /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(packetId) && (
          <p>
            <Link href={`/applications/${packetId}`}>
              Open application draft
            </Link>
          </p>
        )}
      {plan.prepared_results.map((result, index) => (
        <details key={`${result.tool}-${index}`}>
          <summary>
            {result.tool} · {result.evidence.length} evidence references
          </summary>
          <p>{result.trust}</p>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              maxHeight: 320,
              overflow: "auto",
            }}
          >
            {JSON.stringify(result.data, null, 2)}
          </pre>
        </details>
      ))}
      {plan.pending_tool != null && (
        <details>
          <summary>Prepared tool action</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(plan.pending_tool, null, 2)}
          </pre>
        </details>
      )}
      {pending && (
        <div style={{ marginTop: 16 }}>
          <p>
            Pending {pending.scope.kind} decision · expires{" "}
            {new Date(pending.expires_at * 1000).toLocaleString()}
          </p>
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />{" "}
            I reviewed these results and the prepared action.
          </label>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 12,
              marginTop: 12,
            }}
          >
            <button
              className="button primary"
              disabled={
                busy || !reviewed || pending.expires_at * 1000 <= Date.now()
              }
              onClick={() => decide(pending.id, "approve")}
            >
              Approve checkpoint
            </button>
            {!preparation && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => decide(pending.id, "request_changes")}
              >
                Request changes
              </button>
            )}
            <button
              className="button danger"
              disabled={busy}
              onClick={() => decide(pending.id, "reject")}
            >
              Reject run
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
export function WorkflowGraph() {
  const [runs, setRuns] = useState<WorkflowRun[]>([]),
    [selected, setSelected] = useState("");
  const [plan, setPlan] = useState<WorkflowPlan | null>(null),
    [control, setControl] = useState<WorkflowControl | null>(null),
    [capabilities, setCapabilities] = useState<WorkflowCapabilities | null>(
      null,
    );
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [stage, setStage] = useState("planning");
  const run = runs.find((item) => item.id === selected);
  const canPrepareDraft = ["prepare_application", "inspect_application"].every(
    (name) =>
      capabilities?.tools?.some(
        (tool) => tool.name === name && tool.status === "available",
      ),
  );
  async function refresh(id = selected) {
    const [listing, mode, features] = await Promise.all([
      workflowApi<{ runs: WorkflowRun[] }>("runs"),
      workflowApi<WorkflowControl>("control"),
      workflowApi<WorkflowCapabilities>("capabilities"),
    ]);
    setRuns(listing.runs);
    setControl(mode);
    setCapabilities(features);
    const chosen = id || listing.runs[0]?.id || "";
    setSelected(chosen);
    setPlan(
      chosen ? await workflowApi<WorkflowPlan>(`runs/${chosen}/plan`) : null,
    );
  }
  useEffect(() => {
    void refresh().catch((e: Error) => setError(e.message));
  }, []); // explicit refresh avoids background private-data polling
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      const next = await action();
      await refresh(typeof next === "string" ? next : selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Workflow unavailable");
    } finally {
      setBusy(false);
    }
  }
  function createReview(preparePacket: boolean) {
    if (!capabilities) return;
    return mutate(async () => {
      const created = await workflowApi<WorkflowRun>("runs", "POST", {
        request_id: crypto.randomUUID(),
        limits: { ...capabilities.recommended_limits, human_review: true },
        ...(preparePacket ? { prepare_packet: true } : {}),
      });
      return created.id;
    });
  }
  return (
    <div style={{ maxWidth: 1120, margin: "0 auto", padding: 24 }}>
      <h1>Agent workflow</h1>
      <p>
        Discovery → matching → verified answers → review → execution. Inspect
        the plan, tool results and human checkpoints.
      </p>
      <p role="status">
        {canPrepareDraft
          ? "Create a saved job review or prepare one draft in Applications."
          : "Saved job review is available."}
      </p>
      {error && <p role="alert">{error}</p>}
      <PublicDiscovery request={workflowApi} />
      <section style={box} aria-label="Worker controls">
        <p>
          Worker:{" "}
          {control
            ? `${control.mode} · ${control.worker_online ? "online" : "offline"}`
            : "connecting"}{" "}
          · Reviewer: {capabilities?.review_model || "unavailable"}
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {(["RUNNING", "PAUSED", "STOPPED"] as const).map((mode) => (
            <button
              className="button secondary"
              key={mode}
              disabled={busy || !control || control.mode === mode}
              onClick={() =>
                void mutate(() =>
                  workflowApi("control", "PUT", {
                    expected_revision: control!.revision,
                    mode,
                  }),
                )
              }
            >
              {mode === "RUNNING"
                ? "Start worker"
                : mode === "PAUSED"
                  ? "Pause worker"
                  : "Stop worker"}
            </button>
          ))}
          <button
            className="button secondary"
            disabled={busy || !capabilities}
            onClick={() => void createReview(false)}
          >
            Create review with approval
          </button>
          {canPrepareDraft && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void createReview(true)}
            >
              Prepare draft and review
            </button>
          )}
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void mutate(() => refresh())}
          >
            Refresh status
          </button>
        </div>
      </section>
      <label>
        Run{" "}
        <select
          className="input"
          value={selected}
          disabled={busy}
          onChange={(e) => {
            setPlan(null);
            setSelected(e.target.value);
            void refresh(e.target.value).catch((error: Error) =>
              setError(error.message),
            );
          }}
        >
          <option value="">Select run</option>
          {runs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.id.slice(0, 8)} · {item.state}
            </option>
          ))}
        </select>
      </label>
      {run && (
        <p>
          Current node: <strong>{run.graph.node}</strong> · Agent: {run.role} ·
          State: {run.state} · Replans {run.graph.iteration}/
          {run.graph.maximum_replans}
          {run.diagnostic ? ` · ${run.diagnostic}` : ""}
        </p>
      )}
      {run &&
        !["completed", "failed", "stopped", "outcome_unknown"].includes(
          run.state,
        ) && (
          <div
            style={{
              display: "flex",
              gap: 12,
              marginTop: 12,
              marginBottom: 16,
            }}
          >
            {[run.state === "paused" ? "resume" : "pause", "stop"].map(
              (action) => (
                <button
                  className={`button ${action === "stop" ? "danger" : "secondary"}`}
                  key={action}
                  disabled={busy}
                  onClick={() =>
                    void mutate(() =>
                      workflowApi(`runs/${run.id}/control`, "POST", {
                        expected_revision: run.revision,
                        action,
                      }),
                    )
                  }
                >
                  {action === "resume"
                    ? "Resume run"
                    : action === "pause"
                      ? "Pause run"
                      : "Stop run"}
                </button>
              ),
            )}
          </div>
        )}
      {run?.question && (
        <section style={box} aria-label="Missing verified fact">
          <h2>Owner input needed</h2>
          <p>{run.question.prompt}</p>
          <Link href="/profile" className="button secondary">
            Review profile
          </Link>
          <p>
            The running worker checks confirmed saved facts automatically.
            Refresh this page after confirming your profile.
          </p>
        </section>
      )}
      <section
        style={{ ...box, marginTop: 16 }}
        aria-label="Interactive execution graph"
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 8,
          }}
        >
          {stages.map(([key, label], i) => (
            <span key={key}>
              <button
                className="button secondary"
                aria-pressed={stage === key}
                onClick={() => setStage(key)}
                style={{
                  padding: 12,
                  border:
                    run?.graph.node === key ? "3px solid #16803d" : undefined,
                }}
              >
                {label}
                {run?.graph.node === key ? " · current" : ""}
              </button>
              {i < stages.length - 1 ? " → " : ""}
            </span>
          ))}
        </div>
        <p>{stages.find(([key]) => key === stage)?.[2]}</p>
        <p>
          ↶ Review can return to planning. Missing facts wait for owner input;
          uncertain external outcomes wait for reconciliation.
        </p>
      </section>
      {plan && (
        <ReviewCheckpoint
          key={`${plan.run_id}:${plan.revision}`}
          plan={plan}
          busy={busy}
          decide={(id, decision) =>
            void mutate(() =>
              workflowApi(`runs/${plan.run_id}/approvals/${id}`, "POST", {
                expected_revision: plan.revision,
                decision,
              }),
            )
          }
        />
      )}
      {capabilities?.tools && (
        <section style={box}>
          <h2>Specialist tools</h2>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Agents</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {capabilities.tools.map((tool) => (
                  <tr key={tool.name}>
                    <td>
                      {tool.name}
                      <p>{tool.description}</p>
                    </td>
                    <td>{tool.roles.join(", ")}</td>
                    <td>{tool.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {run && (
        <section style={box}>
          <h2>Budget and audit</h2>
          <p>
            Run model policy:{" "}
            {run.model_policy?.provider === "cohere"
              ? `${run.model_policy.model} · ${run.model_policy.roles.join(", ")}`
              : run.model_policy?.provider === "deterministic"
                ? "Deterministic specialists"
                : "Legacy review policy"}
            . Available AI roles:{" "}
            {capabilities?.model_roles?.join(", ") || "none"}.
          </p>
          <p>{run.graph.decision_summary}</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(run.usage, null, 2)}
          </pre>
          <details>
            <summary>Approval history</summary>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(run.graph.approvals, null, 2)}
            </pre>
          </details>
        </section>
      )}
    </div>
  );
}
