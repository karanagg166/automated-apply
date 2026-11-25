import { describe, expect, it } from "vitest";
import {
  ageLabel,
  authTone,
  parseList,
  quotaPercent,
  rulesPatch,
  rulesToForm,
  screeningPatch,
  screeningToForm,
  stateTone,
  type PortalRules,
  type ScreeningProfile,
} from "@/features/autopilot-forms";
import { applicationsPath } from "@/features/autopilot-log";
import { permittedRoute } from "@/lib/gateway";

const rules: PortalRules = {
  platform: "naukri",
  enabled: true,
  auto_apply_enabled: false,
  max_applies_per_day: 50,
  max_applies_per_hour: 10,
  max_job_age_days: 7,
  max_applicants: 300,
  unknown_applicants_policy: "allow_lower_bound",
  min_delay_sec: 45,
  max_delay_sec: 150,
  active_hours_start: "08:00:00",
  active_hours_end: "23:30",
  timezone: "Asia/Kolkata",
  auth_status: "OK",
  revision: 4,
};

const profile: ScreeningProfile = {
  target_roles: ["Backend Engineer"],
  keywords_required: [],
  keywords_excluded: ["sales"],
  tech_stack: ["Python", "FastAPI"],
  company_blacklist: [],
  remote_policy: null,
  skill_match_mode: "any",
  min_match_score: 70,
  current_ctc: 6.5,
  expected_ctc: null,
  min_ctc: null,
  notice_period_days: 30,
  total_experience_years: 1.5,
  current_location: "Bengaluru",
  willing_to_relocate: null,
  skill_years: { Python: 2 },
  version: 9,
  has_profile: true,
};

describe("portal rules patch", () => {
  it("sends only revision when nothing changed (seconds in times ignored)", () => {
    const result = rulesPatch(rules, rulesToForm(rules));
    expect(result).toEqual({ patch: { revision: 4 }, changed: [], errors: [] });
  });

  it("sends only changed fields with the current revision", () => {
    const form = {
      ...rulesToForm(rules),
      auto_apply_enabled: true,
      max_applies_per_day: "40",
      active_hours_end: "",
      timezone: " UTC ",
    };
    const { patch, changed, errors } = rulesPatch(rules, form);
    expect(errors).toEqual([]);
    expect(patch).toEqual({
      revision: 4,
      auto_apply_enabled: true,
      max_applies_per_day: 40,
      active_hours_end: null,
      timezone: "UTC",
    });
    expect(changed).toHaveLength(4);
  });

  it("reports the same bounds the backend enforces", () => {
    const { errors } = rulesPatch(rules, {
      ...rulesToForm(rules),
      max_applies_per_day: "5",
      max_applies_per_hour: "6",
      min_delay_sec: "4",
      max_delay_sec: "3",
      max_job_age_days: "1.5",
      active_hours_start: "25:00",
      timezone: "",
    });
    expect(errors).toEqual([
      "Maximum job age must be a whole number.",
      "Minimum delay must be at least 5.",
      "Maximum delay must be at least 5.",
      "Hourly cap cannot exceed the daily cap.",
      "Maximum delay must be at least the minimum delay.",
      "Active hours start must use HH:MM.",
      "Timezone is required (for example Asia/Kolkata).",
    ]);
  });
});

describe("screening profile patch", () => {
  it("round-trips without changes", () => {
    expect(screeningPatch(profile, screeningToForm(profile))).toEqual({
      patch: { version: 9 },
      changed: [],
      errors: [],
    });
  });

  it("diffs lists, numbers, tri-state relocation and skill years", () => {
    const form = {
      ...screeningToForm(profile),
      tech_stack: "Python, FastAPI, postgres, python",
      expected_ctc: "12",
      current_ctc: "",
      willing_to_relocate: "no" as const,
      remote_policy: "remote_only" as const,
      skill_years: [
        { skill: "Python", years: "2" },
        { skill: "FastAPI", years: "1" },
        { skill: "", years: "" },
      ],
    };
    const { patch, errors } = screeningPatch(profile, form);
    expect(errors).toEqual([]);
    expect(patch).toEqual({
      version: 9,
      tech_stack: ["Python", "FastAPI", "postgres"],
      current_ctc: null,
      expected_ctc: 12,
      willing_to_relocate: false,
      remote_policy: "remote_only",
      skill_years: { Python: 2, FastAPI: 1 },
    });
  });

  it("can clear relocation back to unset and rejects bad rows", () => {
    const { patch, errors } = screeningPatch(
      { ...profile, willing_to_relocate: true },
      {
        ...screeningToForm(profile),
        notice_period_days: "15.5",
        min_match_score: "120",
        skill_years: [
          { skill: "Go", years: "-1" },
          { skill: "", years: "3" },
          { skill: "python", years: "1" },
          { skill: "Python", years: "1" },
        ],
      },
    );
    expect(patch.willing_to_relocate).toBeNull();
    expect(errors).toEqual([
      "Notice period (days) must be a whole number.",
      "Minimum match score must be between 0 and 100.",
      "Years for Go must be a number from 0 to 60.",
      "Skill row 2 needs a skill name.",
      "Python is listed more than once.",
    ]);
  });
});

describe("display helpers", () => {
  it("parses comma and newline lists without duplicates", () => {
    expect(parseList(" a, b\nB ,, c ")).toEqual(["a", "b", "c"]);
  });

  it("maps states and auth to badge tones", () => {
    expect(stateTone("APPLIED")).toBe("green");
    expect(stateTone("FILTERED_OUT")).toBe("neutral");
    expect(stateTone("WAITING_FOR_USER")).toBe("amber");
    expect(stateTone("QUOTA_HIT_PENDING")).toBe("amber");
    expect(stateTone("FAILED")).toBe("red");
    expect(stateTone("SUBMISSION_UNKNOWN")).toBe("red");
    expect(authTone("OK")).toBe("green");
    expect(authTone("AUTH_REQUIRED")).toBe("red");
    expect(authTone("UNKNOWN")).toBe("neutral");
  });

  it("clamps quotas and labels heartbeat age", () => {
    expect(quotaPercent(5, 10)).toBe(50);
    expect(quotaPercent(12, 10)).toBe(100);
    expect(quotaPercent(0, 0)).toBe(0);
    expect(ageLabel(null)).toBe("No heartbeat yet");
    expect(ageLabel(42)).toBe("42s ago");
    expect(ageLabel(125)).toBe("2m 5s ago");
    expect(ageLabel(7260)).toBe("2h 1m ago");
  });

  it("builds application paths the gateway permits", () => {
    expect(applicationsPath("", "")).toBe("v2/applications?limit=50");
    const filtered = applicationsPath("naukri", "FAILED");
    expect(filtered).toBe(
      "v2/applications?limit=50&platform=naukri&state=FAILED",
    );
    expect(permittedRoute("v2/applications", "GET")).toBe(true);
    expect(permittedRoute("v2/portal-rules/naukri", "PATCH")).toBe(true);
    expect(permittedRoute("v2/screening-profile", "PATCH")).toBe(true);
    expect(permittedRoute("v2/worker/run-once", "POST")).toBe(true);
  });
});
