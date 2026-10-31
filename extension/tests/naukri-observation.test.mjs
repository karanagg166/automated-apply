import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { observeNaukri } from "../naukri-observation.js";

const url = "https://www.naukri.com/job-listings-fictional-291026123456";
function html({
  count = "120 Applicants",
  date = "2026-10-31T00:00:00Z",
  title = "Backend Developer",
  status = "Apply",
  description = "Build Python services",
} = {}) {
  return `<div class="styles_jd-header"><h1>Backend Developer</h1><a class="styles_comp-name">Fictional Labs</a><span class="styles_loc-wrap">India</span><span class="styles_exp-wrap">0 - 3 Yrs</span><span>${count}</span><button>${status}</button></div><div class="styles_job-desc">${description}</div><div class="styles_key-skill"><span class="chip">Python</span></div><script type="application/ld+json">${JSON.stringify({ "@type": "JobPosting", title, datePosted: date, identifier: { value: "291026123456" } })}</script>`;
}
async function observe(
  body,
  {
    operation = "inspect_job",
    actual = url,
    expected = url,
    visible = false,
  } = {},
) {
  const dom = new JSDOM(body, { url: actual, runScripts: "outside-only" });
  const w = dom.window;
  Object.defineProperty(w.document, "visibilityState", {
    value: visible ? "visible" : "hidden",
  });
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.TextEncoder = TextEncoder;
  Object.defineProperty(w.document.body, "innerText", {
    get() {
      return this.textContent;
    },
  });
  try {
    return JSON.parse(
      JSON.stringify(
        await w.eval(
          `(${observeNaukri.toString()})(${JSON.stringify(expected)}, ${JSON.stringify(operation)})`,
        ),
      ),
    );
  } finally {
    w.close();
  }
}
test("fictional exact listing yields factual bounds and source digest without clicking", async () => {
  const report = await observe(html());
  assert.equal(report.kind, "job_facts");
  assert.equal(report.job.company, "Fictional Labs");
  assert.equal(report.job.applicants_min, 120);
  assert.equal(report.job.applicants_max, 120);
  assert.equal(report.job.experience_min, 0);
  assert.equal(report.job.experience_max, 3);
  assert.match(report.job.evidence_sha256, /^[a-f0-9]{64}$/);
});
for (const [label, expected] of [
  ["10,000+ Applicants", [10000, null]],
  ["100–200 Applicants", [100, 200]],
  ["No applicant count provided", [null, null]],
  ["Applicants: Less than 10", [0, 9]],
  ["Fewer than 10 Applicants", [0, 9]],
  ["Applicants: Less than 10,000", [0, 9999]],
  ["Applicants: Less than 0", [null, null]],
  ["Applicants: Less than 10+", [null, null]],
  ["Applicants: Less than 10–20", [null, null]],
]) {
  test(`applicant label ${label} preserves its uncertainty`, async () => {
    const report = await observe(html({ count: label }));
    assert.deepEqual(
      [report.job.applicants_min, report.job.applicants_max],
      expected,
    );
  });
}
test("conflicting applicant labels remain unknown rather than choosing the lowest", async () => {
  const report = await observe(
    html({ count: "Applicants: Less than 10</span><span>120 Applicants" }),
  );
  assert.deepEqual(
    [report.job.applicants_min, report.job.applicants_max],
    [null, null],
  );
});
for (const [name, body, options, reason] of [
  ["active owner tab", html(), { visible: true }, "owner_tab_active"],
  [
    "navigation",
    html(),
    { actual: url + "-other" },
    "provider_navigation_changed",
  ],
  [
    "invalid date",
    html({ date: "2026-02-31" }),
    {},
    "posting_timestamp_unknown",
  ],
  [
    "ambiguous title",
    html({ title: "Another job" }),
    {},
    "structured_job_identity_ambiguous",
  ],
  [
    "challenge",
    html({ description: "Verify you are human" }),
    {},
    "provider_challenge_requires_owner",
  ],
]) {
  test(`${name} safely requires input`, async () => {
    assert.equal((await observe(body, options)).reason, reason);
  });
}
test("already applied is an exclusion observation, not a new submission receipt", async () => {
  const report = await observe(html({ status: "Applied" }));
  assert.equal(report.stage, "ALREADY_APPLIED");
  assert.equal(report.receipt, undefined);
});
test("search returns unique canonical posting links only and never invents job facts", async () => {
  const search = "https://www.naukri.com/backend-developer-jobs";
  const report = await observe(
    `<a href="${url}?source=alert">job</a><a href="${url}">same</a><a href="https://evil.example/job-listings-fictional-291026123456">external</a>`,
    { operation: "search_jobs", actual: search, expected: search },
  );
  assert.deepEqual(report.candidates, [url]);
  assert.equal(report.job, undefined);
});

test("calendar date is retained without inventing a timestamp or timezone", async () => {
  const report = await observe(html({ date: "2026-10-31" }));
  assert.equal(report.job.posted_at, null);
  assert.equal(report.job.posted_date, "2026-10-31");
});
test("current public layout reads the full header and excludes ratings/sticky duplicates", async () => {
  const body =
    html()
      .replace(
        '<div class="styles_jd-header">',
        '<section id="job_header" class="styles_job-header-container">',
      )
      .replace("<h1>", '<h1 class="styles_jd-header-title">')
      .replace(
        '<a class="styles_comp-name">Fictional Labs</a>',
        '<div class="styles_jd-header-comp-name"><a>Fictional Labs</a><div>3.9 95 Reviews</div></div>',
      )
      .replace("styles_exp-wrap", "styles_jhc__exp__abc")
      .replace(
        '<span class="styles_loc-wrap">India</span>',
        '<div class="styles_jhc__loc___Du2H"><i class="ni-icon-location"></i><span class="styles_jhc__location__W_pVs"><a>India</a></span></div>',
      )
      .replace("0 - 3 Yrs", "0 - 3 years")
      .replace("120 Applicants", "<label>Applicants: </label><span>120</span>")
      .replace("</button></div>", "</button></section>") +
    '<div class="sticky"><h1 class="styles_jd-header-title">Backend Developer</h1></div>';
  const report = await observe(body);
  assert.equal(report.kind, "job_facts");
  assert.equal(report.job.company, "Fictional Labs");
  assert.equal(report.job.location, "India");
  assert.equal(report.job.applicants_max, 120);
});

test("an empty location icon alone never establishes a job location", async () => {
  const body = html().replace(
    '<span class="styles_loc-wrap">India</span>',
    '<i class="ni-icon-location"></i>',
  );
  assert.equal((await observe(body)).reason, "job_required_facts_unrecognized");
});
