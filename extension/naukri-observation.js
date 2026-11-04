// Read-only isolated-world adapter. No clicks, typing, uploads, provider fetches
// or page-world bridge. A supported layout is observed, never presumed.
export async function observeNaukri(expectedUrl, operation) {
  const failure = (reason) => ({ kind: "needs_input", reason });
  const url = new URL(location.href);
  const expected = new URL(expectedUrl);
  if (document.visibilityState !== "hidden") return failure("owner_tab_active");
  if (
    url.origin !== "https://www.naukri.com" ||
    url.pathname !== expected.pathname
  )
    return failure("provider_navigation_changed");
  if (
    /captcha|verify (?:that )?you are human|unusual traffic|access denied/i.test(
      document.body?.innerText || "",
    ) ||
    [...document.querySelectorAll('iframe[src*="captcha"]')].some(
      (e) => e.getClientRects().length,
    )
  )
    return failure("provider_challenge_requires_owner");
  if (operation === "search_jobs") {
    const candidates = [
      ...new Set(
        [...document.querySelectorAll('a[href*="/job-listings-"]')]
          .map((a) => {
            try {
              const u = new URL(a.href);
              return u.origin === url.origin &&
                /^\/job-listings-[a-zA-Z0-9%_-]+-\d{10,20}\/?$/.test(u.pathname)
                ? u.origin + u.pathname.replace(/\/$/, "")
                : null;
            } catch {
              return null;
            }
          })
          .filter(Boolean),
      ),
    ].slice(0, 20);
    if (
      !candidates.length &&
      !/no jobs found|no results found/i.test(document.body?.innerText || "")
    )
      return failure("search_layout_unrecognized");
    return { kind: "source_candidates", observed_url: expectedUrl, candidates };
  }
  const requisition = url.pathname.match(/-(\d{10,20})\/?$/)?.[1];
  if (!requisition) return failure("provider_job_identity_missing");
  // Current Naukri classes put "jd-header" on the title and company too.
  // Anchor the full listing container; never use a sticky duplicate or the
  // first title-shaped descendant as the application header.
  const modern = [...document.querySelectorAll("#job_header")];
  const legacy = [
    ...document.querySelectorAll('[class*="jd-header"], [class*="jdHeader"]'),
  ].filter(
    (e) =>
      e.querySelectorAll("h1").length === 1 &&
      e.querySelector('[class*="comp-name"], [class*="compName"]'),
  );
  const headers = modern.length ? modern : legacy;
  const header = headers.length === 1 && headers[0];
  if (!header) return failure("job_header_unrecognized");
  const status = [...header.querySelectorAll("button, [role=button]")].some(
    (e) => /^(already applied|applied)$/i.test(e.textContent.trim()),
  );
  if (status)
    return {
      kind: "application_view",
      stage: "ALREADY_APPLIED",
      requisition,
      observed_url: expectedUrl,
    };
  const clean = (x) => x?.textContent?.replace(/\s+/g, " ").trim();
  const title = clean(header.querySelector("h1"));
  const company = clean(
    header.querySelector('[class*="comp-name"] > a, [class*="compName"] > a') ||
      header.querySelector('[class*="comp-name"], [class*="compName"]'),
  );
  const locationText = clean(
    header.querySelector(
      '[class*="jhc__location__"], [class*="loc-wrap"], [class*="location"]:not(i)',
    ),
  );
  const experience = clean(
    header.querySelector(
      '[class*="jhc__exp__"], [class*="exp-wrap"], [class*="experience"]',
    ),
  );
  const range = experience?.match(
    /^(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?)$/i,
  );
  const single = experience?.match(/^(\d+(?:\.\d+)?)\s*(?:yrs?|years?)$/i);
  // Genuine fresher headers display "0 years" rather than a range. Preserve
  // that explicit value; "Fresher", "0+" and unspecified ranges stay unknown.
  const band = range || (single && [single[0], single[1], single[1]]);
  // Actual internship headers put a placement duration in the same slot as
  // regular jobs' work experience. Duration cannot supply experience bounds.
  const internshipDuration =
    /^(?:\d+(?:\.\d+)? months? duration|No fixed duration)$/i.test(
      experience || "",
    ) &&
    [...header.querySelectorAll('[class*="internship-label"]')].some(
      (e) => clean(e) === "Internship",
    );
  // The current outer job-desc-container also contains highlights, platform
  // match scores, skills, education and sharing controls. Keep the employer's
  // actual description separate from that surrounding UI when present.
  const descriptionBodies = [
    ...document.querySelectorAll('[class*="JDC__dang-inner-html__"]'),
  ];
  if (descriptionBodies.length > 1) return failure("job_description_ambiguous");
  const descriptionElement =
    descriptionBodies[0] ||
    document.querySelector(
      '[class*="job-desc"], [class*="jobDesc"], [itemprop="description"]',
    );
  const prose = (node) => {
    if (!node) return "";
    if (node.nodeType === 3) return node.textContent;
    if (/^(SCRIPT|STYLE|TEMPLATE)$/.test(node.nodeName)) return "";
    const value = [...node.childNodes].map(prose).join("");
    return /^(P|DIV|BR|LI|H[1-6]|UL|OL|TABLE|TR|TD|SECTION)$/.test(
      node.nodeName,
    )
      ? " " + value + " "
      : value;
  };
  const description = prose(descriptionElement).replace(/\s+/g, " ").trim();
  const skills = [
    ...new Set(
      [
        ...document.querySelectorAll(
          '[class*="key-skill"] [class*="chip"], [class*="keySkill"] [class*="chip"]',
        ),
      ]
        .map(clean)
        .filter(Boolean),
    ),
  ];
  if (
    !title ||
    !company ||
    !locationText ||
    (!band && !internshipDuration) ||
    !description ||
    !skills.length
  )
    return failure("job_required_facts_unrecognized");
  let postings = [];
  const visit = (v) => {
    if (Array.isArray(v)) return v.forEach(visit);
    if (!v || typeof v !== "object") return;
    if ([v["@type"]].flat().includes("JobPosting")) postings.push(v);
    if (v["@graph"]) visit(v["@graph"]);
  };
  for (const e of document.querySelectorAll(
    'script[type="application/ld+json"]',
  )) {
    try {
      visit(JSON.parse(e.textContent));
    } catch {
      /* Unknown structured data is not fabricated. */
    }
  }
  postings = postings.filter(
    (v) => String(v.title).replace(/\s+/g, " ").trim() === title,
  );
  if (postings.length !== 1)
    return failure("structured_job_identity_ambiguous");
  const posting = postings[0];
  const posted = posting.datePosted;
  const dateOnly =
    typeof posted === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(posted) &&
    Number.isFinite(Date.parse(posted)) &&
    new Date(posted).toISOString().slice(0, 10) === posted;
  const exact =
    typeof posted === "string" &&
    /T.*(?:Z|[+-]\d\d:\d\d)$/.test(posted) &&
    Number.isFinite(Date.parse(posted));
  if (!dateOnly && !exact) return failure("posting_timestamp_unknown");
  if (
    posting.identifier?.value &&
    String(posting.identifier.value) !== requisition
  )
    return failure("structured_job_identity_ambiguous");
  const minimumMonths = posting.experienceRequirements?.monthsOfExperience;
  let minimumYears = band ? Number(band[1]) : null;
  if (minimumMonths !== undefined && minimumMonths !== null) {
    const numeric =
      typeof minimumMonths === "number" ||
      (typeof minimumMonths === "string" &&
        /^\d+(?:\.\d+)?$/.test(minimumMonths.trim()));
    const months = numeric ? Number(minimumMonths) : NaN;
    if (!Number.isFinite(months) || months < 0 || months > 720)
      return failure("structured_experience_requires_review");
    // monthsOfExperience is a minimum. The genuine "0 years" headers can
    // contradict a one-month minimum; never choose the easier requirement.
    if (band && months > Number(band[2]) * 12)
      return failure("experience_requirement_evidence_conflict");
    // A compatible structured minimum still constrains the advertised range.
    // Zero verified years cannot satisfy an explicit one-month minimum.
    minimumYears = Math.max(minimumYears ?? 0, months / 12);
  }
  if (minimumYears === null)
    return failure("verified_experience_requirements_required");
  const employment = (value) =>
    typeof value === "string"
      ? {
          "full time": "full_time",
          "full time, permanent": "full_time",
          full_time: "full_time",
          "part time": "part_time",
          part_time: "part_time",
          contract: "contract",
          contractual: "contract",
          internship: "internship",
        }[value.replace(/\s+/g, " ").trim().toLowerCase()]
      : undefined;
  const employmentLabels = [posting.employmentType].flat();
  const employmentTypes = employmentLabels.map(employment);
  const structuredEmployment =
    employmentTypes.length &&
    employmentTypes.every(Boolean) &&
    new Set(employmentTypes).size === 1
      ? employmentTypes[0]
      : null;
  const details = descriptionElement?.closest('[class*="job-desc-container"]');
  const uiEmploymentLabels = details
    ? [
        ...details.querySelectorAll(
          '[class*="other-details"] [class*="details"]',
        ),
      ]
        .filter(
          (row) =>
            clean(row.querySelector("label"))
              ?.replace(/\s*:\s*$/, "")
              .toLowerCase() === "employment type",
        )
        .map((row) => clean(row.querySelector(":scope > span")))
    : [];
  const uiEmploymentTypes = uiEmploymentLabels.map(employment);
  const uiEmployment =
    uiEmploymentTypes.length &&
    uiEmploymentTypes.every(Boolean) &&
    new Set(uiEmploymentTypes).size === 1
      ? uiEmploymentTypes[0]
      : null;
  // A real details label can supply missing structured metadata, but cannot
  // erase contradictory evidence. Ambiguity stays unknown for review.
  const conflict =
    new Set([...employmentTypes, ...uiEmploymentTypes].filter(Boolean)).size >
    1;
  const employmentType =
    conflict ||
    (internshipDuration &&
      structuredEmployment &&
      structuredEmployment !== "internship")
      ? null
      : structuredEmployment || uiEmployment;
  // Only an explicit mode in the observed location label establishes this
  // fact. Title/description keywords and missing labels never imply remote.
  const mode = locationText.match(
    /^(remote|hybrid|onsite|on-site)\s*(?:[-–:]\s*|$)(.*)$/i,
  );
  const workModes = [
    ...header.querySelectorAll('[class*="jhc__wfhmode__"]'),
  ].map(clean);
  const explicitRemote = workModes.length === 1 && workModes[0] === "Remote";
  const remoteConflict =
    explicitRemote && mode && mode[1].toLowerCase() !== "remote";
  const remoteType = remoteConflict
    ? "unknown"
    : mode && !/^(remote|hybrid|onsite|on-site)\b/i.test(mode[2])
      ? mode[1].toLowerCase().replace("on-site", "onsite")
      : explicitRemote
        ? "remote"
        : "unknown";
  let lower = null,
    upper = null;
  const countLabels = [...header.querySelectorAll("span, p")]
    .map(clean)
    .filter(
      (v) =>
        (/^(?:applicants?\s*:?\s*)?[\d,]+\+?(?:\s*(?:-|–|to)\s*[\d,]+)?(?:\s*applicants?)?$/i.test(
          v,
        ) ||
          /^(?:applicants?\s*:?\s*)?(?:less than|fewer than)\s+[\d,]+(?:\s*applicants?)?$/i.test(
            v,
          )) &&
        /applicants?/i.test(v),
    );
  if (countLabels.length === 1) {
    const numbers = countLabels[0]
      .match(/[\d,]+/g)
      ?.map((v) => Number(v.replaceAll(",", "")));
    if (numbers?.length) {
      if (/(?:less than|fewer than)\s+[\d,]+/i.test(countLabels[0])) {
        // This is a provider upper bound, never an invented exact count.
        if (numbers.length === 1 && numbers[0] > 0) {
          lower = 0;
          upper = numbers[0] - 1;
        }
      } else {
        lower = numbers[0];
        upper = countLabels[0].includes("+") ? null : (numbers[1] ?? lower);
      }
    }
  }
  const job = {
    requisition,
    title,
    company,
    location: locationText,
    description: description.slice(0, 20000),
    skills: skills.slice(0, 50),
    experience_min: minimumYears,
    experience_max: band ? Number(band[2]) : null,
    employment_type: employmentType,
    remote_type: remoteType,
    posted_at: exact ? new Date(posted).toISOString() : null,
    posted_date: dateOnly ? posted : null,
    applicants_min: lower,
    applicants_max: upper,
  };
  job.evidence_sha256 = [
    ...new Uint8Array(
      await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(JSON.stringify(job)),
      ),
    ),
  ]
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
  if (document.visibilityState !== "hidden" || location.href !== url.href)
    return failure("provider_context_changed");
  return { kind: "job_facts", observed_url: expectedUrl, requisition, job };
}
