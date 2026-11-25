import { ApiError, type Schema } from "@/lib/api";

export type PortalRules = Schema<"PortalRulesRead">;
export type PortalRulesPatch = Schema<"PortalRulesPatch">;
export type ScreeningProfile = Schema<"ScreeningProfileRead">;
export type ScreeningProfilePatch = Schema<"ScreeningProfilePatch">;
export type UnknownApplicantsPolicy = PortalRules["unknown_applicants_policy"];
export type RemotePolicy = NonNullable<ScreeningProfile["remote_policy"]>;
export type SkillMatchMode = NonNullable<ScreeningProfile["skill_match_mode"]>;

export const APPLICATION_STATES = [
  "DISCOVERED",
  "FILTERED_OUT",
  "SCORED",
  "APPLYING",
  "WAITING_FOR_USER",
  "APPLIED",
  "QUOTA_HIT_PENDING",
  "DRAFTED_AND_QUEUED",
  "SUBMISSION_UNKNOWN",
  "FAILED",
] as const satisfies readonly Schema<"ApplicationState">[];

export const UNKNOWN_APPLICANTS_POLICIES: ReadonlyArray<
  [UnknownApplicantsPolicy, string]
> = [
  ["allow_lower_bound", "Use lower bound (“100+” counts as 100)"],
  ["allow", "Allow when the count is unknown"],
  ["skip", "Skip when the count is unknown"],
  ["needs_review", "Ask me when the count is unknown"],
];

export const REMOTE_POLICIES: ReadonlyArray<[RemotePolicy, string]> = [
  ["any", "Any arrangement"],
  ["remote_only", "Remote only"],
  ["hybrid_ok", "Remote or hybrid"],
  ["onsite_ok", "Remote, hybrid or on-site"],
];

export const SKILL_MATCH_MODES: ReadonlyArray<[SkillMatchMode, string]> = [
  ["any", "Any listed skill matches"],
  ["all", "All listed skills must match"],
];

export type Tone = "neutral" | "green" | "amber" | "red";

export function stateTone(state: string): Tone {
  if (state === "APPLIED") return "green";
  if (state === "FAILED" || state === "SUBMISSION_UNKNOWN") return "red";
  if (
    state === "WAITING_FOR_USER" ||
    state === "QUOTA_HIT_PENDING" ||
    state === "DRAFTED_AND_QUEUED"
  )
    return "amber";
  return "neutral";
}

export function authTone(status: string): Tone {
  if (status === "OK") return "green";
  if (status === "AUTH_REQUIRED") return "red";
  return "neutral";
}

/** Percentage of a quota used, clamped to 0–100. */
export function quotaPercent(used: number, max: number) {
  if (!Number.isFinite(used) || !Number.isFinite(max) || max <= 0)
    return used > 0 ? 100 : 0;
  return Math.min(100, Math.max(0, Math.round((used / max) * 100)));
}

