"use client";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, patch, post } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";
import {
  formatList,
  parseList,
  saveErrorMessage,
  type ScreeningProfile,
  type ScreeningProfilePatch,
} from "@/features/autopilot-forms";
import { SCREENING_KEY } from "@/features/autopilot-screening";
import { PortalRulesEditor } from "@/features/autopilot-rules";

/** POST v2/rules/explain (milestone 2 contract). */
export type RulesExplain = {
  decision: string;
  passed: boolean;
  reasons: string[];
  checks: Array<{ name: string; passed: boolean; detail?: string | null }>;
  score: { total: number | null; breakdown: Record<string, number> };
};
type TelemetryTelegram = {
  telegram?: {
    quiet_hours?: string | null;
    quiet_hours_active?: boolean;
    muted_until?: string | null;
  };
};

const LISTS = [
  ["target_roles", "Target roles", "Titles the worker searches and accepts."],
  [
    "keywords_excluded",
    "Excluded title keywords",
    "Any match filters the job out.",
  ],
  ["company_blacklist", "Excluded companies", "Never applied to."],
  [
    "keywords_required",
    "Required keywords",
    "At least one must appear in the JD.",
  ],
] as const;
const NUMBERS = [
  ["total_experience_years", "Your experience (years)", 0, 60],
  ["max_required_experience_years", "Max required experience (years)", 0, 60],
  ["min_match_score", "Minimum match score", 0, 100],
] as const;
type ListKey = (typeof LISTS)[number][0];
type NumberKey = (typeof NUMBERS)[number][0];
type HardRules = Record<ListKey | NumberKey, string> & {
  current_location: string;
  remote_policy: string;
};

export function toHardRules(p: ScreeningProfile): HardRules {
  const form = {} as HardRules;
  for (const [key] of LISTS) form[key] = formatList(p[key]);
  for (const [key] of NUMBERS) form[key] = p[key] == null ? "" : String(p[key]);
  form.current_location = p.current_location ?? "";
  form.remote_policy = p.remote_policy ?? "";
  return form;
}

/** Smallest PATCH body (changed fields + version) and validation errors. */
export function hardRulesPatch(p: ScreeningProfile, form: HardRules) {
  const body: Record<string, unknown> = { version: p.version };
  const errors: string[] = [];
  for (const [key] of LISTS) {
    const next = parseList(form[key]);
    if (next.join("\n") !== (p[key] ?? []).join("\n")) body[key] = next;
  }
  for (const [key, label, min, max] of NUMBERS) {
    const text = form[key].trim();
    const value = text === "" ? null : Number(text);
    if (
      value !== null &&
      (!Number.isFinite(value) || value < min || value > max)
    ) {
      errors.push(`${label} must be between ${min} and ${max}.`);
      continue;
    }
    if (value !== (p[key] ?? null)) body[key] = value;
  }
  if (form.current_location.trim() !== (p.current_location ?? ""))
    body.current_location = form.current_location.trim() || null;
  if (form.remote_policy !== (p.remote_policy ?? ""))
    body.remote_policy = form.remote_policy || null;
  const changed = Object.keys(body).filter((k) => k !== "version");
  return { body: body as ScreeningProfilePatch, changed, errors };
}

function HardRulesForm({ profile }: { profile: ScreeningProfile }) {
  const client = useQueryClient();
  const [version, setVersion] = useState(profile.version);
  const [form, setForm] = useState(() => toHardRules(profile));
  if (version !== profile.version) {
    setVersion(profile.version);
    setForm(toHardRules(profile));
  }
  const { body, changed, errors } = hardRulesPatch(profile, form);
  const save = useMutation({
    mutationFn: () => patch<ScreeningProfile>("v2/screening-profile", body),
    onSuccess: (updated) => client.setQueryData(SCREENING_KEY, updated),
    onError: (error) => {
      if (error instanceof ApiError && [404, 409].includes(error.status))
        client.invalidateQueries({ queryKey: SCREENING_KEY });
    },
  });
  const set = (key: keyof HardRules, value: string) => {
    save.reset();
    setForm((f) => ({ ...f, [key]: value }));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (changed.length && !errors.length) save.mutate();
  };
  return (
    <form
      className="panel-body stack"
      onSubmit={submit}
      aria-label="Hard rules"
    >
      <div className="form-grid">
        {LISTS.map(([key, label, hint]) => (
          <Field key={key} label={label} hint={`${hint} Comma separated.`}>
            <Input
              value={form[key]}
              onChange={(e) => set(key, e.target.value)}
            />
          </Field>
        ))}
        {NUMBERS.map(([key, label, min, max]) => (
          <Field key={key} label={label}>
            <Input
              type="number"
              inputMode="decimal"
              min={min}
              max={max}
              step="any"
              value={form[key]}
              onChange={(e) => set(key, e.target.value)}
            />
          </Field>
        ))}
        <Field label="Current location">
          <Input
            value={form.current_location}
            onChange={(e) => set("current_location", e.target.value)}
          />
        </Field>
        <Field label="Work arrangement">
          <Select
            value={form.remote_policy}
            onChange={(e) => set("remote_policy", e.target.value)}
          >
            <option value="">Not set</option>
            <option value="any">Any arrangement</option>
            <option value="remote_only">Remote only</option>
            <option value="hybrid_ok">Remote or hybrid</option>
            <option value="onsite_ok">Remote, hybrid or on-site</option>
          </Select>
        </Field>
      </div>
      {errors.length > 0 && (
        <div className="notice warn" role="alert">
          {errors.join(" ")}
        </div>
      )}
      <div className="actions">
        <Button
          type="submit"
          variant="primary"
          busy={save.isPending}
          disabled={!changed.length || errors.length > 0}
        >
          Save {changed.length || ""} change{changed.length === 1 ? "" : "s"}
        </Button>
      </div>
      {save.isSuccess && (
        <Notice>Saved. The worker uses them on its next cycle.</Notice>
      )}
      {save.isError && (
        <div className="notice warn" role="alert">
          {saveErrorMessage(save.error)}
        </div>
      )}
    </form>
  );
}

