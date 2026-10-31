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
  const band = experience?.match(
    /^(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?)$/i,
  );
  const description = clean(
    document.querySelector(
      '[class*="job-desc"], [class*="jobDesc"], [itemprop="description"]',
    ),
  );
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
    !band ||
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
    experience_min: Number(band[1]),
    experience_max: Number(band[2]),
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
