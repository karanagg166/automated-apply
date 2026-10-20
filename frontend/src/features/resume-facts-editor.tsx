"use client";
import { useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { ProjectsEditor } from "@/components/projects-editor";
import type { Schema } from "@/lib/api";

type Profile = Schema<"CandidateProfileCreate">;
export function ResumeFactsEditor({
  value,
  onChange,
}: {
  value: Profile;
  onChange: (value: Profile) => void;
}) {
  const patch = (changes: Partial<Profile>) =>
    onChange({ ...value, ...changes });
  const [skills, setSkills] = useState(value.verified_skills?.join(", ") || "");
  const roles = value.verified_roles || [],
    education = value.education || [];
  return (
    <div className="stack">
      <h3>Facts to save after approval</h3>
      <p>
        Existing facts are preserved below. Review suggestions against the PDF
        and edit any material changes, including dates. No field is verified by
        extraction alone.
      </p>
      <div className="form-grid">
        <Field label="Reviewed full name">
          <Input
            required
            maxLength={200}
            value={value.full_name}
            onChange={(e) => patch({ full_name: e.target.value })}
          />
        </Field>
        <Field label="Reviewed email">
          <Input
            required
            type="email"
            maxLength={254}
            value={value.email}
            onChange={(e) => patch({ email: e.target.value })}
          />
        </Field>
        <Field
          label="Reviewed skills"
          hint="Comma-separated. Existing confirmed skills are retained."
        >
          <Input
            value={skills}
            onChange={(e) => {
              setSkills(e.target.value);
              patch({
                verified_skills: e.target.value
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
              });
            }}
          />
        </Field>
        {(
          [
            ["github_url", "GitHub"],
            ["linkedin_url", "LinkedIn"],
            ["portfolio_url", "Portfolio"],
            ["personal_website", "Personal website"],
          ] as const
        ).map(([key, label]) => (
          <Field label={`Reviewed ${label} URL`} key={key}>
            <Input
              type="url"
              value={value[key] || ""}
              onChange={(e) => patch({ [key]: e.target.value || null })}
            />
          </Field>
        ))}
      </div>
      <Field label="Reviewed professional summary">
        <textarea
          className="input"
          maxLength={4000}
          value={value.summary || ""}
          onChange={(e) => patch({ summary: e.target.value || null })}
        />
      </Field>
      <h3>Work experience and employment dates</h3>
      {roles.map((role, i) => (
        <div className="evidence-item stack" key={i}>
          <div className="form-grid">
            {(
              [
                ["company", "Company"],
                ["role", "Role"],
                ["start_date", "Start date"],
                ["end_date", "End date"],
              ] as const
            ).map(([key, label]) => (
              <Field key={key} label={`Experience ${i + 1} ${label}`}>
                <Input
                  type={key.endsWith("date") ? "date" : "text"}
                  required={!key.endsWith("date")}
                  value={role[key] || ""}
                  onChange={(e) =>
                    patch({
                      verified_roles: roles.map((r, n) =>
                        n === i ? { ...r, [key]: e.target.value || null } : r,
                      ),
                    })
                  }
                />
              </Field>
            ))}
          </div>
          <Field label={`Experience ${i + 1} contribution`}>
            <textarea
              className="input"
              maxLength={4000}
              value={role.highlight || ""}
              onChange={(e) =>
                patch({
                  verified_roles: roles.map((r, n) =>
                    n === i ? { ...r, highlight: e.target.value || null } : r,
                  ),
                })
              }
            />
          </Field>
          <Button
            type="button"
            onClick={() =>
              patch({ verified_roles: roles.filter((_, n) => n !== i) })
            }
          >
            Remove experience {i + 1}
          </Button>
        </div>
      ))}
      <Button
        type="button"
        onClick={() =>
          patch({ verified_roles: [...roles, { company: "", role: "" }] })
        }
      >
        Add reviewed experience
      </Button>
      <h3>Education</h3>
      {education.map((entry, i) => (
        <div className="evidence-item stack" key={i}>
          <div className="form-grid">
            {(
              [
                ["institution", "Institution"],
                ["qualification", "Qualification"],
                ["field_of_study", "Field of study"],
              ] as const
            ).map(([key, label]) => (
              <Field key={key} label={`Education ${i + 1} ${label}`}>
                <Input
                  required={key !== "field_of_study"}
                  value={entry[key] || ""}
                  onChange={(e) =>
                    patch({
                      education: education.map((r, n) =>
                        n === i ? { ...r, [key]: e.target.value || null } : r,
                      ),
                    })
                  }
                />
              </Field>
            ))}
            <Field label={`Education ${i + 1} graduation year`}>
              <Input
                type="number"
                min={1900}
                max={2200}
                value={entry.graduation_year || ""}
                onChange={(e) =>
                  patch({
                    education: education.map((r, n) =>
                      n === i
                        ? {
                            ...r,
                            graduation_year: e.target.value
                              ? Number(e.target.value)
                              : null,
                          }
                        : r,
                    ),
                  })
                }
              />
            </Field>
          </div>
          <Button
            type="button"
            onClick={() =>
              patch({ education: education.filter((_, n) => n !== i) })
            }
          >
            Remove education {i + 1}
          </Button>
        </div>
      ))}
      <Button
        type="button"
        onClick={() =>
          patch({
            education: [...education, { institution: "", qualification: "" }],
          })
        }
      >
        Add reviewed education
      </Button>
      <ProjectsEditor
        value={JSON.stringify(value.projects || [])}
        onChange={(v) => patch({ projects: JSON.parse(v) })}
      />
    </div>
  );
}