export function ageLabel(seconds?: number | null) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds))
    return "No heartbeat yet";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s ago`;
  if (s < 86400)
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function stamp(value?: string | null, fallback = "Never") {
  return value ? new Date(value).toLocaleString("en-IN") : fallback;
}

/** Splits comma or newline separated text into trimmed, de-duplicated entries. */
export function parseList(text: string) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of text.split(/[,\n]/)) {
    const entry = raw.trim();
    const key = entry.toLowerCase();
    if (entry && !seen.has(key)) {
      seen.add(key);
      result.push(entry);
    }
  }
  return result;
}

export function formatList(values?: readonly string[] | null) {
  return (values || []).join(", ");
}

function sameList(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

/** Reads the most useful message from an API error for an inline notice. */
export function saveErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 409)
      return "These settings changed elsewhere — the latest values were reloaded. Re-apply your edits and save again.";
    if (error.status === 422) return `Not saved: ${error.message}`;
    if (error.status === 404)
      return "Not saved: no candidate profile exists yet.";
    return `Not saved: ${error.message}`;
  }
  return error instanceof Error ? `Not saved: ${error.message}` : "Not saved.";
}

// ---------- Portal rules ----------

export type PortalRulesForm = {
  enabled: boolean;
  auto_apply_enabled: boolean;
  max_applies_per_day: string;
  max_applies_per_hour: string;
  max_job_age_days: string;
  max_applicants: string;
  unknown_applicants_policy: UnknownApplicantsPolicy;
  min_delay_sec: string;
  max_delay_sec: string;
  active_hours_start: string;
  active_hours_end: string;
  timezone: string;
};

const timeValue = (value?: string | null) => (value ? value.slice(0, 5) : "");

export function rulesToForm(rules: PortalRules): PortalRulesForm {
  return {
    enabled: rules.enabled,
    auto_apply_enabled: rules.auto_apply_enabled,
    max_applies_per_day: String(rules.max_applies_per_day),
    max_applies_per_hour: String(rules.max_applies_per_hour),
    max_job_age_days: String(rules.max_job_age_days),
    max_applicants: String(rules.max_applicants),
    unknown_applicants_policy: rules.unknown_applicants_policy,
    min_delay_sec: String(rules.min_delay_sec),
    max_delay_sec: String(rules.max_delay_sec),
    active_hours_start: timeValue(rules.active_hours_start),
    active_hours_end: timeValue(rules.active_hours_end),
    timezone: rules.timezone,
  };
}

type IntegerKey =
  | "max_applies_per_day"
  | "max_applies_per_hour"
  | "max_job_age_days"
  | "max_applicants"
  | "min_delay_sec"
  | "max_delay_sec";

const INTEGER_RULES: ReadonlyArray<[IntegerKey, string, number, number?]> = [
  ["max_applies_per_day", "Daily cap", 1, 500],
  ["max_applies_per_hour", "Hourly cap", 1, 100],
  ["max_job_age_days", "Maximum job age", 1, 365],
  ["max_applicants", "Maximum applicants", 1],
  ["min_delay_sec", "Minimum delay", 5],
  ["max_delay_sec", "Maximum delay", 5],
];

const HH_MM = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * Builds the smallest PATCH body (changed fields + revision) and lists the
 * validation problems that would make the backend answer 422.
 */
export function rulesPatch(
  rules: PortalRules,
  form: PortalRulesForm,
): { patch: PortalRulesPatch; changed: string[]; errors: string[] } {
  const errors: string[] = [];
  const numbers = {} as Record<IntegerKey, number>;
  for (const [key, label, min, max] of INTEGER_RULES) {
    const text = form[key].trim();
    const value = Number(text);
    if (!text || !Number.isInteger(value)) {
      errors.push(`${label} must be a whole number.`);
      continue;
    }
    if (value < min || (max !== undefined && value > max)) {
      errors.push(
        max === undefined
          ? `${label} must be at least ${min}.`
          : `${label} must be between ${min} and ${max}.`,
      );
    }
    numbers[key] = value;
  }
  if (
    numbers.max_applies_per_hour !== undefined &&
    numbers.max_applies_per_day !== undefined &&
    numbers.max_applies_per_hour > numbers.max_applies_per_day
  )
    errors.push("Hourly cap cannot exceed the daily cap.");
  if (
    numbers.min_delay_sec !== undefined &&
    numbers.max_delay_sec !== undefined &&
    numbers.max_delay_sec < numbers.min_delay_sec
  )
    errors.push("Maximum delay must be at least the minimum delay.");
  for (const [key, label] of [
    ["active_hours_start", "Active hours start"],
    ["active_hours_end", "Active hours end"],
  ] as const) {
    if (form[key] && !HH_MM.test(form[key]))
      errors.push(`${label} must use HH:MM.`);
  }
  const timezone = form.timezone.trim();
  if (!timezone)
    errors.push("Timezone is required (for example Asia/Kolkata).");

  const patch: PortalRulesPatch = { revision: rules.revision };
  const changed: string[] = [];
  const set = <K extends keyof PortalRulesPatch>(
    key: K,
    value: PortalRulesPatch[K],
  ) => {
    patch[key] = value;
    changed.push(key);
  };
  if (form.enabled !== rules.enabled) set("enabled", form.enabled);
  if (form.auto_apply_enabled !== rules.auto_apply_enabled)
    set("auto_apply_enabled", form.auto_apply_enabled);
  for (const [key] of INTEGER_RULES) {
    if (numbers[key] !== undefined && numbers[key] !== rules[key])
      set(key, numbers[key]);
  }
  if (form.unknown_applicants_policy !== rules.unknown_applicants_policy)
    set("unknown_applicants_policy", form.unknown_applicants_policy);
  for (const key of ["active_hours_start", "active_hours_end"] as const) {
    if (form[key] !== timeValue(rules[key])) set(key, form[key] || null);
  }
  if (timezone && timezone !== rules.timezone) set("timezone", timezone);
  return { patch, changed, errors };
}

// ---------- Screening profile ----------

export type ListKey =
  | "target_roles"
  | "keywords_required"
  | "keywords_excluded"
  | "tech_stack"
  | "company_blacklist";

export const LIST_FIELDS: ReadonlyArray<[ListKey, string, string]> = [
  ["target_roles", "Target roles", "e.g. Backend Engineer, SDE 1"],
  [
    "keywords_required",
    "Required keywords",
    "A job must mention these to be scored.",
  ],
  [
    "keywords_excluded",
    "Excluded keywords",
    "Jobs mentioning any of these are filtered out.",
  ],
  ["tech_stack", "Tech stack", "e.g. Python, FastAPI, PostgreSQL"],
  [
    "company_blacklist",
    "Company blacklist",
    "Companies that are never applied to.",
  ],
];

export type NumberKey =
  | "current_ctc"
  | "expected_ctc"
  | "min_ctc"
  | "notice_period_days"
  | "total_experience_years"
  | "min_match_score";

export const NUMBER_FIELDS: ReadonlyArray<
  [NumberKey, string, string, { min: number; max?: number; integer?: boolean }]
> = [
  ["current_ctc", "Current CTC (LPA)", "Lakhs per annum, INR.", { min: 0 }],
  ["expected_ctc", "Expected CTC (LPA)", "Lakhs per annum, INR.", { min: 0 }],
  [
    "min_ctc",
    "Minimum acceptable CTC (LPA)",
    "Jobs advertising less are skipped.",
    { min: 0 },
  ],
  [
    "notice_period_days",
    "Notice period (days)",
    "Whole days.",
    { min: 0, max: 365, integer: true },
  ],
  [
    "total_experience_years",
    "Total experience (years)",
    "Decimals allowed, e.g. 1.5.",
    { min: 0, max: 60 },
  ],
  [
    "min_match_score",
    "Minimum match score",
    "0–100. Lower-scoring jobs are filtered out.",
    { min: 0, max: 100 },
  ],
];

export type Relocate = "unset" | "yes" | "no";
export type SkillRow = { skill: string; years: string };

export type ScreeningForm = Record<ListKey, string> &
  Record<NumberKey, string> & {
    current_location: string;
    willing_to_relocate: Relocate;
    remote_policy: RemotePolicy | "";
    skill_match_mode: SkillMatchMode | "";
    skill_years: SkillRow[];
  };

const numberText = (value?: number | null) =>
  value === null || value === undefined ? "" : String(value);

export function screeningToForm(profile: ScreeningProfile): ScreeningForm {
  return {
    target_roles: formatList(profile.target_roles),
    keywords_required: formatList(profile.keywords_required),
    keywords_excluded: formatList(profile.keywords_excluded),
    tech_stack: formatList(profile.tech_stack),
    company_blacklist: formatList(profile.company_blacklist),
    current_ctc: numberText(profile.current_ctc),
    expected_ctc: numberText(profile.expected_ctc),
    min_ctc: numberText(profile.min_ctc),
    notice_period_days: numberText(profile.notice_period_days),
    total_experience_years: numberText(profile.total_experience_years),
    min_match_score: numberText(profile.min_match_score),
    current_location: profile.current_location || "",
    willing_to_relocate:
      profile.willing_to_relocate === true
        ? "yes"
        : profile.willing_to_relocate === false
          ? "no"
          : "unset",
    remote_policy: profile.remote_policy || "",
    skill_match_mode: profile.skill_match_mode || "",
    skill_years: Object.entries(profile.skill_years || {}).map(
      ([skill, years]) => ({ skill, years: String(years) }),
    ),
  };
}

function sameSkillYears(a: Record<string, number>, b: Record<string, number>) {
  const keysA = Object.keys(a),
    keysB = Object.keys(b);
  return keysA.length === keysB.length && keysA.every((k) => a[k] === b[k]);
}

export function screeningPatch(
  profile: ScreeningProfile,
  form: ScreeningForm,
): { patch: ScreeningProfilePatch; changed: string[]; errors: string[] } {
  const errors: string[] = [];
  const patch: ScreeningProfilePatch = { version: profile.version };
  const changed: string[] = [];
  const set = <K extends keyof ScreeningProfilePatch>(
    key: K,
    value: ScreeningProfilePatch[K],
  ) => {
    patch[key] = value;
    changed.push(key);
  };

  for (const [key] of LIST_FIELDS) {
    const next = parseList(form[key]);
    if (!sameList(next, profile[key] || [])) set(key, next);
  }
  for (const [key, label, , rule] of NUMBER_FIELDS) {
    const text = form[key].trim();
    let value: number | null = null;
    if (text) {
      value = Number(text);
      if (!Number.isFinite(value)) {
        errors.push(`${label} must be a number.`);
        continue;
      }
      if (rule.integer && !Number.isInteger(value)) {
        errors.push(`${label} must be a whole number.`);
        continue;
      }
      if (value < rule.min || (rule.max !== undefined && value > rule.max)) {
        errors.push(
          rule.max === undefined
            ? `${label} cannot be negative.`
            : `${label} must be between ${rule.min} and ${rule.max}.`,
        );
        continue;
      }
    }
    if (value !== (profile[key] ?? null)) set(key, value);
  }
  const location = form.current_location.trim() || null;
  if (location !== (profile.current_location || null))
    set("current_location", location);
  const relocate =
    form.willing_to_relocate === "unset"
      ? null
      : form.willing_to_relocate === "yes";
  if (relocate !== (profile.willing_to_relocate ?? null))
    set("willing_to_relocate", relocate);
  const remote = form.remote_policy || null;
  if (remote !== (profile.remote_policy ?? null)) set("remote_policy", remote);
  const mode = form.skill_match_mode || null;
  if (mode !== (profile.skill_match_mode ?? null))
    set("skill_match_mode", mode);

  const skillYears: Record<string, number> = {};
  form.skill_years.forEach((row, index) => {
    const skill = row.skill.trim();
    const yearsText = row.years.trim();
    if (!skill && !yearsText) return;
    if (!skill) {
      errors.push(`Skill row ${index + 1} needs a skill name.`);
      return;
    }
    const years = Number(yearsText);
    if (!yearsText || !Number.isFinite(years) || years < 0 || years > 60) {
      errors.push(`Years for ${skill} must be a number from 0 to 60.`);
      return;
    }
    if (
      Object.keys(skillYears).some(
        (k) => k.toLowerCase() === skill.toLowerCase(),
      )
    ) {
      errors.push(`${skill} is listed more than once.`);
      return;
    }
    skillYears[skill] = years;
  });
  if (!sameSkillYears(skillYears, profile.skill_years || {}))
    set("skill_years", skillYears);
  return { patch, changed, errors };
}
