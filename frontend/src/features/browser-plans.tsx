"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "@/lib/api";
import { Button, ErrorState, Notice } from "@/components/ui";

type Plan = {
  id: string;
  mode: string;
  state: string;
  expires_at: string;
  target_url: string;
  inspection: {
    fields: { field_id: string; label: string }[];
    has_next: boolean;
  };
  actions: {
    field_id: string;
    value: string | null;
    safe_reference: string | null;
    evidence: string[];
    candidate_version: number;
    project_version: string | null;
    needs_input: boolean;
    requires_review: boolean;
  }[];
};
export function BrowserPlans() {
  const client = useQueryClient();
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const plans = useQuery({
    queryKey: ["browser-plans"],
    queryFn: () => api<Plan[]>("browser/plans"),
    refetchInterval: 3000,
  });
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["browser-plans"] });
  const review = useMutation({
    mutationFn: (plan: Plan) =>
      post(`browser/plans/${plan.id}/review`, {
        field_ids: plan.actions
          .filter((a) => !a.needs_input && selected[`${plan.id}:${a.field_id}`])
          .map((a) => a.field_id),
      }),
    onSuccess: refresh,
  });
  const stop = useMutation({
    mutationFn: () => post("browser/stop"),
    onSuccess: refresh,
  });
  const next = useMutation({
    mutationFn: (id: string) => post(`browser/plans/${id}/next`),
    onSuccess: refresh,
  });
  return (
    <div className="stack">
      <h2>Chrome form plans</h2>
      <Notice>
        Review each proposed value and its evidence. Filled forms remain in
        Chrome for inspection. Submission requires separate exact approval in
        Submission review. Sign-in and CAPTCHA/MFA require you.
      </Notice>
      <Button onClick={() => stop.mutate()} disabled={stop.isPending}>
        Stop filling applications
      </Button>
      {plans.isError && <ErrorState error={plans.error} />}
      {review.isError && <ErrorState error={review.error} />}
      {next.isError && <ErrorState error={next.error} />}
      {(Array.isArray(plans.data) ? plans.data : []).map((plan) => (
        <article className="panel stack" key={plan.id}>
          <p>
            {plan.mode} · {plan.state}
          </p>
          <p>{plan.target_url}</p>
          <p>Plan expires {new Date(plan.expires_at).toLocaleString()}</p>
          {plan.actions.map((a) => (
            <label key={a.field_id} className="stack">
              <span>
                <input
                  type="checkbox"
                  aria-label={
                    plan.inspection.fields.find(
                      (f) => f.field_id === a.field_id,
                    )?.label || a.field_id
                  }
                  disabled={a.needs_input || plan.state !== "preview"}
                  checked={selected[`${plan.id}:${a.field_id}`] || false}
                  onChange={(e) =>
                    setSelected({
                      ...selected,
                      [`${plan.id}:${a.field_id}`]: e.target.checked,
                    })
                  }
                />{" "}
                {plan.inspection.fields.find((f) => f.field_id === a.field_id)
                  ?.label || a.field_id}
              </span>
              <span>
                {a.needs_input
                  ? "Needs input — field will remain untouched"
                  : a.value || "Confirmed canonical PDF"}
              </span>
              <small>
                Profile version {a.candidate_version}; evidence:{" "}
                {a.evidence.join(", ") || "Missing"}
                {a.project_version ? `; project ${a.project_version}` : ""}
              </small>
            </label>
          ))}
          {plan.mode === "local_automation" && plan.state === "preview" && (
            <Button
              disabled={review.isPending}
              onClick={() => review.mutate(plan)}
            >
              Approve selected fields for filling
            </Button>
          )}
          {plan.mode === "local_automation" &&
            plan.state === "finished" &&
            plan.inspection.has_next && (
              <Button
                disabled={next.isPending}
                onClick={() => next.mutate(plan.id)}
              >
                Inspect next step
              </Button>
            )}
        </article>
      ))}
    </div>
  );
}
