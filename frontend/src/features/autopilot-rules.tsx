"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, patch, readable } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Select,
  Skeleton,
} from "@/components/ui";
import {
  UNKNOWN_APPLICANTS_POLICIES,
  authTone,
  rulesPatch,
  rulesToForm,
  saveErrorMessage,
  stamp,
  type PortalRules,
  type PortalRulesForm,
  type UnknownApplicantsPolicy,
} from "@/features/autopilot-forms";
import { STATUS_KEY } from "@/features/autopilot-status";

export const RULES_KEY = ["v2-portal-rules"] as const;

const NUMBER_INPUTS: ReadonlyArray<
  [
    keyof Pick<
      PortalRulesForm,
      | "max_applies_per_day"
      | "max_applies_per_hour"
      | "max_job_age_days"
      | "max_applicants"
      | "min_delay_sec"
      | "max_delay_sec"
    >,
    string,
    string,
    number,
    number | undefined,
  ]
> = [
  ["max_applies_per_day", "Max applications per day", "1–500.", 1, 500],
  [
    "max_applies_per_hour",
    "Max applications per hour",
    "1–100, not above the daily cap.",
    1,
    100,
  ],
  [
    "max_job_age_days",
    "Max job age (days)",
    "Older postings are filtered out.",
    1,
    365,
  ],
  [
    "max_applicants",
    "Max applicants",
    "Skip jobs with more applicants than this.",
    1,
    undefined,
  ],
  [
    "min_delay_sec",
    "Min delay between applies (s)",
    "At least 5.",
    5,
    undefined,
  ],
  [
    "max_delay_sec",
    "Max delay between applies (s)",
    "Not below the minimum delay.",
    5,
    undefined,
  ],
];

type Feedback = { tone: "ok" | "error"; text: string } | null;

