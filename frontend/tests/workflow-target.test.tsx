import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowGraph } from "@/features/workflow-graph";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/workflow-api", () => ({ workflowApi: request }));
vi.mock("@/features/public-discovery", () => ({ PublicDiscovery: () => null }));

afterEach(() => request.mockReset());

const job = "12345678-1234-4234-8234-123456789abc";

function setup(targeted: boolean) {
  request.mockImplementation(async (path: string, method?: string) => {
    if (method === "POST") return { id: "run" };
    if (path === "runs") return { runs: [] };
    if (path === "control")
      return { mode: "STOPPED", revision: 1, worker_online: true };
    if (path === "capabilities")
      return {
        targeted_packet_review: targeted,
        recommended_limits: { tool_calls: 8 },
        tools: ["prepare_application", "inspect_application"].map((name) => ({
          name,
          status: "available",
          description: "Review a saved job draft",
          roles: ["review"],
          repeatable: false,
        })),
      };
    return null;
  });
}

it("starts a draft for the selected job only after the owner clicks", async () => {
  setup(true);
  render(<WorkflowGraph targetJobId={job} />);
  const action = await screen.findByRole("button", {
    name: "Prepare draft for this job",
  });
  expect(request.mock.calls.some(([, method]) => method === "POST")).toBe(
    false,
  );
  await userEvent.click(action);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("runs", "POST", {
      request_id: expect.any(String),
      limits: { tool_calls: 8, human_review: true },
      prepare_packet: true,
      target_job_id: job,
    }),
  );
});

it("keeps a selected job scoped when the runtime only supports general drafts", async () => {
  setup(false);
  render(<WorkflowGraph targetJobId={job} />);
  await screen.findByText(
    "Reviewing a selected job requires a runtime update.",
  );
  expect(screen.queryByRole("button", { name: /prepare draft/i })).toBeNull();
});
