"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, patch } from "@/lib/api";
import {
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Select,
  Skeleton,
} from "@/components/ui";
import {
  LIST_FIELDS,
  NUMBER_FIELDS,
  REMOTE_POLICIES,
  SKILL_MATCH_MODES,
  saveErrorMessage,
  screeningPatch,
  screeningToForm,
  type Relocate,
  type RemotePolicy,
  type ScreeningForm,
  type ScreeningProfile,
  type SkillMatchMode,
  type SkillRow,
} from "@/features/autopilot-forms";

export const SCREENING_KEY = ["v2-screening-profile"] as const;

type Feedback = { tone: "ok" | "error"; text: string } | null;

function SkillYearsEditor({
  rows,
  onChange,
}: {
  rows: SkillRow[];
  onChange: (rows: SkillRow[]) => void;
}) {
  const edit = (index: number, next: Partial<SkillRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...next } : row)));
  return (
    <fieldset className="skill-years">
      <legend>Years of experience per skill</legend>
      <small className="muted">
        Used to answer “How many years of X?” questions. Skills not listed here
        are asked to you, never estimated.
      </small>
      {rows.length === 0 && (
        <p className="muted small-print">No skills recorded yet.</p>
      )}
      {rows.map((row, index) => {
        const name = row.skill.trim() || `skill ${index + 1}`;
        return (
          <div className="skill-row" key={index}>
            <Input
              aria-label={`Skill ${index + 1} name`}
              placeholder="Skill, e.g. Python"
              value={row.skill}
              onChange={(e) => edit(index, { skill: e.target.value })}
            />
            <Input
              aria-label={`Years of ${name}`}
              type="number"
              inputMode="decimal"
              min={0}
              max={60}
              step={0.5}
              placeholder="Years"
              value={row.years}
              onChange={(e) => edit(index, { years: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              aria-label={`Remove ${name}`}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              Remove
            </Button>
          </div>
        );
      })}
      <div>
        <Button
          type="button"
          onClick={() => onChange([...rows, { skill: "", years: "" }])}
        >
          Add skill
        </Button>
      </div>
    </fieldset>
  );
}

function ScreeningFields({ profile }: { profile: ScreeningProfile }) {
  const client = useQueryClient();
  const [base, setBase] = useState(profile);
  const [form, setForm] = useState(() => screeningToForm(profile));
  const [feedback, setFeedback] = useState<Feedback>(null);
  if (base.version !== profile.version) {
    setBase(profile);
    setForm(screeningToForm(profile));
  }
  const { patch: body, changed, errors } = screeningPatch(profile, form);
  const save = useMutation({
    mutationFn: () => patch<ScreeningProfile>("v2/screening-profile", body),
    onSuccess: (updated) => {
      client.setQueryData(SCREENING_KEY, updated);
      setFeedback({
        tone: "ok",
        text: `Saved ${changed.length} change${changed.length === 1 ? "" : "s"} (version ${updated.version}). The worker uses them on its next cycle.`,
      });
    },
    onError: (error) => {
      setFeedback({ tone: "error", text: saveErrorMessage(error) });
      if (error instanceof ApiError && [404, 409].includes(error.status))
        client.invalidateQueries({ queryKey: SCREENING_KEY });
    },
  });
  const update = <K extends keyof ScreeningForm>(
    key: K,
    value: ScreeningForm[K],
  ) => {
    setFeedback(null);
    setForm((current) => ({ ...current, [key]: value }));
  };
  return (
    <form
      className="panel-body stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (!changed.length || errors.length) return;
        setFeedback(null);
        save.mutate();
      }}
    >
      <h3>Screening facts</h3>
      <div className="form-grid">
        {NUMBER_FIELDS.map(([key, label, hint, rule]) => (
          <Field key={key} label={label} hint={`${hint} Leave empty if unset.`}>
            <Input
              type="number"
              inputMode={rule.integer ? "numeric" : "decimal"}
              min={rule.min}
              max={rule.max}
              step={rule.integer ? 1 : "any"}
              value={form[key]}
              onChange={(e) => update(key, e.target.value)}
            />
          </Field>
        ))}
        <Field label="Current location" hint="City, e.g. Bengaluru.">
          <Input
            value={form.current_location}
            autoComplete="address-level2"
            onChange={(e) => update("current_location", e.target.value)}
          />
        </Field>
        <Field
          label="Country"
          hint="Answers “Country” questions (e.g. India). Empty = derived from your city or +91 phone."
        >
          <Input
            value={form.country}
            autoComplete="country-name"
            onChange={(e) => update("country", e.target.value)}
          />
        </Field>
        <Field
          label="Current company"
          hint="Answers “Current company” questions. Empty = asked to you."
        >
          <Input
            value={form.current_company}
            autoComplete="organization"
            onChange={(e) => update("current_company", e.target.value)}
          />
        </Field>
        <Field
          label="English proficiency"
          hint="For example Fluent or Professional. Empty = asked to you."
        >
          <Input
            value={form.english_proficiency}
            onChange={(e) => update("english_proficiency", e.target.value)}
          />
        </Field>
        <Field
          label="Willing to relocate"
          hint="“Not set” means relocation questions are asked to you."
        >
          <Select
            value={form.willing_to_relocate}
            onChange={(e) =>
              update("willing_to_relocate", e.target.value as Relocate)
            }
          >
            <option value="unset">Not set</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </Select>
        </Field>
      </div>
      <h3>Job preferences</h3>
      <div className="form-grid">
        <Field label="Work arrangement">
          <Select
            value={form.remote_policy}
            onChange={(e) =>
              update("remote_policy", e.target.value as RemotePolicy | "")
            }
          >
            <option value="">Not set</option>
            {REMOTE_POLICIES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Skill matching">
          <Select
            value={form.skill_match_mode}
            onChange={(e) =>
              update("skill_match_mode", e.target.value as SkillMatchMode | "")
            }
          >
            <option value="">Not set</option>
            {SKILL_MATCH_MODES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        {LIST_FIELDS.map(([key, label, hint]) => (
          <Field key={key} label={label} hint={`${hint} Comma separated.`}>
            <Input
              value={form[key]}
              onChange={(e) => update(key, e.target.value)}
            />
          </Field>
        ))}
      </div>
      <SkillYearsEditor
        rows={form.skill_years}
        onChange={(rows) => update("skill_years", rows)}
      />
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
          Save screening facts
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={!changed.length || save.isPending}
          onClick={() => {
            setFeedback(null);
            setForm(screeningToForm(profile));
          }}
        >
          Discard changes
        </Button>
        <span className="muted small-print">
          {changed.length
            ? `${changed.length} unsaved change${changed.length === 1 ? "" : "s"}`
            : "No unsaved changes"}{" "}
          · Version {profile.version}
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
  );
}

export function ScreeningProfileEditor() {
  const profile = useQuery({
    queryKey: SCREENING_KEY,
    queryFn: () => api<ScreeningProfile>("v2/screening-profile"),
  });
  return (
    <section className="panel spaced" aria-labelledby="screening-heading">
      <div className="panel-header">
        <div>
          <h2 id="screening-heading">Screening facts &amp; preferences</h2>
          <p>
            Answers the worker may give deterministically, and the filters it
            scores jobs with.
          </p>
        </div>
      </div>
      <div className="panel-body">
        <Notice>
          Only facts saved here (or answers you confirmed earlier) are used. Any
          question that is not covered — or is below the confidence threshold —
          pauses only that job and is sent to you on Telegram. It is never
          guessed.
        </Notice>
      </div>
      {profile.isPending ? (
        <div className="panel-body">
          <Skeleton />
        </div>
      ) : profile.isError ? (
        <div className="panel-body">
          {profile.error instanceof ApiError && profile.error.status === 404 ? (
            <NoProfile />
          ) : (
            <ErrorState error={profile.error} retry={() => profile.refetch()} />
          )}
        </div>
      ) : !profile.data.has_profile ? (
        <div className="panel-body">
          <NoProfile />
        </div>
      ) : (
        <ScreeningFields profile={profile.data} />
      )}
    </section>
  );
}

function NoProfile() {
  return (
    <div className="notice warn" role="status">
      No candidate profile exists yet, so there is nothing to screen with.{" "}
      <Link href="/profile">Create your profile</Link> first; these fields
      appear once it is saved.
    </div>
  );
}
