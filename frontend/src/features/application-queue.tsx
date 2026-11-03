"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Select,
} from "@/components/ui";
import { api, post, readable } from "@/lib/api";

export type QueueLimits = {
  daily_cap: number;
  max_job_age_days: number;
  applicant_limit: number | null;
  unknown_applicants: "needs_review" | "skip" | "allow_lower_bound" | "allow";
  minimum_match_score: number;
};
type Preferences = {
  roles: string[];
  locations: string[];
  experience_min: number | null;
  experience_max: number | null;
  minimum_salary: number | null;
  maximum_salary: number | null;
  salary_currency: string;
  salary_period: "year" | "month";
  excluded_companies: string[];
};
type PlatformPolicy = {
  enabled: boolean;
  sources?: (
    "approved_gmail_alerts" | "saved_verified_job" | "naukri_ui_search"
  )[];
  mode: "PREPARE_ONLY" | "SUPERVISED" | "AUTOMATIC";
  owner_submission_authorized: boolean;
  cap_mode: "global" | "custom";
  age_mode: "global" | "custom";
  applicants_mode: "global" | "custom";
  preferences_mode: "global" | "custom";
  limits: QueueLimits;
  preferences: Preferences;
  discovery_interval_seconds: number;
  supervised_submission_cap: number;
  hourly_submission_cap?: number;
  notify_telegram?: boolean;
  skill_match_mode?: "all" | "any";
};
export type QueuePolicy = {
  global_limits: QueueLimits;
  platforms: { naukri: PlatformPolicy };
  day_timezone: string;
  concurrency: 1;
  max_pending: number;
  background_only: true;
  notify_submitted: boolean;
};
export type QueueConfiguration = {
  revision: number;
  state: string;
  policy: QueuePolicy;
};
type QueueItem = {
  id: string;
  platform: string;
  requisition: string;
  title: string | null;
  company: string | null;
  location: string | null;
  stage: string;
  status: string;
  reason: string | null;
  match_score: number | null;
  created_at: string;
  posted_at: string | null;
  posted_date?: string | null;
  applicants_min: number | null;
  applicants_max: number | null;
  url?: string | null;
  packet_id?: string | null;
  submission_mode?: string | null;
  receipt_source?: string | null;
};
type QueueView = {
  items: QueueItem[];
  total: number;
  counts: Record<string, number>;
  configuration: QueueConfiguration;
  capabilities?: {
    submission: string;
    background_read: string;
    locked_screen: string;
  };
  discovery?: {
    last_cycle_count: number;
    last_finished_at: string;
    last_error: string | null;
  } | null;
  consumer?: { last_poll_at: string; busy: boolean; capability: string } | null;
  quota?: {
    reserved_today: number;
    daily_cap: number;
    remaining: number;
    hourly_cap: number;
  };
};
const words = (value: string) =>
  value
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
const stages = [
  "DISCOVERED",
  "MATCHED",
  "ELIGIBLE",
  "PREPARING",
  "READY_TO_APPLY",
  "APPLYING",
  "QUESTIONS",
  "RESUME_ATTACHMENT",
  "VERIFYING",
  "SUBMITTED_RECORDED",
  "SUBMITTED_CONFIRMED",
  "NEEDS_INPUT",
  "PAUSED",
  "FAILED_RETRYABLE",
  "FAILED_FINAL",
  "SUBMISSION_UNKNOWN",
  "SKIPPED",
];

type SyncView = {
  configuration: {
    revision: number;
    policy: {
      enabled: boolean;
      auto_profile_sync: boolean;
      profile_version: number | null;
      approved_fields: string[];
      interval_seconds: number;
    };
  };
  current_profile_version: number | null;
  profile_confirmed: boolean;
  latest: {
    outcome: string;
    observed_at: string;
    decisions: { field: string; state: string; update_supported: boolean }[];
  } | null;
  last_error: string | null;
};

