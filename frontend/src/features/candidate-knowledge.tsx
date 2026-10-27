"use client";

import { useId, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Award,
  BookOpen,
  Briefcase,
  Check,
  CheckCircle2,
  Clock,
  Code,
  DollarSign,
  Edit3,
  ExternalLink,
  FileCheck,
  FolderGit2,
  Globe,
  History,
  Link as LinkIcon,
  Plus,
  RefreshCw,
  Save,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  User,
  Users,
} from "lucide-react";
import { api, dateLabel, externalUrl, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Field,
  Input,
  Modal,
  Notice,
  PageTitle,
  Select,
  Skeleton,
} from "@/components/ui";

type Profile = Schema<"CandidateProfileRead">;
type Compensation = Schema<"CompensationFact-Output">;
type Project = Schema<"VerifiedProject">;

export function CandidateKnowledge() {
  const client = useQueryClient();
  const confirmationId = useId();

  const [activeTab, setActiveTab] = useState<
    "approved" | "edit-facts" | "projects" | "links" | "answers"
  >("approved");

  const [editSuccessMessage, setEditSuccessMessage] = useState("");
  const [conflictError, setConflictError] = useState<string | null>(null);
  const [confirmedTruthful, setConfirmedTruthful] = useState(false);

  // Form states for editable facts
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [location, setLocation] = useState("");
  const [experienceYears, setExperienceYears] = useState("");
  const [summary, setSummary] = useState("");
  const [skills, setSkills] = useState("");
  const [noticeDays, setNoticeDays] = useState("");
  const [remotePref, setRemotePref] = useState<string>("any");

  // Compensation
  const [currentAmount, setCurrentAmount] = useState("");
  const [currentCurrency, setCurrentCurrency] = useState("INR");
  const [currentPeriod, setCurrentPeriod] = useState<string>("year");
  const [currentKind, setCurrentKind] = useState<string>("ctc");

  const [expectedAmount, setExpectedAmount] = useState("");
  const [expectedCurrency, setExpectedCurrency] = useState("INR");
  const [expectedPeriod, setExpectedPeriod] = useState<string>("year");
  const [expectedKind, setExpectedKind] = useState<string>("ctc");

  // Projects state
  const [projectsList, setProjectsList] = useState<Project[]>([]);
  const [editingProjectIndex, setEditingProjectIndex] = useState<number | null>(
    null,
  );
  const [projectTitle, setProjectTitle] = useState("");
  const [projectDesc, setProjectDesc] = useState("");
  const [projectRole, setProjectRole] = useState("");
  const [projectTech, setProjectTech] = useState("");
  const [projectImpact, setProjectImpact] = useState("");
  const [projectUrl, setProjectUrl] = useState("");
  const [projectModalOpen, setProjectModalOpen] = useState(false);

  // Links state
  const [githubUrl, setGithubUrl] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [portfolioUrl, setPortfolioUrl] = useState("");
  const [personalWebsite, setPersonalWebsite] = useState("");

  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<Profile>("profile"),
  });

  const resourcesQuery = useQuery({
    queryKey: ["resources"],
    queryFn: () => api<Schema<"ResourceList">>("candidate/resources"),
    enabled: !!profileQuery.data,
  });

  const savedAnswersQuery = useQuery({
    queryKey: ["saved-answer-drafts"],
    queryFn: () => api<Schema<"DraftRead">[]>("application-answers/drafts"),
  });

  const reuseBank = useQuery({
    queryKey: ["answer-reuse-bank"],
    queryFn: () =>
      api<{
        enabled: boolean;
        approvals: Record<string, { approved: boolean; scope: string }>;
      }>("application-answers/reuse-approvals"),
  });

  // Populate local form fields from loaded backend profile
  useEffect(() => {
    if (profileQuery.data) {
      const p = profileQuery.data;
      setFullName(p.full_name || "");
      setEmail(p.email || "");
      setPhone(p.phone || "");
      setLocation(p.preferences?.current_location || "");
      setExperienceYears(p.verified_experience_years?.toString() || "");
      setSummary(p.summary || "");
      setSkills(p.verified_skills?.join(", ") || "");
      setNoticeDays(p.preferences?.notice_period_days?.toString() || "");
      setRemotePref(p.preferences?.remote_preference || "any");

      // Current compensation
      const curr = p.preferences?.current_compensation;
      setCurrentAmount(curr?.amount || "");
      setCurrentCurrency(curr?.currency || "INR");
      setCurrentPeriod(curr?.period || "year");
      setCurrentKind(curr?.kind || "ctc");

      // Expected compensation
      const exp = p.preferences?.expected_compensation;
      setExpectedAmount(exp?.amount || "");
      setExpectedCurrency(exp?.currency || "INR");
      setExpectedPeriod(exp?.period || "year");
      setExpectedKind(exp?.kind || "ctc");

      // Projects
      setProjectsList((p.projects as Project[]) || []);

      // Links
      setGithubUrl(p.github_url || "");
      setLinkedinUrl(p.linkedin_url || "");
      setPortfolioUrl(p.portfolio_url || "");
      setPersonalWebsite(p.personal_website || "");
    }
  }, [profileQuery.data]);

  // Mutation to save updated candidate facts with Optimistic Concurrency (If-Match)
  const saveFactsMutation = useMutation({
    mutationFn: async () => {
      if (!profileQuery.data) throw new Error("No existing profile loaded");
      if (!confirmedTruthful) {
        throw new Error(
          "Explicit factual confirmation required before saving candidate facts.",
        );
      }

      setConflictError(null);
      setEditSuccessMessage("");

      const existing = profileQuery.data;

      // Construct current compensation
      let currentComp: Schema<"CompensationFact-Input"> | null = null;
      if (currentAmount.trim()) {
        currentComp = {
          amount: currentAmount.trim(),
          currency: currentCurrency.toUpperCase(),
          period: currentPeriod as Schema<"CompensationFact-Input">["period"],
          kind: currentKind as Schema<"CompensationFact-Input">["kind"],
        };
      }

      // Construct expected compensation
      let expectedComp: Schema<"CompensationFact-Input"> | null = null;
      if (expectedAmount.trim()) {
        expectedComp = {
          amount: expectedAmount.trim(),
          currency: expectedCurrency.toUpperCase(),
          period: expectedPeriod as Schema<"CompensationFact-Input">["period"],
          kind: expectedKind as Schema<"CompensationFact-Input">["kind"],
        };
      }

      const body: Schema<"CandidateProfileCreate-Input"> = {
        full_name: fullName.trim(),
        email: email.trim(),
        phone: phone.trim() || null,
        summary: summary.trim() || null,
        personal_website: personalWebsite.trim() || null,
        github_url: githubUrl.trim() || null,
        linkedin_url: linkedinUrl.trim() || null,
        portfolio_url: portfolioUrl.trim() || null,
        verified_experience_years: experienceYears.trim()
          ? Number(experienceYears)
          : null,
        verified_skills: skills
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        verified_roles: existing.verified_roles || [],
        education: existing.education || [],
        certifications: existing.certifications || [],
        projects: projectsList,
        preferences: {
          ...existing.preferences,
          current_location: location.trim() || null,
          notice_period_days: noticeDays.trim() ? Number(noticeDays) : null,
          remote_preference: (remotePref ||
            null) as Schema<"JobSearchPreferencesUpdate">["remote_preference"],
          current_compensation: currentComp,
          expected_compensation: expectedComp,
        },
      };

      try {
        const result = await api<Profile>("profile", {
          method: "PUT",
          headers: {
            "If-Match": `"${existing.version}"`,
          },
          body: JSON.stringify(body),
        });
        return result;
      } catch (err: unknown) {
        const status = (err as { status?: number }).status;
        if (status === 412 || status === 409) {
          throw new Error("VERSION_CONFLICT");
        }
        throw err;
      }
    },
    onSuccess: (updatedProfile) => {
      client.setQueryData(["profile"], updatedProfile);
      setEditSuccessMessage(
        `Candidate facts saved successfully as approved version ${updatedProfile.version}.`,
      );
      setConfirmedTruthful(false);
      setActiveTab("approved");
    },
    onError: (err: Error) => {
      if (err.message === "VERSION_CONFLICT") {
        setConflictError(
          "Stale revision conflict: This profile was updated elsewhere. Your changes were not applied to prevent accidental overwrites. Please refresh to load the latest approved facts.",
        );
      }
    },
  });

  const handleOpenAddProject = () => {
    setEditingProjectIndex(null);
    setProjectTitle("");
    setProjectDesc("");
    setProjectRole("");
    setProjectTech("");
    setProjectImpact("");
    setProjectUrl("");
    setProjectModalOpen(true);
  };

  const handleOpenEditProject = (idx: number) => {
    const p = projectsList[idx];
    setEditingProjectIndex(idx);
    setProjectTitle(p.name);
    setProjectDesc(p.description || "");
    setProjectRole(p.contribution || "");
    setProjectTech((p.technologies || []).join(", "));
    setProjectImpact(p.measurable_results || "");
    setProjectUrl(p.url || "");
    setProjectModalOpen(true);
  };

  const handleSaveProject = () => {
    setConfirmedTruthful(false);
    if (!projectTitle.trim() || !projectDesc.trim()) return;
    const techArray = projectTech
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const newProject: Project = {
      name: projectTitle.trim(),
      description: projectDesc.trim() || null,
      contribution: projectRole.trim() || null,
      technologies: techArray,
      measurable_results: projectImpact.trim() || null,
      url: projectUrl.trim() || null,
    };

    if (editingProjectIndex !== null) {
      const updated = [...projectsList];
      updated[editingProjectIndex] = newProject;
      setProjectsList(updated);
    } else {
      setProjectsList([...projectsList, newProject]);
    }
    setProjectModalOpen(false);
  };

  const handleDeleteProject = (idx: number) => {
    setProjectsList(projectsList.filter((_, i) => i !== idx));
    setConfirmedTruthful(false);
  };

  if (profileQuery.isPending) return <Skeleton />;
  if (profileQuery.isError) return <ErrorState error={profileQuery.error} />;

  const p = profileQuery.data;
  const prefs = p.preferences;
  const currentComp = prefs?.current_compensation;
  const expectedComp = prefs?.expected_compensation;
  const answers = savedAnswersQuery.data || [];

  return (
    <div className="stack spaced" aria-label="Candidate Knowledge and Facts">
      <PageTitle
        eyebrow="TRUTH-BACKED CANDIDATE KNOWLEDGE"
        title="Candidate facts & approved answers."
        description="Your single source of truth for personal facts, technical skills, verified projects, and approved reusable answers."
        actions={
          <div className="actions">
            <Badge tone="green">
              <ShieldCheck size={12} />
              Approved Version {p.version}
            </Badge>
            <Button
              onClick={() => profileQuery.refetch()}
              busy={profileQuery.isFetching}
            >
              <RefreshCw size={13} />
              Refresh facts
            </Button>
          </div>
        }
      />

      {editSuccessMessage && (
        <Notice>
          <div className="split">
            <span>{editSuccessMessage}</span>
            <CheckCircle2 size={16} style={{ color: "var(--green)" }} />
          </div>
        </Notice>
      )}

      {conflictError && (
        <div className="error-state" role="alert">
          <AlertTriangle size={20} />
          <div>
            <strong>Profile version conflict</strong>
            <p>{conflictError}</p>
            <Button
              onClick={() => {
                setConflictError(null);
                profileQuery.refetch();
              }}
            >
              Reload latest approved version
            </Button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div
        className="status-tabs"
        role="tablist"
        aria-label="Candidate knowledge tabs"
      >
        {[
          ["approved", "Approved facts overview"],
          ["edit-facts", "Edit personal & career facts"],
          ["projects", `Projects & achievements (${projectsList.length})`],
          ["links", "Verified links & evidence"],
          ["answers", `Saved answers (${answers.length})`],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            className={activeTab === key ? "selected" : ""}
            onClick={() => setActiveTab(key as typeof activeTab)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* TAB 1: APPROVED FACTS OVERVIEW */}
      {activeTab === "approved" && (
        <div className="detail-grid">
          <section className="panel panel-body stack">
            <div className="split">
              <h3>Current Approved Profile Facts</h3>
              <Badge tone="neutral">v{p.version}</Badge>
            </div>
            <Notice>
              These facts are active in your knowledge base. When fact revisions
              are approved, dependent answers are marked for review.
            </Notice>

            <dl>
              <dt>Full name</dt>
              <dd>
                <strong>{p.full_name}</strong>
              </dd>

              <dt>Primary email</dt>
              <dd>
                <code>{p.email}</code>
              </dd>

              <dt>Phone</dt>
              <dd>
                {p.phone || (
                  <span className="muted">Unknown / not provided</span>
                )}
              </dd>

              <dt>Current location</dt>
              <dd>
                {prefs?.current_location || (
                  <span className="muted">Unknown / not provided</span>
                )}
              </dd>

              <dt>Verified experience</dt>
              <dd>
                {p.verified_experience_years !== null ? (
                  `${p.verified_experience_years} years`
                ) : (
                  <span className="muted">Not established</span>
                )}
              </dd>

              <dt>Notice period</dt>
              <dd>
                {prefs?.notice_period_days !== null &&
                prefs?.notice_period_days !== undefined ? (
                  `${prefs.notice_period_days} days`
                ) : (
                  <span className="muted">Unknown / not established</span>
                )}
              </dd>

              <dt>Work preference</dt>
              <dd>
                <Badge>{readable(prefs?.remote_preference || "any")}</Badge>
              </dd>
            </dl>

            <div className="detail-section">
              <h4>
                Verified Technical Skills ({p.verified_skills?.length || 0})
              </h4>
              <div className="tag-list">
                {p.verified_skills && p.verified_skills.length > 0 ? (
                  p.verified_skills.map((skill) => (
                    <Badge key={skill}>{skill}</Badge>
                  ))
                ) : (
                  <span className="muted">No verified skills entered</span>
                )}
              </div>
            </div>

            <div className="detail-section">
              <h4>Professional Summary</h4>
              <p className="preserve-lines">
                {p.summary || (
                  <span className="muted">No summary recorded</span>
                )}
              </p>
            </div>
          </section>

          <aside className="panel panel-body stack">
            <h3>Compensation & Expectations</h3>
            <Notice>
              Compensation facts remain private and are only cited in
              exact-match approved contexts.
            </Notice>

            <div className="metric spaced">
              <div className="metric-label">CURRENT COMPENSATION</div>
              <p className="spaced">
                {currentComp ? (
                  <strong>
                    {currentComp.amount} {currentComp.currency} /{" "}
                    {readable(currentComp.period)} ({readable(currentComp.kind)}
                    )
                  </strong>
                ) : (
                  <span className="muted">Unknown / not disclosed</span>
                )}
              </p>
            </div>

            <div className="metric spaced">
              <div className="metric-label">EXPECTED COMPENSATION</div>
              <p className="spaced">
                {expectedComp ? (
                  <strong>
                    {expectedComp.amount} {expectedComp.currency} /{" "}
                    {readable(expectedComp.period)} (
                    {readable(expectedComp.kind)})
                  </strong>
                ) : (
                  <span className="muted">Unknown / not disclosed</span>
                )}
              </p>
            </div>

            <div className="detail-section">
              <h4>Work Authorizations</h4>
              <ul>
                {prefs?.work_authorizations &&
                prefs.work_authorizations.length > 0 ? (
                  prefs.work_authorizations.map((auth, idx) => (
                    <li key={idx}>
                      <strong>
                        {auth.country_name} ({auth.country_code}):
                      </strong>{" "}
                      {auth.authorized_to_work
                        ? "Authorized"
                        : "Not authorized"}
                      {auth.requires_sponsorship_now_or_future &&
                        " · Sponsorship required"}
                    </li>
                  ))
                ) : (
                  <li className="muted">
                    No country authorization facts saved
                  </li>
                )}
              </ul>
            </div>

            <div className="actions" style={{ marginTop: "1rem" }}>
              <Button
                variant="primary"
                onClick={() => setActiveTab("edit-facts")}
              >
                <Edit3 size={13} />
                Edit approved facts
              </Button>
            </div>
          </aside>
        </div>
      )}

      {/* TAB 2: EDIT FACTS */}
      {activeTab === "edit-facts" && (
        <form
          className="panel panel-body stack"
          onSubmit={(e) => {
            e.preventDefault();
            saveFactsMutation.mutate();
          }}
        >
          <div className="split">
            <h3>Edit Candidate Facts</h3>
            <Badge tone="amber">Draft in progress</Badge>
          </div>
          <p className="section-intro">
            Required fields are validated. Unknown fields remain unknown rather
            than guessed. Saving requires explicit confirmation and checks the
            server version.
          </p>

          <div className="form-grid">
            <Field label="Full name" hint="Official full legal name">
              <Input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                maxLength={200}
              />
            </Field>

            <Field label="Primary email" hint="Verified contact address">
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={254}
              />
            </Field>

            <Field label="Phone number" hint="With country code">
              <Input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91 9876543210"
                maxLength={50}
              />
            </Field>

            <Field label="Current city / location">
              <Input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. Bengaluru, India"
                maxLength={200}
              />
            </Field>

            <Field
              label="Experience in years"
              hint="Verified numeric years (0 to 100)"
            >
              <Input
                type="number"
                min="0"
                max="100"
                step="0.5"
                value={experienceYears}
                onChange={(e) => setExperienceYears(e.target.value)}
              />
            </Field>

            <Field label="Notice period (days)" hint="Official required notice">
              <Input
                type="number"
                min="0"
                max="365"
                value={noticeDays}
                onChange={(e) => setNoticeDays(e.target.value)}
                placeholder="e.g. 30"
              />
            </Field>

            <Field label="Remote work preference">
              <Select
                value={remotePref}
                onChange={(e) => setRemotePref(e.target.value)}
              >
                <option value="any">Any (Remote, Hybrid or Onsite)</option>
                <option value="remote">Remote Only</option>
                <option value="hybrid">Hybrid Preferred</option>
                <option value="onsite">Onsite</option>
              </Select>
            </Field>
          </div>

          <Field
            label="Technical skills"
            hint="Comma-separated verified skills"
          >
            <Input
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
              placeholder="Python, FastAPI, TypeScript, React, PostgreSQL, Docker, Redis"
            />
          </Field>

          <Field
            label="Executive summary / Bio"
            hint="Truthful career overview"
          >
            <textarea
              className="input preserve-lines"
              rows={4}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={4000}
            />
          </Field>

          <fieldset className="panel stack" style={{ padding: "1rem" }}>
            <legend>
              <strong>Compensation Expectations</strong>
            </legend>
            <div className="form-grid">
              <Field label="Current amount">
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={currentAmount}
                  onChange={(e) => setCurrentAmount(e.target.value)}
                  placeholder="Leave blank if unknown"
                />
              </Field>
              <Field label="Current currency">
                <Input
                  maxLength={3}
                  value={currentCurrency}
                  onChange={(e) =>
                    setCurrentCurrency(e.target.value.toUpperCase())
                  }
                />
              </Field>
              <Field label="Current period">
                <Select
                  value={currentPeriod}
                  onChange={(e) => setCurrentPeriod(e.target.value)}
                >
                  <option value="year">Per year</option>
                  <option value="month">Per month</option>
                  <option value="hour">Per hour</option>
                </Select>
              </Field>
              <Field label="Current kind">
                <Select
                  value={currentKind}
                  onChange={(e) => setCurrentKind(e.target.value)}
                >
                  <option value="ctc">CTC</option>
                  <option value="base_salary">Base salary</option>
                  <option value="total_compensation">Total compensation</option>
                </Select>
              </Field>
            </div>

            <div className="form-grid spaced">
              <Field label="Expected amount">
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={expectedAmount}
                  onChange={(e) => setExpectedAmount(e.target.value)}
                  placeholder="Leave blank if unknown"
                />
              </Field>
              <Field label="Expected currency">
                <Input
                  maxLength={3}
                  value={expectedCurrency}
                  onChange={(e) =>
                    setCurrentCurrency(e.target.value.toUpperCase())
                  }
                />
              </Field>
              <Field label="Expected period">
                <Select
                  value={expectedPeriod}
                  onChange={(e) => setExpectedPeriod(e.target.value)}
                >
                  <option value="year">Per year</option>
                  <option value="month">Per month</option>
                  <option value="hour">Per hour</option>
                </Select>
              </Field>
              <Field label="Expected kind">
                <Select
                  value={expectedKind}
                  onChange={(e) => setExpectedKind(e.target.value)}
                >
                  <option value="ctc">CTC</option>
                  <option value="base_salary">Base salary</option>
                  <option value="total_compensation">Total compensation</option>
                </Select>
              </Field>
            </div>
          </fieldset>

          <label
            className="check-label"
            htmlFor={`confirm-truthful-${confirmationId}`}
          >
            <input
              id={`confirm-truthful-${confirmationId}`}
              type="checkbox"
              checked={confirmedTruthful}
              onChange={(e) => setConfirmedTruthful(e.target.checked)}
            />
            I confirm these facts are truthful, verified, and represent my
            actual candidate background.
          </label>

          {saveFactsMutation.isError && (
            <ErrorState error={saveFactsMutation.error} />
          )}

          <div className="actions">
            <Button
              type="submit"
              variant="primary"
              disabled={!confirmedTruthful || saveFactsMutation.isPending}
              busy={saveFactsMutation.isPending}
            >
              <Save size={13} />
              Save and approve version {p.version + 1}
            </Button>
            <Button variant="ghost" onClick={() => setActiveTab("approved")}>
              Cancel edits
            </Button>
          </div>
        </form>
      )}

      {/* TAB 3: PROJECTS & ACHIEVEMENTS */}
      {activeTab === "projects" && (
        <section className="panel panel-body stack">
          <div className="split">
            <div>
              <h3>Real Projects & Achievements</h3>
              <p className="section-intro">
                Evidence-backed engineering projects. Every project can be
                referenced in application answers and technical packets.
              </p>
            </div>
            <Button variant="primary" onClick={handleOpenAddProject}>
              <Plus size={14} />
              Add project
            </Button>
          </div>

          {projectsList.length === 0 ? (
            <Empty
              title="No projects added yet"
              description="Add your key software engineering projects, measurable achievements, and repositories to support answer generation."
              action={
                <Button variant="primary" onClick={handleOpenAddProject}>
                  <Plus size={14} />
                  Add first project
                </Button>
              }
            />
          ) : (
            <div className="company-grid" role="list">
              {projectsList.map((proj, idx) => (
                <article className="company-card" key={idx} role="listitem">
                  <div className="company-top">
                    <span className="row-icon">
                      <FolderGit2 size={18} />
                    </span>
                    <div>
                      <h4>{proj.name}</h4>
                      {proj.contribution && (
                        <p className="muted">{proj.contribution}</p>
                      )}
                    </div>
                  </div>

                  <p className="company-description preserve-lines">
                    {proj.description}
                  </p>

                  {proj.measurable_results && (
                    <div
                      className="notice"
                      style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}
                    >
                      <strong>Measurable Impact:</strong>{" "}
                      {proj.measurable_results}
                    </div>
                  )}

                  <div className="tag-list" style={{ marginTop: "0.5rem" }}>
                    {(proj.technologies || []).map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </div>

                  <div className="actions" style={{ marginTop: "1rem" }}>
                    {proj.url && (
                      <External href={proj.url}>Project link</External>
                    )}
                    <Button onClick={() => handleOpenEditProject(idx)}>
                      <Edit3 size={12} />
                      Edit
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => handleDeleteProject(idx)}
                    >
                      <Trash2 size={12} />
                      Remove
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}

          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmedTruthful}
              onChange={(event) => setConfirmedTruthful(event.target.checked)}
            />
            I confirm these project changes are truthful and supported by my own
            work.
          </label>
          <div className="actions spaced">
            <Button
              variant="primary"
              disabled={!confirmedTruthful}
              onClick={() => saveFactsMutation.mutate()}
              busy={saveFactsMutation.isPending}
            >
              <Save size={13} />
              Save project changes to profile
            </Button>
          </div>
          {saveFactsMutation.isError && (
            <ErrorState error={saveFactsMutation.error} />
          )}
        </section>
      )}

      {/* TAB 4: VERIFIED LINKS & EVIDENCE */}
      {activeTab === "links" && (
        <div className="detail-grid">
          <section className="panel panel-body stack">
            <h3>Professional Profiles & Portfolios</h3>
            <p className="section-intro">
              Public links must be HTTPS and verified before being cited in
              applications.
            </p>

            <div className="form-grid">
              <Field label="GitHub URL">
                <Input
                  type="url"
                  value={githubUrl}
                  onChange={(e) => {
                    setGithubUrl(e.target.value);
                    setConfirmedTruthful(false);
                  }}
                  placeholder="https://github.com/username"
                />
              </Field>

              <Field label="LinkedIn profile URL">
                <Input
                  type="url"
                  value={linkedinUrl}
                  onChange={(e) => {
                    setLinkedinUrl(e.target.value);
                    setConfirmedTruthful(false);
                  }}
                  placeholder="https://linkedin.com/in/username"
                />
              </Field>

              <Field label="Portfolio URL">
                <Input
                  type="url"
                  value={portfolioUrl}
                  onChange={(e) => {
                    setPortfolioUrl(e.target.value);
                    setConfirmedTruthful(false);
                  }}
                  placeholder="https://yourportfolio.dev"
                />
              </Field>

              <Field label="Personal website">
                <Input
                  type="url"
                  value={personalWebsite}
                  onChange={(e) => {
                    setPersonalWebsite(e.target.value);
                    setConfirmedTruthful(false);
                  }}
                  placeholder="https://yourdomain.com"
                />
              </Field>
            </div>

            <label className="check-label">
              <input
                type="checkbox"
                checked={confirmedTruthful}
                onChange={(event) => setConfirmedTruthful(event.target.checked)}
              />
              I confirm these links are mine and accurately represent my
              profile.
            </label>
            {saveFactsMutation.isError && (
              <ErrorState error={saveFactsMutation.error} />
            )}
            <div className="actions">
              <Button
                variant="primary"
                disabled={!confirmedTruthful}
                onClick={() => saveFactsMutation.mutate()}
                busy={saveFactsMutation.isPending}
              >
                <Save size={13} />
                Save links
              </Button>
            </div>
          </section>

          <aside className="panel panel-body stack">
            <h3>
              Verified Candidate Resources (
              {resourcesQuery.data?.resources?.length || 0})
            </h3>
            <p className="section-intro">
              Evidence artifacts stored in candidate knowledge repository.
            </p>

            {resourcesQuery.isPending && <Skeleton />}

            {resourcesQuery.data?.resources?.map((res) => (
              <div className="evidence-item" key={res.id}>
                <div className="split">
                  <strong>{res.label}</strong>
                  <Badge tone={res.user_confirmed ? "green" : "neutral"}>
                    {readable(res.resource_type)}
                  </Badge>
                </div>
                <External href={res.url}>{res.url}</External>
                <small className="muted">
                  Added {dateLabel(res.created_at)}
                </small>
              </div>
            ))}
          </aside>
        </div>
      )}

      {/* TAB 5: APPROVED REUSABLE ANSWERS */}
      {activeTab === "answers" && (
        <section className="panel panel-body stack">
          <div className="split">
            <div>
              <h3>Saved Answer Drafts ({answers.length})</h3>
              <p className="section-intro">
                Saved drafts and reviewed answers. Broader reuse requires a
                separate current approval; exact-context approvals do not create
                general profile facts.
              </p>
            </div>
          </div>

          {savedAnswersQuery.isError && (
            <ErrorState error={savedAnswersQuery.error} />
          )}
          {reuseBank.isError && <ErrorState error={reuseBank.error} />}
          {answers.length === 0 ? (
            <Empty
              title="No saved answers yet"
              description="Saved answer drafts and exact-context approvals appear here with their actual review status."
            />
          ) : (
            <div className="stack spaced" role="list">
              {answers.map((draft) => (
                <article
                  className="panel panel-body"
                  key={draft.id}
                  role="listitem"
                >
                  <div className="split">
                    <strong>{draft.question}</strong>
                    <Badge tone={draft.stale ? "amber" : "neutral"}>
                      {draft.stale
                        ? "Profile facts updated · Review required"
                        : readable(draft.review_status)}
                    </Badge>
                  </div>
                  <p className="preserve-lines" style={{ marginTop: "0.5rem" }}>
                    {draft.answer}
                  </p>
                  <div
                    className="split"
                    style={{
                      fontSize: "0.8rem",
                      color: "var(--muted)",
                      marginTop: "0.5rem",
                    }}
                  >
                    <span>Category: {readable(draft.question_category)}</span>
                    <span>
                      {!draft.stale &&
                      reuseBank.data?.enabled &&
                      reuseBank.data.approvals?.[draft.id]?.approved
                        ? `Reuse approved: ${readable(reuseBank.data.approvals[draft.id].scope)}`
                        : "No broader reuse approval"}
                    </span>
                    <span>
                      Recorded for Profile v{draft.candidate_profile_version}
                    </span>
                    <span>
                      {draft.evidence_references.length} evidence citation(s)
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Project Add/Edit Modal */}
      <Modal
        open={projectModalOpen}
        onOpenChange={setProjectModalOpen}
        title={editingProjectIndex !== null ? "Edit Project" : "Add Project"}
        description="Provide truthful engineering details. These can be cited as factual evidence in answer generation."
      >
        <div className="stack">
          <Field label="Project title" hint="e.g. Real-Time Distributed Cache">
            <Input
              value={projectTitle}
              onChange={(e) => setProjectTitle(e.target.value)}
              required
            />
          </Field>

          <Field
            label="Your role"
            hint="e.g. Lead Backend Engineer / Solo Creator"
          >
            <Input
              value={projectRole}
              onChange={(e) => setProjectRole(e.target.value)}
            />
          </Field>

          <Field
            label="Project description"
            hint="What does the system do? Architecture and mechanics"
          >
            <textarea
              className="input preserve-lines"
              rows={3}
              value={projectDesc}
              onChange={(e) => setProjectDesc(e.target.value)}
              required
            />
          </Field>

          <Field
            label="Measurable impact / Achievements"
            hint="e.g. Reduced latency by 45%, handled 10k req/s"
          >
            <Input
              value={projectImpact}
              onChange={(e) => setProjectImpact(e.target.value)}
            />
          </Field>

          <Field
            label="Technologies used"
            hint="Comma-separated (e.g. Go, Redis, Docker, gRPC)"
          >
            <Input
              value={projectTech}
              onChange={(e) => setProjectTech(e.target.value)}
            />
          </Field>

          <Field label="Repository or Demo URL" hint="Public HTTPS link">
            <Input
              type="url"
              value={projectUrl}
              onChange={(e) => setProjectUrl(e.target.value)}
            />
          </Field>

          <div className="actions">
            <Button
              variant="primary"
              onClick={handleSaveProject}
              disabled={!projectTitle || !projectDesc}
            >
              {editingProjectIndex !== null ? "Update project" : "Add project"}
            </Button>
            <Button variant="ghost" onClick={() => setProjectModalOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
