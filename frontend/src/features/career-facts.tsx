"use client";
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Schema } from "@/lib/api";
import {
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Select,
} from "@/components/ui";

type Profile = Schema<"CandidateProfileRead">;
type Compensation = Schema<"CompensationFact-Output">;
type CountryInput = Omit<
  Schema<"CountryAuthorization">,
  "authorized_to_work"
> & { authorized_to_work: boolean | null };
const unknownBoolean = (value: boolean | null | undefined) =>
  value == null ? "" : String(value);
const readBoolean = (value: FormDataEntryValue | null) =>
  value === "true" ? true : value === "false" ? false : null;

function CompensationFields({
  label,
  name,
  value,
}: {
  label: string;
  name: string;
  value?: Compensation | null;
}) {
  return (
    <fieldset className="panel">
      <legend>{label}</legend>
      <div className="form-grid">
        <Field
          label={`${label} amount`}
          hint="Leave blank if unknown. Use full currency units, not lakhs."
        >
          <Input
            name={`${name}.amount`}
            type="number"
            min="0"
            max="1000000000000"
            step="0.01"
            defaultValue={value?.amount ?? ""}
          />
        </Field>
        <Field label={`${label} currency`}>
          <Input
            name={`${name}.currency`}
            maxLength={3}
            pattern="[A-Z]{3}"
            placeholder="INR"
            defaultValue={value?.currency ?? ""}
          />
        </Field>
        <Field label={`${label} period`}>
          <Select name={`${name}.period`} defaultValue={value?.period ?? ""}>
            <option value="">Unknown</option>
            <option value="hour">Per hour</option>
            <option value="month">Per month</option>
            <option value="year">Per year</option>
          </Select>
        </Field>
        <Field label={`${label} type`}>
          <Select name={`${name}.kind`} defaultValue={value?.kind ?? ""}>
            <option value="">Unknown</option>
            <option value="ctc">CTC</option>
            <option value="base_salary">Base salary</option>
            <option value="total_compensation">Total compensation</option>
          </Select>
        </Field>
      </div>
    </fieldset>
  );
}