function PortalRulesCard({ rules }: { rules: PortalRules }) {
  const client = useQueryClient();
  const [base, setBase] = useState(rules);
  const [form, setForm] = useState(() => rulesToForm(rules));
  const [feedback, setFeedback] = useState<Feedback>(null);
  if (base.revision !== rules.revision || base.platform !== rules.platform) {
    // Server data moved on (saved here, reloaded after a conflict, or edited
    // elsewhere): start again from the latest saved values.
    setBase(rules);
    setForm(rulesToForm(rules));
  }
  const { patch: body, changed, errors } = rulesPatch(rules, form);
  const name = rules.label || readable(rules.platform);
  const ready = rules.adapter_status === "ready";
  const save = useMutation({
    mutationFn: () =>
      patch<PortalRules>(`v2/portal-rules/${rules.platform}`, body),
    onSuccess: (updated) => {
      client.setQueryData<PortalRules[]>(RULES_KEY, (rows) =>
        rows?.map((row) => (row.platform === updated.platform ? updated : row)),
      );
      client.invalidateQueries({ queryKey: STATUS_KEY });
      setFeedback({
        tone: "ok",
        text: `Saved ${name} rules (${changed.length} change${changed.length === 1 ? "" : "s"}, revision ${updated.revision}). The worker uses them on its next cycle — no restart needed.`,
      });
    },
    onError: (error) => {
      setFeedback({ tone: "error", text: saveErrorMessage(error) });
      if (error instanceof ApiError && error.status === 409)
        client.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
  const update = <K extends keyof PortalRulesForm>(
    key: K,
    value: PortalRulesForm[K],
  ) => {
    setFeedback(null);
    setForm((current) => ({ ...current, [key]: value }));
  };
  const id = `rules-${rules.platform}`;
  return (
    <section className="panel rules-card" aria-labelledby={id}>
      <div className="panel-header">
        <div>
          <h3 id={id}>{name}</h3>
          <p>
            Revision {rules.revision} · Updated{" "}
            {stamp(rules.updated_at, "never")}
          </p>
        </div>
        <div className="tag-list">
          <Badge tone={ready ? "green" : "neutral"}>
            {ready ? "Adapter ready" : "Phase 6 adapter pending"}
          </Badge>
          {rules.requires_login ? (
            <Badge tone={authTone(rules.auth_status)}>
              {readable(rules.auth_status)}
            </Badge>
          ) : (
            <Badge tone="neutral">No login needed</Badge>
          )}
        </div>
      </div>
      {!ready && (
        <p className="portal-hint">
          Rules are saved now; this portal only runs once its adapter ships in
          Phase 6, even if enabled.
        </p>
      )}
      <form
        className="panel-body stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (!changed.length || errors.length) return;
          setFeedback(null);
          save.mutate();
        }}
      >
        <div className="tag-list">
          <label className="check-label">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => update("enabled", e.target.checked)}
            />
            Portal enabled (discover and score jobs)
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={form.auto_apply_enabled}
              onChange={(e) => update("auto_apply_enabled", e.target.checked)}
            />
            Auto-apply enabled (submit without asking)
          </label>
        </div>
        <div className="form-grid">
          {NUMBER_INPUTS.map(([key, label, hint, min, max]) => (
            <Field key={key} label={label} hint={hint}>
              <Input
                type="number"
                inputMode="numeric"
                min={min}
                max={max}
                step={1}
                value={form[key]}
                onChange={(e) => update(key, e.target.value)}
              />
            </Field>
          ))}
          <Field
            label="When applicant count is unknown"
            hint="Applies when a portal hides or rounds the applicant count."
          >
            <Select
              value={form.unknown_applicants_policy}
              onChange={(e) =>
                update(
                  "unknown_applicants_policy",
                  e.target.value as UnknownApplicantsPolicy,
                )
              }
            >
              {UNKNOWN_APPLICANTS_POLICIES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Timezone" hint="IANA name, for example Asia/Kolkata.">
            <Input
              value={form.timezone}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => update("timezone", e.target.value)}
            />
          </Field>
          <Field
            label="Active hours start"
            hint="Leave both empty to run at any hour."
          >
            <Input
              type="time"
              value={form.active_hours_start}
              onChange={(e) => update("active_hours_start", e.target.value)}
            />
          </Field>
          <Field label="Active hours end">
            <Input
              type="time"
              value={form.active_hours_end}
              onChange={(e) => update("active_hours_end", e.target.value)}
            />
          </Field>
        </div>
        {errors.length > 0 && (
          <ul className="form-errors" role="alert">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}
        <div className="actions">
          <Button
            type="submit"
            variant="primary"
            busy={save.isPending}
            disabled={!changed.length || errors.length > 0}
          >
            Save {name} rules
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={!changed.length || save.isPending}
            onClick={() => {
              setFeedback(null);
              setForm(rulesToForm(rules));
            }}
          >
            Discard changes
          </Button>
          <span className="muted small-print">
            {changed.length
              ? `${changed.length} unsaved change${changed.length === 1 ? "" : "s"}`
              : "No unsaved changes"}
          </span>
        </div>
        <div
          role="status"
          className={
            feedback
              ? `notice ${feedback.tone === "error" ? "warn" : ""}`
              : undefined
          }
        >
          {feedback?.text}
        </div>
      </form>
    </section>
  );
}

export function PortalRulesEditor() {
  const rules = useQuery({
    queryKey: RULES_KEY,
    queryFn: () => api<PortalRules[]>("v2/portal-rules"),
  });
  return (
    <section className="spaced" aria-labelledby="rules-heading">
      <div className="section-heading">
        <h2 id="rules-heading">Portal permissions &amp; rules</h2>
        <p className="muted">
          Caps, filters and pacing for all 10 portals. Changes apply on the
          worker’s next cycle — no restart needed. Defaults: 50/day, 10/hour,
          jobs under 7 days old, at most 300 applicants, 45–150 s between
          applies, 08:00–23:30 IST.
        </p>
      </div>
      {rules.isPending ? (
        <Skeleton />
      ) : rules.isError ? (
        <ErrorState error={rules.error} retry={() => rules.refetch()} />
      ) : rules.data.length === 0 ? (
        <p className="muted">
          No portal rules exist yet. They appear once the v2 migration has run.
        </p>
      ) : (
        <div className="rules-grid">
          {rules.data.map((row) => (
            <PortalRulesCard key={row.platform} rules={row} />
          ))}
        </div>
      )}
    </section>
  );
}
