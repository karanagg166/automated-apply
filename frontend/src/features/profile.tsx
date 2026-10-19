"use client";
import { useEffect, useState } from "react";
import { ProjectsEditor } from "@/components/projects-editor";
import { sizeFilter } from "./startups";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  FileUp,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError, post, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";
const formSchema = z.object({
  full_name: z.string().min(2).max(200),
  email: z.email().max(254),
  summary: z.string().max(4000),
  skills: z.string().max(4000),
  resume_url: z
    .string()
    .max(2048)
    .refine(
      (value) =>
        !value || value !== "https://url-shortner-jet-rho.vercel.app/r2wL9UE",
      "The short-link destination is unresolved. Upload a PDF or supply the verified original URL.",
    ),
  company: z.string().max(200),
  role: z.string().max(200),
  start_date: z.string(),
  end_date: z.string(),
  highlight: z.string().max(4000),
  institution: z.string().max(200),
  qualification: z.string().max(200),
  field_of_study: z.string().max(200),
  projects: z.string().max(16000),
  target_titles: z.string().max(2000),
  locations: z.string().max(2000),
  remote: z.enum(["", "any", "remote", "hybrid", "onsite"]),
  startup_size: z.enum(["", "2-10", "11-50", "51-200", "201-500", "any"]),
  salary: z.string(),
  currency: z.string().max(3),
  notice: z.string(),
});
type Values = z.infer<typeof formSchema>;
type Proposal = {
  resource_type: Schema<"ResourceWrite">["resource_type"];
  label: string;
  url: string;
  status: string;
  issue?: string | null;
};
const initial: Values = {
  full_name: "",
  email: "",
  summary: "",
  skills: "",
  resume_url: "",
  company: "",
  role: "",
  start_date: "",
  end_date: "",
  highlight: "",
  institution: "",
  qualification: "",
  field_of_study: "",
  projects: "[]",
  target_titles: "",
  locations: "",
  remote: "",
  startup_size: "",
  salary: "",
  currency: "",
  notice: "",
};
const steps = [
  "Identity & resume",
  "Your experience",
  "Evidence & links",
  "Search preferences",
  "Final review",
];
export function ProfileWizard() {
  const client = useQueryClient(),
    [step, setStep] = useState(0),
    [selected, setSelected] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false),
    [saved, setSaved] = useState(""),
    [origin, setOrigin] = useState("Manually entered"),
    [imported, setImported] = useState<Schema<"ResumeImportRead"> | null>(null),
    [parseBusy, setParseBusy] = useState(false),
    [uploadError, setUploadError] = useState<unknown>(null);
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<Schema<"CandidateProfileRead">>("profile"),
  });
  const manifest = useQuery({
    queryKey: ["link-manifest"],
    queryFn: () =>
      api<{ resources: Proposal[]; resume_status: string }>(
        "dashboard/onboarding/manifest",
      ),
  });
  const resources = useQuery({
    queryKey: ["resources"],
    queryFn: () => api<Schema<"ResourceList">>("candidate/resources"),
    enabled: !!profile.data,
  });
  const resumes = useQuery({
    queryKey: ["private-resumes"],
    queryFn: () =>
      api<{
        resumes: Array<{
          id: string;
          label: string;
          confirmed: boolean;
          resource_id: string | null;
        }>;
      }>("dashboard/resumes"),
  });
  const form = useForm<Values>({
    resolver: zodResolver(formSchema),
    defaultValues: initial,
  });
  const {
    register,
    reset,
    getValues,
    setValue,
    formState: { errors },
  } = form;
  useEffect(() => {
    if (profile.data) {
      const p = profile.data;
      reset({
        ...initial,
        full_name: p.full_name,
        email: p.email,
        summary: p.summary || "",
        skills: p.verified_skills?.join(", ") || "",
        company: p.verified_roles?.[0]?.company || "",
        role: p.verified_roles?.[0]?.role || "",
        start_date: p.verified_roles?.[0]?.start_date || "",
        end_date: p.verified_roles?.[0]?.end_date || "",
        highlight: p.verified_roles?.[0]?.highlight || "",
        institution: p.education?.[0]?.institution || "",
        qualification: p.education?.[0]?.qualification || "",
        field_of_study: p.education?.[0]?.field_of_study || "",
        projects: JSON.stringify(p.projects || [], null, 2),
        target_titles: p.preferences?.target_titles?.join(", ") || "",
        locations: p.preferences?.preferred_locations?.join(", ") || "",
        remote: p.preferences?.remote_preference || "",
        salary: p.preferences?.minimum_salary?.toString() || "",
        currency: p.preferences?.salary_currency || "",
        notice: p.preferences?.notice_period_days?.toString() || "",
      });
      setOrigin("Saved profile · owner confirmed");
    }
  }, [profile.data, reset]);
  const list = (s: string) =>
    s
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  const save = useMutation({
    mutationFn: async (values: Values) => {
      if (!confirmed)
        throw new Error("Review the facts and confirm before saving.");
      const proposals =
        manifest.data?.resources.filter((x) => selected.includes(x.url)) || [];
      const projects = JSON.parse(values.projects || "[]");
      if (!Array.isArray(projects))
        throw new Error("Projects must be an array.");
      const existing = profile.data;
      const body: Schema<"CandidateProfileCreate"> = {
        full_name: values.full_name,
        email: values.email,
        summary: values.summary || null,
        verified_skills: list(values.skills),
        verified_roles:
          values.company && values.role
            ? [
                {
                  company: values.company,
                  role: values.role,
                  start_date: values.start_date || null,
                  end_date: values.end_date || null,
                  highlight: values.highlight || null,
                },
                ...(existing?.verified_roles || []).slice(1),
              ]
            : existing?.verified_roles || [],
        education:
          values.institution && values.qualification
            ? [
                {
                  institution: values.institution,
                  qualification: values.qualification,
                  field_of_study: values.field_of_study || null,
                },
                ...(existing?.education || []).slice(1),
              ]
            : existing?.education || [],
        projects,
        phone: existing?.phone || null,
        personal_website: existing?.personal_website || null,
        verified_experience_years: existing?.verified_experience_years ?? null,
        certifications: existing?.certifications || [],
        github_url:
          proposals.find((x) => x.resource_type === "github")?.url ||
          existing?.github_url ||
          null,
        linkedin_url:
          proposals.find((x) => x.resource_type === "linkedin")?.url ||
          existing?.linkedin_url ||
          null,
        portfolio_url:
          proposals.find((x) => x.resource_type === "portfolio")?.url ||
          existing?.portfolio_url ||
          null,
        preferences: {
          ...existing?.preferences,
          target_titles: list(values.target_titles),
          preferred_locations: list(values.locations),
          remote_preference: values.remote || null,
          minimum_salary: values.salary ? Number(values.salary) : null,
          salary_currency: values.currency || null,
          salary_period: values.salary ? "year" : null,
          notice_period_days: values.notice ? Number(values.notice) : null,
        },
      };
      const result = await api<Schema<"CandidateProfileRead">>("profile", {
        method: "PUT",
        headers: existing ? { "If-Match": `"${existing.version}"` } : {},
        body: JSON.stringify(body),
      });
      // Subsequent failures preserve the successful profile save and report exactly what remains.
      client.setQueryData(["profile"], result);
      const failures: string[] = [];
      for (const proposal of proposals.filter(
        (x) => !["github", "linkedin", "portfolio"].includes(x.resource_type),
      )) {
        const savedResource = resources.data?.resources.find(
          (r) => r.url === proposal.url,
        );
        if (savedResource && proposal.resource_type !== "geeksforgeeks")
          continue;
        try {
          if (proposal.resource_type === "geeksforgeeks") {
            for (const other of resources.data?.resources.filter(
              (r) =>
                r.resource_type === "geeksforgeeks" && r.url !== proposal.url,
            ) || []) {
              if (other.user_confirmed || other.is_primary)
                await post("candidate/resources", {
                  id: other.id,
                  resource_type: other.resource_type,
                  label: other.label,
                  url: other.url,
                  user_confirmed: false,
                  is_primary: false,
                });
            }
          }
          await post("candidate/resources", {
            ...(savedResource ? { id: savedResource.id } : {}),
            resource_type: proposal.resource_type,
            label: proposal.label,
            url: proposal.url,
            user_confirmed: !proposal.issue?.includes("unresolved"),
            is_primary: proposal.resource_type === "geeksforgeeks",
          });
        } catch {
          failures.push(proposal.label);
        }
      }
      if (
        values.resume_url &&
        !resources.data?.resources.some(
          (r) => r.resource_type === "resume" && r.url === values.resume_url,
        )
      ) {
        try {
          await post("candidate/resources", {
            resource_type: "resume",
            label: "Owner-reviewed resume link",
            url: values.resume_url,
            user_confirmed: true,
            is_primary:
              !imported &&
              !resources.data?.resources.some(
                (r) => r.resource_type === "resume" && r.is_primary,
              ),
          });
        } catch {
          failures.push("public resume URL validation or duplicate primary");
        }
      }
      if (imported) {
        try {
          await post(`dashboard/resumes/${imported.id}/confirm`, {
            owner_confirmed: true,
            primary: !resources.data?.resources.some(
              (r) => r.resource_type === "resume" && r.is_primary,
            ),
          });
        } catch {
          failures.push("private resume confirmation");
        }
      }
      if (values.startup_size) {
        try {
          await post("dashboard/presets", {
            name: "My preferred team size",
            filters: {
              ...sizeFilter(
                values.startup_size === "any" ? "all" : values.startup_size,
              ),
              use_profile: false,
              application_status: "not_applied",
            },
          });
        } catch {
          failures.push("team size preference");
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setSaved(
        failures.length
          ? `Profile saved. These resources still need attention: ${failures.join(", ")}. Review before retrying.`
          : "Your reviewed profile and selected evidence are saved. Your private resume remains available only to your authenticated workspace.",
      );
      client.invalidateQueries({ queryKey: ["resources"] });
      client.invalidateQueries({ queryKey: ["private-resumes"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  if (profile.isPending) return <Skeleton />;
  if (
    profile.isError &&
    !(profile.error instanceof ApiError && profile.error.status === 404)
  )
    return <ErrorState error={profile.error} retry={() => profile.refetch()} />;
  const proposals = manifest.data?.resources || [];
  return (
    <div className="wizard">
      <PageTitle
        eyebrow="THE FOUNDATION FOR BETTER MATCHES"
        title="Make it yours."
        description="Your facts, your evidence, your review. Nothing is inferred or sent to an AI provider."
        actions={
          profile.data ? (
            <Badge tone="green">Saved · version {profile.data.version}</Badge>
          ) : (
            <Badge tone="amber">Awaiting owner review</Badge>
          )
        }
      />
      <div className="stepper" aria-label="Onboarding steps">
        {steps.map((label, i) => (
          <button
            key={label}
            className={step === i ? "current" : ""}
            aria-current={step === i ? "step" : undefined}
            onClick={() => setStep(i)}
          >
            <small>0{i + 1}</small>
            {label}
          </button>
        ))}
      </div>
      <form
        onSubmit={form.handleSubmit(
          (v) => save.mutate(v),
          () => {
            setStep(0);
            setSaved("Check the highlighted identity fields before saving.");
          },
        )}
      >
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>{steps[step]}</h2>
              <p>{origin}</p>
            </div>
            <ShieldCheck size={19} className="muted" />
          </div>
          <div className="panel-body">
            {step === 0 && (
              <div className="stack">
                <p className="section-intro">
                  Upload a private resume or enter your facts below. Extracted
                  values are suggestions until you review and confirm them. The
                  referenced PDF is currently awaiting upload unless listed in
                  your private variants.
                </p>
                <div className="upload-zone">
                  <FileUp size={29} className="muted" />
                  <h3>Bring your experience along.</h3>
                  <p>
                    Plain PDF · up to 5 MiB · 20 pages · local extraction only
                  </p>
                  <input
                    aria-label="Upload private resume"
                    type="file"
                    accept="application/pdf,.pdf"
                    disabled={parseBusy}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setUploadError(null);
                      setParseBusy(true);
                      try {
                        if (file.size > 5 * 1024 * 1024)
                          throw new Error("Choose a PDF smaller than 5 MiB");
                        const imported = await api<Schema<"ResumeImportRead">>(
                          `dashboard/resumes?label=${encodeURIComponent(file.name.replace(/\.pdf$/i, ""))}`,
                          {
                            method: "POST",
                            headers: { "Content-Type": "application/pdf" },
                            body: file,
                          },
                        );
                        setImported(imported);
                        setOrigin("Extracted from resume · unconfirmed");
                        for (const key of ["full_name", "email"] as const)
                          if (
                            !getValues(key) &&
                            typeof imported.suggestions[key] === "string"
                          )
                            setValue(key, imported.suggestions[key]);
                        if (
                          !getValues("skills") &&
                          Array.isArray(imported.suggestions.verified_skills)
                        )
                          setValue(
                            "skills",
                            imported.suggestions.verified_skills.join(", "),
                          );
                        client.invalidateQueries({
                          queryKey: ["private-resumes"],
                        });
                      } catch (err) {
                        setUploadError(err);
                      } finally {
                        setParseBusy(false);
                      }
                    }}
                  />
                  {parseBusy && <Badge>Parsing privately…</Badge>}
                </div>
                <Field
                  label="Or use a reviewed public HTTPS resume URL"
                  hint="The URL is validated for public HTTPS syntax; review its content and availability yourself. Private uploads work independently."
                >
                  <Input type="url" {...register("resume_url")} />
                  {errors.resume_url && (
                    <span className="form-error">
                      {errors.resume_url.message}
                    </span>
                  )}
                </Field>
                {uploadError !== null && <ErrorState error={uploadError} />}{" "}
                {imported && (
                  <>
                    <Notice>
                      {imported.pages} pages parsed locally. Name, email and
                      recognized skill suggestions were populated only into
                      empty fields. Review experience and education against the
                      extracted text.
                    </Notice>
                    <details>
                      <summary>Review extracted source text</summary>
                      <pre className="source-text">
                        {imported.text ||
                          "No extractable text. Enter facts manually."}
                      </pre>
                    </details>
                  </>
                )}
                <div className="form-grid">
                  <Field label="Full name">
                    <Input
                      {...register("full_name")}
                      autoComplete="name"
                      required
                    />
                    {errors.full_name && (
                      <span className="form-error">
                        {errors.full_name.message}
                      </span>
                    )}
                  </Field>
                  <Field
                    label="Email"
                    hint="Private. Used in application fields only after your review."
                  >
                    <Input
                      {...register("email")}
                      type="email"
                      autoComplete="email"
                      required
                    />
                    {errors.email && (
                      <span className="form-error">{errors.email.message}</span>
                    )}
                  </Field>
                  <Field label="Professional summary">
                    <textarea className="input" {...register("summary")} />
                  </Field>
                </div>
                {!!resumes.data?.resumes.length && (
                  <div>
                    <h3>Private resume variants</h3>
                    {resumes.data.resumes.map((r) => (
                      <div className="evidence-item split" key={r.id}>
                        <div>
                          <strong>{r.label}</strong>
                          <p>
                            {r.confirmed
                              ? "Owner confirmed"
                              : "Awaiting review"}
                          </p>
                        </div>
                        <a
                          className="button"
                          href={`/api/backend/dashboard/resumes/${r.id}`}
                        >
                          Download privately
                        </a>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {step === 1 && (
              <div className="stack">
                <p className="section-intro">
                  Review the actual text of your resume. Dates, institutions,
                  employers and achievements are never inferred from the
                  supplied filename. Existing additional entries are preserved
                  when editing this first entry.
                </p>
                <div className="form-grid">
                  <Field label="Company">
                    <Input {...register("company")} />
                  </Field>
                  <Field label="Role">
                    <Input {...register("role")} />
                  </Field>
                  <Field label="Start date · optional">
                    <Input type="date" {...register("start_date")} />
                  </Field>
                  <Field label="End date · optional">
                    <Input type="date" {...register("end_date")} />
                  </Field>
                  <Field label="Contribution / evidence">
                    <textarea className="input" {...register("highlight")} />
                  </Field>
                </div>
                <div className="divider" />
                <h3>Education</h3>
                <div className="form-grid">
                  <Field label="Institution">
                    <Input {...register("institution")} />
                  </Field>
                  <Field label="Qualification">
                    <Input {...register("qualification")} />
                  </Field>
                  <Field label="Field of study">
                    <Input {...register("field_of_study")} />
                  </Field>
                </div>
                <Field
                  label="Technical skills"
                  hint="Comma-separated. Save only skills you are comfortable claiming."
                >
                  <textarea className="input" {...register("skills")} />
                </Field>
                <ProjectsEditor
                  value={form.watch("projects")}
                  onChange={(v) =>
                    setValue("projects", v, { shouldDirty: true })
                  }
                />
              </div>
            )}
            {step === 2 && (
              <>
                <p className="section-intro">
                  These exact links were supplied by the owner. Select only
                  those you have reviewed. Availability and ownership are
                  separate checks. Public links are stored with your profile,
                  never as client credentials.
                </p>
                {manifest.isError && <ErrorState error={manifest.error} />}
                <Notice>
                  The two GeeksforGeeks links conflict. Choose at most one after
                  verifying your account. ShopSizzle and CSES remain optional.
                  The resume short URL has an unresolved destination and cannot
                  serve as a verified resume.
                </Notice>
                {proposals.map((p) => (
                  <div className="resource-review" key={p.url}>
                    <input
                      id={`link-${proposals.indexOf(p)}`}
                      aria-label={`Confirm ${p.label}`}
                      type="checkbox"
                      checked={selected.includes(p.url)}
                      disabled={p.issue === "destination_unresolved"}
                      onChange={(e) =>
                        setSelected((current) =>
                          e.target.checked
                            ? [
                                ...current.filter(
                                  (url) =>
                                    p.resource_type !== "geeksforgeeks" ||
                                    !proposals.some(
                                      (x) =>
                                        x.url === url &&
                                        x.resource_type === "geeksforgeeks",
                                    ),
                                ),
                                p.url,
                              ]
                            : current.filter((x) => x !== p.url),
                        )
                      }
                    />
                    <label htmlFor={`link-${proposals.indexOf(p)}`}>
                      <strong>{p.label}</strong>
                      <small>{p.url}</small>
                      <small>
                        {p.issue
                          ? p.issue.replaceAll("_", " ")
                          : "Owner-provided proposal · availability not independently verified"}
                      </small>
                    </label>
                    <External href={p.url}>Review</External>
                    <Badge
                      tone={p.issue === "conflicting_gfg" ? "amber" : "neutral"}
                    >
                      {p.status.replaceAll("_", " ")}
                    </Badge>
                  </div>
                ))}
                {resources.data && (
                  <details className="spaced">
                    <summary>
                      Already saved resources ({resources.data.resources.length}
                      )
                    </summary>
                    {resources.data.resources.map((r) => (
                      <div className="resource-review" key={r.id}>
                        <div>
                          <strong>{r.label}</strong>
                          <small>
                            {r.source_type === "private_upload"
                              ? "Private resume · authenticated download"
                              : r.url}
                          </small>
                        </div>
                        <Badge tone={r.user_confirmed ? "green" : "amber"}>
                          {r.user_confirmed
                            ? "Owner confirmed"
                            : "Needs review"}
                        </Badge>
                      </div>
                    ))}
                  </details>
                )}
              </>
            )}
            {step === 3 && (
              <div className="stack">
                <p className="section-intro">
                  Choose your direction. Preferences are optional and remain
                  separate from verified career facts. Salary, notice period and
                  work authorization are never inferred.
                </p>
                <div className="form-grid">
                  <Field label="Target job titles" hint="Comma-separated">
                    <Input {...register("target_titles")} />
                  </Field>
                  <Field label="Preferred locations" hint="Comma-separated">
                    <Input {...register("locations")} />
                  </Field>
                  <Field label="Work preference">
                    <Select {...register("remote")}>
                      <option value="">Not specified</option>
                      {["any", "remote", "hybrid", "onsite"].map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </Select>
                  </Field>
                  <Field
                    label="Startup team size"
                    hint="Saved as a reusable evidence-based search preset."
                  >
                    <Select {...register("startup_size")}>
                      <option value="">Not specified</option>
                      {["any", "2-10", "11-50", "51-200", "201-500"].map(
                        (x) => (
                          <option key={x}>{x}</option>
                        ),
                      )}
                    </Select>
                  </Field>
                  <Field label="Minimum annual salary · optional">
                    <Input
                      {...register("salary")}
                      type="number"
                      min="0"
                      max="1000000000000"
                    />
                  </Field>
                  <Field label="Currency · required with salary">
                    <Input
                      {...register("currency")}
                      maxLength={3}
                      placeholder="ISO currency code"
                    />
                  </Field>
                  <Field label="Notice period in days · optional">
                    <Input
                      {...register("notice")}
                      type="number"
                      min="0"
                      max="3650"
                    />
                  </Field>
                </div>
              </div>
            )}
            {step === 4 && (
              <div className="stack">
                <Notice>
                  Only your reviewed form values and selected links will be
                  saved. Confirming the profile does not authorize AI
                  processing, paid providers, email delivery or application
                  submission.
                </Notice>
                <div className="form-grid">
                  {[
                    ["Name", getValues("full_name")],
                    ["Email", getValues("email")],
                    ["Skills", getValues("skills") || "Missing"],
                    [
                      "Target titles",
                      getValues("target_titles") || "Not specified",
                    ],
                    [
                      "Experience",
                      getValues("company")
                        ? `${getValues("role")} · ${getValues("company")}`
                        : "Not specified",
                    ],
                    ["Education", getValues("institution") || "Not specified"],
                  ].map(([k, v]) => (
                    <div className="evidence-item" key={k}>
                      <strong>{k}</strong>
                      <p>{v}</p>
                    </div>
                  ))}
                </div>
                <p className="section-intro">
                  {selected.length} resource proposals selected ·{" "}
                  {imported
                    ? "Private PDF uploaded; confirmation will follow the profile save"
                    : "No new PDF parsed in this session"}
                  . Conflicting or unresolved resources remain outside verified
                  facts.
                </p>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>
                    I reviewed these facts, selected links and preferences. I
                    confirm the saved facts accurately describe me.
                  </span>
                </label>
                <Button
                  type="submit"
                  variant="primary"
                  busy={save.isPending}
                  disabled={!confirmed}
                >
                  <CheckCheck size={16} />
                  Save reviewed profile
                </Button>
              </div>
            )}
            {save.isError && <ErrorState error={save.error} />}{" "}
            {saved && <Notice>{saved}</Notice>}
          </div>
          <div className="wizard-footer">
            <small>Step {step + 1} of 5 · private, reviewable evidence</small>
            <div className="actions">
              <Button
                type="button"
                disabled={step === 0}
                onClick={() => setStep(step - 1)}
              >
                <ArrowLeft size={13} />
                Back
              </Button>
              {step < 4 && (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => setStep(step + 1)}
                >
                  Continue
                  <ArrowRight size={13} />
                </Button>
              )}
              {step === 4 && (
                <Badge>
                  <Check size={12} />
                  Owner review required
                </Badge>
              )}
            </div>
          </div>
        </section>
      </form>
    </div>
  );
}