export function ExplainResult({ result }: { result: RulesExplain }) {
  const breakdown = Object.entries(result.score.breakdown ?? {});
  return (
    <div className="stack" aria-label="Rules verdict">
      <div className="tag-list">
        <Badge tone={result.passed ? "green" : "red"}>
          {result.passed ? "Passes your rules" : "Filtered out"} ·{" "}
          {result.decision}
        </Badge>
        {result.score.total != null && (
          <Badge tone="neutral">Score {result.score.total}</Badge>
        )}
      </div>
      {result.reasons.length > 0 && (
        <ul className="stack">
          {result.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <div className="table-wrap">
        <table>
          <caption className="visually-hidden">Rule checks</caption>
          <thead>
            <tr>
              <th scope="col">CHECK</th>
              <th scope="col">RESULT</th>
              <th scope="col">DETAIL</th>
            </tr>
          </thead>
          <tbody>
            {result.checks.map((check) => (
              <tr key={check.name}>
                <td>{check.name.replaceAll("_", " ")}</td>
                <td>
                  <Badge tone={check.passed ? "green" : "red"}>
                    {check.passed ? "pass" : "fail"}
                  </Badge>
                </td>
                <td className="reason-cell">{check.detail || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {breakdown.length > 0 && (
        <dl className="worker-facts" aria-label="Score breakdown">
          {breakdown.map(([name, value]) => (
            <div key={name}>
              <dt>{name.replaceAll("_", " ")}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const SANDBOX_FIELDS = [
  ["title", "Job title"],
  ["company", "Company"],
  ["location", "Location"],
  ["experience_text", "Experience required (as posted)"],
  ["url", "Job URL (optional)"],
] as const;
type SandboxKey = (typeof SANDBOX_FIELDS)[number][0] | "description";

function Sandbox() {
  const [job, setJob] = useState<Record<SandboxKey, string>>({
    title: "",
    company: "",
    location: "",
    experience_text: "",
    url: "",
    description: "",
  });
  const explain = useMutation({
    mutationFn: () =>
      post<RulesExplain>(
        "v2/rules/explain",
        Object.fromEntries(
          Object.entries(job)
            .map(([k, v]) => [k, v.trim()])
            .filter(([, v]) => v),
        ),
      ),
  });
  const ready = Boolean(job.title.trim() || job.url.trim());
  return (
    <section className="panel" aria-labelledby="rules-sandbox">
      <div className="panel-header">
        <div>
          <h2 id="rules-sandbox">Test a job against your rules</h2>
          <p>
            Nothing is fetched or applied — the job you describe is scored
            offline.
          </p>
        </div>
      </div>
      <form
        className="panel-body stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) explain.mutate();
        }}
      >
        <div className="form-grid">
          {SANDBOX_FIELDS.map(([key, label]) => (
            <Field key={key} label={label}>
              <Input
                value={job[key]}
                onChange={(e) =>
                  setJob((j) => ({ ...j, [key]: e.target.value }))
                }
              />
            </Field>
          ))}
          <Field label="Description">
            <textarea
              className="input"
              rows={4}
              maxLength={20000}
              value={job.description}
              onChange={(e) =>
                setJob((j) => ({ ...j, description: e.target.value }))
              }
            />
          </Field>
        </div>
        <div className="actions">
          <Button
            type="submit"
            variant="primary"
            busy={explain.isPending}
            disabled={!ready}
          >
            Test job
          </Button>
        </div>
        {explain.isError && <ErrorState error={explain.error} />}
        {explain.data && <ExplainResult result={explain.data} />}
      </form>
    </section>
  );
}

export function RulesStudio() {
  const profile = useQuery({
    queryKey: SCREENING_KEY,
    queryFn: () => api<ScreeningProfile>("v2/screening-profile"),
  });
  const telemetry = useQuery({
    queryKey: ["v2-worker-telemetry"],
    queryFn: () => api<TelemetryTelegram>("v2/worker/telemetry"),
    refetchInterval: 30000,
  });
  const tg = telemetry.data?.telegram;
  return (
    <>
      <PageTitle
        eyebrow="RULES · PREFERENCES"
        title="Rules Studio"
        description="Hard rules decide which jobs the worker may apply to. Test any job before it reaches the queue."
      />
      <section className="panel" aria-labelledby="hard-rules">
        <div className="panel-header">
          <div>
            <h2 id="hard-rules">Hard rules</h2>
            <p>
              Shared by every portal. Per-portal caps and active hours are
              below.
            </p>
          </div>
          {tg && (
            <div className="tag-list">
              <Badge tone={tg.quiet_hours_active ? "amber" : "neutral"}>
                Quiet hours: {tg.quiet_hours || "off"}
              </Badge>
              <Badge tone="neutral">Digest: twice daily (Telegram)</Badge>
            </div>
          )}
        </div>
        {profile.isPending ? (
          <Skeleton />
        ) : profile.isError ? (
          <ErrorState error={profile.error} retry={() => profile.refetch()} />
        ) : (
          <HardRulesForm profile={profile.data} />
        )}
      </section>
      <Sandbox />
      <PortalRulesEditor />
    </>
  );
}