export function CareerFacts({ profile }: { profile: Profile }) {
  const client = useQueryClient();
  const prefs = profile.preferences;
  const [confirmed, setConfirmed] = useState(false);
  const [localError, setLocalError] = useState<unknown>(null);
  const [countries, setCountries] = useState<
    Array<{ key: string; value: CountryInput }>
  >(() =>
    (prefs?.work_authorizations ?? []).map((value) => ({
      key: crypto.randomUUID(),
      value,
    })),
  );
  const save = useMutation({
    mutationFn: (preferences: Schema<"JobSearchPreferencesUpdate">) =>
      api<Profile>("profile", {
        method: "PATCH",
        headers: { "If-Match": `"${profile.version}"` },
        body: JSON.stringify({ preferences }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["profile"] });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) return;
    setLocalError(null);
    const data = new FormData(event.currentTarget);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    function money(name: string): Schema<"CompensationFact-Input"> | null {
      if (!text(`${name}.amount`)) return null;
      const currency = text(`${name}.currency`),
        period = text(`${name}.period`),
        kind = text(`${name}.kind`);
      if (
        !/^[A-Z]{3}$/.test(currency) ||
        !["hour", "month", "year"].includes(period) ||
        !["ctc", "base_salary", "total_compensation"].includes(kind)
      )
        throw new Error(
          "Each compensation amount requires its currency, period and type.",
        );
      return {
        amount: text(`${name}.amount`),
        currency,
        period: period as Schema<"CompensationFact-Input">["period"],
        kind: kind as Schema<"CompensationFact-Input">["kind"],
      };
    }
    try {
      save.mutate({
        current_compensation: money("current"),
        expected_compensation: money("expected"),
        availability_date: text("availability") || null,
        current_location: text("location") || null,
        open_to_relocation: readBoolean(data.get("relocation")),
        relocation_locations: text("relocation_locations")
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        work_authorizations: countries.map((_, index) => {
          const code = text(`country.${index}.code`),
            name = text(`country.${index}.name`),
            authorized = readBoolean(data.get(`country.${index}.authorized`));
          if (!/^[A-Z]{2}$/.test(code) || !name || authorized === null)
            throw new Error(
              "Every country requires its two-letter code, name and an explicit work authorization answer. Remove an unknown country.",
            );
          return {
            country_code: code,
            country_name: name,
            authorized_to_work: authorized,
            requires_sponsorship_now_or_future: readBoolean(
              data.get(`country.${index}.sponsorship`),
            ),
          };
        }),
      });
    } catch (error) {
      setLocalError(error);
    }
  }
  return (
    <details className="panel">
      <summary>Private application facts</summary>
      <p>
        Save only facts you have reviewed. Blank values stay unknown. Search
        salary minimums are separate from current and expected compensation.
        Changing facts requires existing applications to be reviewed again.
      </p>
      <form onSubmit={submit}>
        <CompensationFields
          label="Current compensation"
          name="current"
          value={prefs?.current_compensation}
        />
        <CompensationFields
          label="Expected compensation"
          name="expected"
          value={prefs?.expected_compensation}
        />
        <div className="form-grid">
          <Field
            label="Available from"
            hint="An actual approved date; never calculated from notice period."
          >
            <Input
              type="date"
              name="availability"
              defaultValue={prefs?.availability_date ?? ""}
            />
          </Field>
          <Field label="Current location">
            <Input
              name="location"
              maxLength={200}
              defaultValue={prefs?.current_location ?? ""}
            />
          </Field>
          <Field label="Open to relocation">
            <Select
              name="relocation"
              defaultValue={unknownBoolean(prefs?.open_to_relocation)}
            >
              <option value="">Unknown</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </Select>
          </Field>
          <Field
            label="Approved relocation destinations"
            hint="Comma-separated; a general Yes does not approve every destination."
          >
            <Input
              name="relocation_locations"
              defaultValue={prefs?.relocation_locations?.join(", ") ?? ""}
            />
          </Field>
        </div>
        <h3>Country-specific work authorization</h3>
        {countries.map(({ key, value }, index) => (
          <fieldset className="panel" key={key}>
            <legend>Country {index + 1}</legend>
            <div className="form-grid">
              <Field label="Country code">
                <Input
                  name={`country.${index}.code`}
                  defaultValue={value.country_code}
                  maxLength={2}
                  pattern="[A-Z]{2}"
                  placeholder="IN"
                  required
                />
              </Field>
              <Field label="Country name">
                <Input
                  name={`country.${index}.name`}
                  defaultValue={value.country_name}
                  maxLength={200}
                  required
                />
              </Field>
              <Field label="Authorized to work">
                <Select
                  name={`country.${index}.authorized`}
                  defaultValue={unknownBoolean(value.authorized_to_work)}
                  required
                >
                  <option value="">Unknown</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </Select>
              </Field>
              <Field label="Need sponsorship now or in future">
                <Select
                  name={`country.${index}.sponsorship`}
                  defaultValue={unknownBoolean(
                    value.requires_sponsorship_now_or_future,
                  )}
                >
                  <option value="">Unknown</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </Select>
              </Field>
            </div>
            <Button
              type="button"
              onClick={() =>
                setCountries((rows) => rows.filter((row) => row.key !== key))
              }
            >
              Remove country {index + 1}
            </Button>
          </fieldset>
        ))}
        <Button
          type="button"
          disabled={countries.length >= 20}
          onClick={() =>
            setCountries((rows) => [
              ...rows,
              {
                key: crypto.randomUUID(),
                value: {
                  country_code: "",
                  country_name: "",
                  authorized_to_work: null,
                  requires_sponsorship_now_or_future: null,
                },
              },
            ])
          }
        >
          Add country authorization
        </Button>
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          I reviewed these private career facts and their units.
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={!confirmed}
          busy={save.isPending}
        >
          Save reviewed career facts
        </Button>
        {(localError || save.error) && (
          <ErrorState error={localError || save.error} />
        )}
        {save.isSuccess && (
          <Notice>
            Career facts saved. Review existing answers against the updated
            profile.
          </Notice>
        )}
      </form>
    </details>
  );
}
