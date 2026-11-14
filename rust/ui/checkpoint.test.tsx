import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewCheckpoint, workflowApi } from "@/features/workflow-graph";
import type { WorkflowPlan } from "@/lib/workflow-types";
function plan(revision = 12): WorkflowPlan {
  return {
    run_id: "fictional",
    revision,
    pending_tool: null,
    approval_grants_submission: false,
    prepared_results: [
      {
        tool: "rank_jobs",
        evidence: ["saved-id"],
        trust: "observed data",
        data: { text: "<img src=x onerror=alert(1)>", score: 80 },
      },
    ],
    graph: {
      node: "human_approval",
      plan_revision: 1,
      iteration: 0,
      maximum_replans: 2,
      human_review: true,
      decision_summary: "fixture",
      approvals: [
        {
          id: "approval-one",
          scope: { kind: "review" },
          status: "pending",
          plan_revision: 1,
          expires_at: Math.floor(Date.now() / 1000) + 3600,
        },
      ],
    },
  };
}
describe("exact checkpoint review", () => {
  it("requires reviewing displayed results and sends only the selected checkpoint decision", () => {
    const decide = vi.fn();
    render(<ReviewCheckpoint plan={plan()} busy={false} decide={decide} />);
    expect(
      screen.getByRole("button", { name: "Approve checkpoint" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Approve checkpoint" }));
    expect(decide).toHaveBeenCalledExactlyOnceWith("approval-one", "approve");
    expect(
      screen.getByText(/application limits and backend checks/),
    ).toBeInTheDocument();
  });
  it("revokes the local review checkbox when a newer checkpoint arrives", () => {
    const decide = vi.fn();
    const view = render(
      <ReviewCheckpoint plan={plan()} busy={false} decide={decide} />,
    );
    fireEvent.click(screen.getByRole("checkbox"));
    view.rerender(
      <ReviewCheckpoint plan={plan(13)} busy={false} decide={decide} />,
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Approve checkpoint" }),
    ).toBeDisabled();
  });
  it("renders untrusted tool content as text and keeps reject/request changes available", () => {
    const decide = vi.fn();
    const view = render(
      <ReviewCheckpoint plan={plan()} busy={false} decide={decide} />,
    );
    expect(view.container.querySelector("img")).toBeNull();
    expect(view.container.textContent).toContain(
      "<img src=x onerror=alert(1)>",
    );
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject run" }));
    expect(decide.mock.calls).toEqual([
      ["approval-one", "request_changes"],
      ["approval-one", "reject"],
    ]);
  });
  it("prevents approving an expired checkpoint even after reading it", () => {
    const expired = plan();
    expired.graph.approvals[0].expires_at = 1;
    render(<ReviewCheckpoint plan={expired} busy={false} decide={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(
      screen.getByRole("button", { name: "Approve checkpoint" }),
    ).toBeDisabled();
  });
  it("carries CSRF and exact revision and never retries a stale approval mutation", async () => {
    document.cookie = "aa_csrf=fixture-csrf";
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ error: "agent_revision_conflict" }), {
          status: 409,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(
      workflowApi("runs/run/approvals/approval", "POST", {
        expected_revision: 12,
        decision: "approve",
      }),
    ).rejects.toThrow("checkpoint changed");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].headers["x-csrf-token"]).toBe("fixture-csrf");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      expected_revision: 12,
      decision: "approve",
    });
    vi.unstubAllGlobals();
  });
});
