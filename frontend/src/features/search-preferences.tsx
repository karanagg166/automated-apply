"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schema } from "@/lib/api";
import { Button, ErrorState, Input, Select } from "@/components/ui";
type Preferences = Schema<"SearchPreferences-Output">;

export function SearchPreferencesEditor() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["search-preferences"],
    queryFn: () => api<Preferences>("local-agent/search-preferences"),
  });
  const [draft, setDraft] = useState<Preferences | null>(null);
  const value = draft || query.data;
  const save = useMutation({
    mutationFn: (data: Preferences) =>
      api("local-agent/search-preferences", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["search-preferences"] });
      setDraft(null);
    },
  });
  const lists = [
    ["target_titles", "Job titles"],
    ["technology_stacks", "Technical skills"],
    ["preferred_locations", "Preferred locations"],
    ["target_industries", "Company categories"],
    ["company_stages", "Company stages"],
    ["source_platforms", "Source platforms"],
    ["excluded_companies", "Blocked companies"],
  ] as const;
  const ranges = [
    ["minimum_experience", "Minimum experience (years)"],
    ["maximum_experience", "Maximum experience (years)"],
    ["minimum_salary", "Minimum salary"],
    ["maximum_salary", "Maximum salary"],
    ["minimum_employees", "Minimum employees"],
    ["maximum_employees", "Maximum employees"],
    ["posting_recency_days", "Posting recency (days)"],
    ["relevance_threshold", "Relevance threshold (0–100)"],
  ] as const;
  return (
    <section className="panel" aria-label="Saved job search preferences">
      <div className="panel-header">
        <h2>Saved job search preferences</h2>
      </div>
      <div className="panel-body stack">
        <p>
          These filters control discovery searches. For applications, edit
          company preferences in your profile and posting age, applicant counts
          and match score in the application queue. Saving here does not change
          application rules or start discovery. Missing job properties remain
          unknown.
        </p>
        {query.isError && <ErrorState error={query.error} />}
        {value && (
          <details>
            <summary>Edit saved filters</summary>
            <div className="stack">
              {lists.map(([key, label]) => (
                <label key={key}>
                  {label}
                  <Input
                    aria-label={label}
                    value={(value[key] || []).join(", ")}
                    onChange={(event) =>
                      setDraft({
                        ...value,
                        [key]: event.target.value
                          .split(",")
                          .map((entry) => entry.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </label>
              ))}
              {ranges.map(([key, label]) => (
                <label key={key}>
                  {label}
                  <Input
                    aria-label={label}
                    type="number"
                    min="0"
                    step={key.includes("experience") ? "0.5" : "1"}
                    value={value[key] ?? ""}
                    onChange={(event) =>
                      setDraft({
                        ...value,
                        [key]:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      })
                    }
                  />
                </label>
              ))}
              <label>
                Work arrangement
                <Select
                  aria-label="Work arrangement"
                  value={value.remote_preference || "any"}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      remote_preference: event.target
                        .value as Preferences["remote_preference"],
                    })
                  }
                >
                  {["any", "remote", "hybrid", "onsite"].map((entry) => (
                    <option key={entry}>{entry}</option>
                  ))}
                </Select>
              </label>
              <label>
                Employment types
                <Select
                  aria-label="Employment types"
                  multiple
                  value={value.employment_types || []}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      employment_types: Array.from(
                        event.target.selectedOptions,
                        (option) => option.value,
                      ) as Preferences["employment_types"],
                    })
                  }
                >
                  {["full_time", "internship", "contract"].map((entry) => (
                    <option key={entry}>{entry}</option>
                  ))}
                </Select>
              </label>
              <label>
                Salary currency
                <Input
                  aria-label="Salary currency"
                  maxLength={3}
                  value={value.salary_currency || ""}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      salary_currency: event.target.value.toUpperCase() || null,
                    })
                  }
                />
              </label>
              <label>
                Salary period
                <Select
                  aria-label="Salary period"
                  value={value.salary_period || ""}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      salary_period: (event.target.value ||
                        null) as Preferences["salary_period"],
                    })
                  }
                >
                  <option value="">Not specified</option>
                  {["hour", "day", "week", "month", "year"].map((entry) => (
                    <option key={entry}>{entry}</option>
                  ))}
                </Select>
              </label>
              <label>
                Application status
                <Select
                  aria-label="Application status"
                  value={value.application_status || "not_applied"}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      application_status: event.target
                        .value as Preferences["application_status"],
                    })
                  }
                >
                  {["all", "applied", "not_applied"].map((entry) => (
                    <option key={entry}>{entry}</option>
                  ))}
                </Select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={value.saved_jobs_only || false}
                  onChange={(event) =>
                    setDraft({
                      ...value,
                      saved_jobs_only: event.target.checked,
                    })
                  }
                />{" "}
                Saved jobs only
              </label>
              <p>
                Duplicate prevention is always on. Employee bounds 2 and 10
                require an evidenced count.
              </p>
              <Button
                disabled={!draft}
                busy={save.isPending}
                onClick={() => save.mutate(value)}
              >
                Save search preferences
              </Button>
            </div>
          </details>
        )}
        {save.isError && <ErrorState error={save.error} />}
        {save.isSuccess && !draft && (
          <p role="status">Search preferences saved.</p>
        )}
      </div>
    </section>
  );
}