export function ProfileReconciliation() {
  const query = useQuery({
    queryKey: ["naukri-profile-sync"],
    queryFn: () => api<SyncView>("execution/naukri/profile-sync"),
    refetchInterval: 15000,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (query.isPending) return <p>Loading profile reconciliation…</p>;
  if (query.error) return <ErrorState error={query.error} />;
  const view = query.data!;
  const policy = view.configuration.policy;
  const automaticCurrent =
    policy.auto_profile_sync &&
    policy.profile_version === view.current_profile_version;
  async function save(
    enabled: boolean,
    fields: string[],
    intervalSeconds = policy.interval_seconds,
  ) {
    setBusy(true);
    setError(null);
    try {
      await api("execution/naukri/profile-sync/policy", {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: view.configuration.revision,
          policy: {
            ...policy,
            enabled,
            auto_profile_sync: fields.length > 0,
            profile_version: view.current_profile_version,
            approved_fields: fields,
            interval_seconds: intervalSeconds,
          },
        }),
      });
      await query.refetch();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="stack" aria-label="Naukri profile reconciliation">
      <h2>Profile reconciliation</h2>
      <p>
        Compare supported portal fields with your confirmed profile. Unknown
        facts never replace portal information. Automatic updates support
        Profile summary and verified Key skills additions within the portal's
        available capacity. Existing skills are preserved. Other fields retain
        explicit unsupported or conflict states. Missing information appears in
        dashboard notifications; supply or correct it in your profile.
      </p>
      <Field label="Profile check interval">
        <Select
          value={String(policy.interval_seconds)}
          disabled={busy}
          onChange={(e) =>
            void save(
              policy.enabled,
              automaticCurrent ? policy.approved_fields : [],
              Number(e.target.value),
            )
          }
        >
          {![300, 900, 1800, 3600, 86400].includes(policy.interval_seconds) && (
            <option value={policy.interval_seconds}>
              {policy.interval_seconds / 60} minutes
            </option>
          )}
          <option value="300">5 minutes</option>
          <option value="900">15 minutes</option>
          <option value="1800">30 minutes</option>
          <option value="3600">1 hour</option>
          <option value="86400">1 day</option>
        </Select>
      </Field>
      <label>
        <input
          type="checkbox"
          checked={policy.enabled}
          disabled={busy || !view.profile_confirmed}
          onChange={(e) =>
            void save(
              e.target.checked,
              automaticCurrent ? policy.approved_fields : [],
            )
          }
        />{" "}
        Compare profile periodically
      </label>
      <label>
        <input
          type="checkbox"
          checked={
            automaticCurrent && policy.approved_fields.includes("summary")
          }
          disabled={busy || !view.profile_confirmed || !policy.enabled}
          onChange={(e) =>
            void save(
              policy.enabled,
              e.target.checked
                ? [
                    ...new Set([
                      ...(automaticCurrent ? policy.approved_fields : []),
                      "summary",
                    ]),
                  ]
                : policy.approved_fields.filter((field) => field !== "summary"),
            )
          }
        />{" "}
        Approve automatic Profile summary updates from confirmed profile version{" "}
        {view.current_profile_version ?? "unknown"}
      </label>
      <label>
        <input
          type="checkbox"
          checked={
            automaticCurrent && policy.approved_fields.includes("skills")
          }
          disabled={busy || !view.profile_confirmed || !policy.enabled}
          onChange={(e) =>
            void save(
              policy.enabled,
              e.target.checked
                ? [
                    ...new Set([
                      ...(automaticCurrent ? policy.approved_fields : []),
                      "skills",
                    ]),
                  ]
                : policy.approved_fields.filter((field) => field !== "skills"),
            )
          }
        />{" "}
        Approve automatic verified Key skills additions from confirmed profile
        version {view.current_profile_version ?? "unknown"}
      </label>
      {!view.profile_confirmed && (
        <Notice>
          Review and confirm the current profile before enabling
          synchronization.
        </Notice>
      )}
      {error ? <ErrorState error={error} /> : null}
      {view.last_error && <Notice>{readable(view.last_error)}</Notice>}
      <p>
        {view.latest
          ? `${readable(view.latest.outcome)} · ${new Date(view.latest.observed_at).toLocaleString()}`
          : "No portal comparison recorded."}
      </p>
      {view.latest && (
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Comparison</th>
              <th>Update support</th>
            </tr>
          </thead>
          <tbody>
            {view.latest.decisions.map((d) => (
              <tr key={d.field}>
                <td>{readable(d.field)}</td>
                <td>{readable(d.state)}</td>
                <td>
                  {d.update_supported
                    ? "Supported layout required"
                    : "Unsupported"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function QueuePolicyForm({
  configuration,
  saved,
}: {
  configuration: QueueConfiguration;
  saved: () => Promise<unknown>;
}) {
  const [policy, setPolicy] = useState<QueuePolicy>(configuration.policy);
  const [revision, setRevision] = useState(configuration.revision);
  const [persisted, setPersisted] = useState(configuration);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [roleText, setRoleText] = useState(
    configuration.policy.platforms.naukri.preferences.roles.join(", "),
  );
  const [locationText, setLocationText] = useState(
    configuration.policy.platforms.naukri.preferences.locations.join(", "),
  );
  const [excludedText, setExcludedText] = useState(
    configuration.policy.platforms.naukri.preferences.excluded_companies.join(
      ", ",
    ),
  );
  const current =
    configuration.revision > persisted.revision ? configuration : persisted;
  useEffect(() => {
    if (!dirty && current.revision >= revision) {
      setPolicy(current.policy);
      setRevision(current.revision);
      setRoleText(current.policy.platforms.naukri.preferences.roles.join(", "));
      setLocationText(
        current.policy.platforms.naukri.preferences.locations.join(", "),
      );
      setExcludedText(
        current.policy.platforms.naukri.preferences.excluded_companies.join(
          ", ",
        ),
      );
    }
  }, [current, dirty, revision]);
  const naukri = policy.platforms.naukri;
  function update(change: Partial<PlatformPolicy>) {
    setDirty(true);
    setPolicy((p) => ({
      ...p,
      platforms: {
        ...p.platforms,
        naukri: { ...p.platforms.naukri, ...change },
      },
    }));
  }
  function globalLimits(change: Partial<QueueLimits>) {
    setDirty(true);
    setPolicy((p) => ({
      ...p,
      global_limits: { ...p.global_limits, ...change },
    }));
  }
  function localLimits(change: Partial<QueueLimits>) {
    update({ limits: { ...naukri.limits, ...change } });
  }
  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      await saved();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack">
      <h2>Background job queue</h2>
      <Notice>
        Automatic mode supports eligible direct Apply journeys with verified
        account, saved resume and persistent Application Status evidence.
        Questionnaires, resume replacement and unrecognized layouts require
        review. Installed live and locked-screen acceptance is still pending.
      </Notice>
      <p>
        Persisted state: <strong>{current.state}</strong>. Background tabs only.
        One application worker; other eligible jobs continue when one needs
        input.
      </p>
      <p>
        Saving settings pauses current claims. Use Start after reviewing the
        saved policy.
      </p>
      <div className="actions">
        {(["start", "pause", "stop"] as const).map((name) => (
          <Button
            key={name}
            disabled={
              busy ||
              (name === "start" && !current.policy.platforms.naukri.enabled)
            }
            onClick={() =>
              action(async () => {
                const updated = await post<QueueConfiguration>(
                  "execution/queue/control",
                  { action: name, expected_revision: current.revision },
                );
                setPersisted(updated);
              })
            }
          >
            {name.toUpperCase()} QUEUE
          </Button>
        ))}
      </div>
      {error ? <ErrorState error={error} /> : null}
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void action(async () => {
            const updated = await api<QueueConfiguration>(
              "execution/queue/policy",
              {
                method: "PUT",
                body: JSON.stringify({
                  expected_revision: revision,
                  policy: {
                    ...policy,
                    platforms: {
                      ...policy.platforms,
                      naukri: {
                        ...naukri,
                        preferences: {
                          ...naukri.preferences,
                          roles: words(roleText),
                          locations: words(locationText),
                          excluded_companies: words(excludedText),
                        },
                      },
                    },
                  },
                }),
              },
            );
            setPersisted(updated);
            setPolicy(updated.policy);
            setRevision(updated.revision);
            setDirty(false);
          });
        }}
      >
        <fieldset className="stack">
          <legend>Global limits</legend>
          <Field label="Global maximum applications per day">
            <Input
              type="number"
              min={1}
              max={100}
              required
              value={policy.global_limits.daily_cap}
              onChange={(e) =>
                globalLimits({ daily_cap: Number(e.target.value) })
              }
            />
          </Field>
          <Field label="Global maximum posting age in days">
            <Input
              type="number"
              min={1}
              max={30}
              required
              value={policy.global_limits.max_job_age_days}
              onChange={(e) =>
                globalLimits({ max_job_age_days: Number(e.target.value) })
              }
            />
          </Field>
          <Field label="Global applicant threshold (skip at or above)">
            <Input
              type="number"
              min={1}
              max={10000000}
              value={policy.global_limits.applicant_limit ?? ""}
              onChange={(e) =>
                globalLimits({
                  applicant_limit: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
            />
          </Field>
          <Field label="Global minimum match score">
            <Input
              type="number"
              min={50}
              max={100}
              required
              value={policy.global_limits.minimum_match_score}
              onChange={(e) =>
                globalLimits({ minimum_match_score: Number(e.target.value) })
              }
            />
          </Field>
          <Field
            label="When applicant count is unknown"
            hint="A label such as 100+ can exceed your threshold. Allowing lower-bound labels explicitly accepts that uncertainty; completely missing counts still require review with that option."
          >
            <Select
              value={policy.global_limits.unknown_applicants}
              onChange={(e) =>
                globalLimits({
                  unknown_applicants: e.target
                    .value as QueueLimits["unknown_applicants"],
                })
              }
            >
              <option value="needs_review">Request review</option>
              <option value="skip">Skip</option>
              <option value="allow_lower_bound">
                Allow lower-bound labels below the threshold; review missing
                counts
              </option>
              <option value="allow">
                Allow if other eligibility checks pass
              </option>
            </Select>
          </Field>
          <p>
            Budget day: {policy.day_timezone}. Salary, CTC, location and other
            personal answers use confirmed profile facts. A preference range
            never changes those facts.
          </p>
        </fieldset>
        <fieldset className="stack">
          <legend>Naukri</legend>
          <Field label="Required skill matches">
            <Select
              value={naukri.skill_match_mode ?? "all"}
              onChange={(e) =>
                update({ skill_match_mode: e.target.value as "all" | "any" })
              }
            >
              <option value="all">Every listed skill</option>
              <option value="any">At least one verified listed skill</option>
            </Select>
          </Field>
          <p>
            Applications still use verified facts and approved answers. Missing
            skills are never added to your profile by this setting.
          </p>
          <label>
            <input
              type="checkbox"
              checked={naukri.notify_telegram ?? false}
              onChange={(e) => update({ notify_telegram: e.target.checked })}
            />{" "}
            Notify confirmed submissions through the configured Telegram owner
            channel
          </label>
          <Field label="Maximum Naukri submissions per rolling hour">
            <Input
              type="number"
              min={1}
              max={20}
              required
              value={naukri.hourly_submission_cap ?? 5}
              onChange={(e) =>
                update({ hourly_submission_cap: Number(e.target.value) })
              }
            />
          </Field>
          <fieldset>
            <legend>Naukri discovery sources</legend>
            {(
              [
                "approved_gmail_alerts",
                "saved_verified_job",
                "naukri_ui_search",
              ] as const
            ).map((source) => (
              <label className="check" key={source}>
                <input
                  type="checkbox"
                  checked={(
                    naukri.sources ?? [
                      "approved_gmail_alerts",
                      "saved_verified_job",
                      "naukri_ui_search",
                    ]
                  ).includes(source)}
                  onChange={(e) => {
                    const selected = naukri.sources ?? [
                      "approved_gmail_alerts",
                      "saved_verified_job",
                      "naukri_ui_search",
                    ];
                    update({
                      sources: e.target.checked
                        ? [...selected, source]
                        : selected.filter((s) => s !== source),
                    });
                  }}
                />
                {readable(source)}
              </label>
            ))}
            <p>
              Gmail uses the existing approved local alert source. This setting
              adds no mailbox access.
            </p>
          </fieldset>
          <label className="check">
            <input
              type="checkbox"
              checked={naukri.enabled}
              onChange={(e) => update({ enabled: e.target.checked })}
            />{" "}
            Enable Naukri automation
          </label>
          <Field label="Naukri execution mode">
            <Select
              value={naukri.mode}
              onChange={(e) =>
                update({ mode: e.target.value as PlatformPolicy["mode"] })
              }
            >
              <option value="PREPARE_ONLY">Prepare only</option>
              <option value="SUPERVISED">Supervised validation</option>
              <option value="AUTOMATIC">Automatic</option>
            </Select>
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={naukri.owner_submission_authorized}
              onChange={(e) =>
                update({ owner_submission_authorized: e.target.checked })
              }
            />{" "}
            Authorize eligible Naukri applications using my confirmed profile
            and canonical resume within this policy
          </label>
          <Field label="Naukri daily cap source">
            <Select
              value={naukri.cap_mode}
              onChange={(e) =>
                update({
                  cap_mode: e.target.value as PlatformPolicy["cap_mode"],
                })
              }
            >
              <option value="global">Global limit</option>
              <option value="custom">Custom Naukri limit</option>
            </Select>
          </Field>
          {naukri.cap_mode === "custom" && (
            <Field label="Naukri maximum applications per day">
              <Input
                type="number"
                min={1}
                max={100}
                required
                value={naukri.limits.daily_cap}
                onChange={(e) =>
                  localLimits({ daily_cap: Number(e.target.value) })
                }
              />
            </Field>
          )}
          <Field label="Naukri posting age source">
            <Select
              value={naukri.age_mode}
              onChange={(e) =>
                update({
                  age_mode: e.target.value as PlatformPolicy["age_mode"],
                })
              }
            >
              <option value="global">Global age limit</option>
              <option value="custom">Custom Naukri age</option>
            </Select>
          </Field>
          {naukri.age_mode === "custom" && (
            <Field label="Naukri maximum posting age in days">
              <Input
                type="number"
                min={1}
                max={30}
                required
                value={naukri.limits.max_job_age_days}
                onChange={(e) =>
                  localLimits({ max_job_age_days: Number(e.target.value) })
                }
              />
            </Field>
          )}
          <Field label="Naukri applicant threshold source">
            <Select
              value={naukri.applicants_mode}
              onChange={(e) =>
                update({
                  applicants_mode: e.target
                    .value as PlatformPolicy["applicants_mode"],
                })
              }
            >
              <option value="global">Global threshold</option>
              <option value="custom">Custom Naukri threshold</option>
            </Select>
          </Field>
          {naukri.applicants_mode === "custom" && (
            <>
              <Field label="Naukri applicant threshold (skip at or above)">
                <Input
                  type="number"
                  min={1}
                  max={10000000}
                  value={naukri.limits.applicant_limit ?? ""}
                  onChange={(e) =>
                    localLimits({
                      applicant_limit: e.target.value
                        ? Number(e.target.value)
                        : null,
                    })
                  }
                />
              </Field>
              <Field
                label="Naukri unknown applicant count"
                hint="Lower-bound labels can exceed your threshold. That option accepts the risk while keeping completely missing counts for review."
              >
                <Select
                  value={naukri.limits.unknown_applicants}
                  onChange={(e) =>
                    localLimits({
                      unknown_applicants: e.target
                        .value as QueueLimits["unknown_applicants"],
                    })
                  }
                >
                  <option value="needs_review">Request review</option>
                  <option value="skip">Skip</option>
                  <option value="allow_lower_bound">
                    Allow lower-bound labels below the threshold; review missing
                    counts
                  </option>
                  <option value="allow">Allow if other checks pass</option>
                </Select>
              </Field>
            </>
          )}
          <Field label="Naukri job preferences">
            <Select
              value={naukri.preferences_mode}
              onChange={(e) =>
                update({
                  preferences_mode: e.target
                    .value as PlatformPolicy["preferences_mode"],
                })
              }
            >
              <option value="global">Use global profile preferences</option>
              <option value="custom">Custom Naukri preferences</option>
            </Select>
          </Field>
          {naukri.preferences_mode === "custom" && (
            <>
              <Field label="Naukri job titles">
                <Input
                  value={roleText}
                  onChange={(e) => {
                    setDirty(true);
                    setRoleText(e.target.value);
                  }}
                />
              </Field>
              <Field label="Naukri locations">
                <Input
                  value={locationText}
                  onChange={(e) => {
                    setDirty(true);
                    setLocationText(e.target.value);
                  }}
                />
              </Field>
              <Field label="Minimum advertised experience years">
                <Input
                  type="number"
                  min={0}
                  max={60}
                  step={0.5}
                  value={naukri.preferences.experience_min ?? ""}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        experience_min: e.target.value
                          ? Number(e.target.value)
                          : null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="Maximum advertised experience years">
                <Input
                  type="number"
                  min={0}
                  max={60}
                  step={0.5}
                  value={naukri.preferences.experience_max ?? ""}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        experience_max: e.target.value
                          ? Number(e.target.value)
                          : null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="Minimum advertised salary">
                <Input
                  type="number"
                  min={0}
                  value={naukri.preferences.minimum_salary ?? ""}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        minimum_salary: e.target.value
                          ? Number(e.target.value)
                          : null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="Maximum advertised salary">
                <Input
                  type="number"
                  min={0}
                  value={naukri.preferences.maximum_salary ?? ""}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        maximum_salary: e.target.value
                          ? Number(e.target.value)
                          : null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="Salary currency">
                <Input
                  maxLength={3}
                  value={naukri.preferences.salary_currency}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        salary_currency: e.target.value.toUpperCase(),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Salary period">
                <Select
                  value={naukri.preferences.salary_period}
                  onChange={(e) =>
                    update({
                      preferences: {
                        ...naukri.preferences,
                        salary_period: e.target.value as "year" | "month",
                      },
                    })
                  }
                >
                  <option value="year">Annual</option>
                  <option value="month">Monthly</option>
                </Select>
              </Field>
              <Field label="Excluded companies">
                <Input
                  value={excludedText}
                  onChange={(e) => {
                    setDirty(true);
                    setExcludedText(e.target.value);
                  }}
                />
              </Field>
            </>
          )}
          <Field label="Naukri discovery interval in seconds">
            <Input
              type="number"
              min={60}
              max={86400}
              required
              value={naukri.discovery_interval_seconds}
              onChange={(e) =>
                update({ discovery_interval_seconds: Number(e.target.value) })
              }
            />
          </Field>
        </fieldset>
        {dirty && revision < current.revision && (
          <Notice>
            Settings changed in another session. Reload them before saving.
          </Notice>
        )}
        <Button
          type="submit"
          disabled={busy || (dirty && revision < current.revision)}
        >
          Save queue policy
        </Button>
      </form>
    </div>
  );
}

export function ApplicationQueue() {
  const client = useQueryClient();
  const [stage, setStage] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [location, setLocation] = useState("");
  const [minimumScore, setMinimumScore] = useState("");
  const [appliedLocation, setAppliedLocation] = useState("");
  const [appliedScore, setAppliedScore] = useState("");
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({
    platform: "naukri",
    limit: "100",
    offset: String(offset),
  });
  if (stage) query.set("stage", stage);
  if (appliedSearch.trim()) query.set("search", appliedSearch.trim());
  if (appliedLocation.trim()) query.set("location", appliedLocation.trim());
  if (appliedScore !== "") query.set("minimum_score", appliedScore);
  const queue = useQuery({
    queryKey: [
      "application-queue",
      stage,
      appliedSearch,
      appliedLocation,
      appliedScore,
      offset,
    ],
    queryFn: () => api<QueueView>("execution/queue?" + query),
    refetchInterval: 10000,
  });
  if (queue.isPending) return <p>Loading background job queue…</p>;
  if (queue.isError) return <ErrorState error={queue.error} />;
  const count = (states: string[]) =>
    states.reduce((sum, state) => sum + (queue.data.counts[state] ?? 0), 0);
  return (
    <section
      className="panel panel-body stack"
      aria-label="Background application queue"
    >
      <QueuePolicyForm
        configuration={queue.data.configuration}
        saved={() =>
          client.invalidateQueries({ queryKey: ["application-queue"] })
        }
      />
      <ProfileReconciliation />
      <section aria-label="Discovery and application progress">
        <h3>Discovery worker</h3>
        <p>
          {count(["DISCOVERED"])} jobs awaiting listing checks. Discovery checks
          your filters and skips duplicate jobs before eligible work advances.
        </p>
        <h3>Application worker</h3>
        <p>
          {count(["ELIGIBLE"])} eligible jobs awaiting preparation ·{" "}
          {count([
            "PREPARING",
            "READY_TO_APPLY",
            "APPLYING",
            "QUESTIONS",
            "RESUME_ATTACHMENT",
            "VERIFYING",
          ])}{" "}
          application jobs in progress · {count(["SUBMITTED_CONFIRMED"])} new
          submissions confirmed · {count(["SUBMITTED_RECORDED"])} previously
          recorded applications.
        </p>
        <p>
          Discovered, skipped and held jobs remain in history. They are not
          submitted applications. Submission is counted only after receipt
          verification.
        </p>
      </section>
      <h3>Queue and application history</h3>
      {queue.data.quota && (
        <p>
          {queue.data.quota.reserved_today} reserved today ·{" "}
          {queue.data.quota.remaining} remaining of {queue.data.quota.daily_cap}{" "}
          · {queue.data.quota.hourly_cap} per rolling hour. Uncertain attempts
          retain their reservation.
        </p>
      )}
      <p>
        {queue.data.consumer?.last_poll_at
          ? `Background browser last checked in: ${new Date(queue.data.consumer.last_poll_at).toLocaleString()}.`
          : "Background browser has not checked in for this queue. The selected profile needs the matching extension release and Naukri website access."}
      </p>
      {queue.data.capabilities?.submission === "executor_pending" && (
        <Notice>
          Background discovery and preparation are available in this source
          candidate. Automatic submission is still being implemented and has not
          passed live acceptance.
        </Notice>
      )}
      {queue.data.discovery && (
        <p>
          Last browser discovery cycle:{" "}
          {queue.data.discovery.last_cycle_count ?? 0} candidate links.{" "}
          {queue.data.discovery.last_error
            ? readable(queue.data.discovery.last_error)
            : ""}
        </p>
      )}
      <p>
        {Object.entries(queue.data.counts)
          .map(([state, count]) => `${readable(state)}: ${count}`)
          .join(" · ") || "No recorded jobs yet."}
      </p>
      <Field label="Queue platform">
        <Select value="naukri" onChange={() => {}}>
          <option value="naukri">Naukri</option>
        </Select>
      </Field>
      <Field label="Queue status filter">
        <Select
          value={stage}
          onChange={(e) => {
            setStage(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All stages</option>
          {stages.map((s) => (
            <option key={s} value={s}>
              {readable(s)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Search role, employer or requisition">
        <Input
          value={search}
          maxLength={200}
          onChange={(e) => setSearch(e.target.value)}
        />
      </Field>
      <Field label="Queue location filter">
        <Input
          value={location}
          maxLength={200}
          onChange={(e) => setLocation(e.target.value)}
        />
      </Field>
      <Field label="Queue minimum match score filter">
        <Input
          type="number"
          min={0}
          max={100}
          value={minimumScore}
          onChange={(e) => setMinimumScore(e.target.value)}
        />
      </Field>
      <Button
        onClick={() => {
          setAppliedSearch(search);
          setAppliedLocation(location);
          setAppliedScore(minimumScore);
          setOffset(0);
        }}
      >
        Filter jobs
      </Button>
      <p>
        {queue.data.total} matching records. Showing{" "}
        {offset + (queue.data.items.length ? 1 : 0)}–
        {offset + queue.data.items.length}. Applicant ranges remain ranges;
        unknown values require the configured policy.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Employer</th>
              <th>Location</th>
              <th>Stage</th>
              <th>Match</th>
              <th>Applicants</th>
              <th>Posting date</th>
              <th>Reason</th>
              <th>Mode / receipt</th>
            </tr>
          </thead>
          <tbody>
            {queue.data.items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.title || item.requisition}
                    </a>
                  ) : (
                    item.title || item.requisition
                  )}
                </td>
                <td>{item.company || "Unverified"}</td>
                <td>{item.location || "Unknown"}</td>
                <td>{readable(item.stage)}</td>
                <td>{item.match_score ?? "Unknown"}</td>
                <td>
                  {item.applicants_min === null
                    ? "Unknown"
                    : item.applicants_min === item.applicants_max
                      ? item.applicants_min
                      : item.applicants_max === null
                        ? `${item.applicants_min}+`
                        : `${item.applicants_min}–${item.applicants_max}`}
                </td>
                <td>
                  {item.posted_at
                    ? new Date(item.posted_at).toLocaleString()
                    : item.posted_date
                      ? `${item.posted_date} (time unknown)`
                      : "Unknown"}
                </td>
                <td>{readable(item.reason)}</td>
                <td>
                  {readable(item.submission_mode)} ·{" "}
                  {readable(item.receipt_source)}{" "}
                  {item.packet_id && (
                    <a href={`/applications/${item.packet_id}`}>
                      View application
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!queue.data.items.length && <p>No jobs match these filters.</p>}
      <div className="actions">
        <Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 100))}
        >
          Previous jobs
        </Button>
        <Button
          disabled={offset + 100 >= queue.data.total}
          onClick={() => setOffset(offset + 100)}
        >
          Next jobs
        </Button>
      </div>
    </section>
  );
}
