export interface Approval {
  id: string;
  scope: { kind: "review" } | { kind: "tool"; effect_id: string };
  status: string;
  plan_revision: number;
  expires_at: number;
}
export interface Graph {
  node: string;
  plan_revision: number;
  iteration: number;
  maximum_replans: number;
  human_review: boolean;
  approvals: Approval[];
  decision_summary: string;
}
export interface WorkflowRun {
  id: string;
  revision: number;
  state: string;
  role: string;
  diagnostic: string | null;
  model_policy?:
    | { provider: "deterministic" }
    | { provider: "cohere"; model: string; roles: string[] }
    | null;
  question?: { id: string; prompt: string } | null;
  usage: Record<string, number>;
  graph: Graph;
}
export interface WorkflowPlan {
  run_id: string;
  revision: number;
  graph: Graph;
  pending_tool: unknown;
  prepared_results: Array<{
    tool: string;
    evidence: string[];
    data: unknown;
    trust: string;
  }>;
  approval_grants_submission: boolean;
}
export interface WorkflowControl {
  mode: "STOPPED" | "PAUSED" | "RUNNING";
  revision: number;
  worker_online: boolean;
}
export interface WorkflowCapabilities {
  review_model: string;
  model_roles?: string[];
  recommended_limits: Record<string, number | boolean>;
  application_dispatch: boolean;
  tools?: Array<{
    name: string;
    description: string;
    roles: string[];
    repeatable: boolean;
    status: string;
  }>;
}
