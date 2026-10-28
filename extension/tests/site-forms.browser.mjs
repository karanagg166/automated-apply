// Real Chromium with intercepted fictional ATS-style forms. No live site claim.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";
const sites = [
  ["naukri_fictional", "https://www.naukri.com/job-listings-fictional-backend-281026123456"],
  ["greenhouse", "https://job-boards.greenhouse.io/fictional/jobs/12345"],
  ["lever", "https://jobs.lever.co/fictional/fictional-job-123/apply"],
  ["ashby", "https://jobs.ashbyhq.com/fictional/fictional-job-123/application"],
  ["workday", "https://fictional.wd5.myworkdayjobs.com/en-US/External/job/India/Engineer_R123"],
  ["smartrecruiters", "https://jobs.smartrecruiters.com/Fictional/12345678-engineer?oga=true"],
  ["generic", "https://fictional-employer.example/careers/apply"],
  ["google_forms", "https://docs.google.com/forms/d/e/fictional/viewform"],
];
const browser = await chromium.launch({ headless: true });
let mutations = 0, cases = 0;
try {
  for (const [site, url] of sites) {
    const page = await browser.newPage();
    await page.route("**/*", route => {
      if (route.request().method() !== "GET") mutations++;
      return route.fulfill({ contentType: "text/html", body: `<h1>Fictional ${site} application</h1>
        <form id="application"><div data-automation-id="legalNameSection">
        <label for="name">Full name</label><input id="name" required data-automation-id="legalNameSection_firstName">
        </div><label>Email<input id="email" type="email" value="owner-entered@example.com"></label>
        <label>Relevant project<textarea id="project"></textarea></label>
        <label>Work arrangement<select id="arrangement"><option value="">Choose one</option><option>Remote</option><option>Hybrid</option></select></label>
        <fieldset><legend>Available shift</legend><label>Day<input type="radio" name="shift" value="day"></label><label>Night<input type="radio" name="shift" value="night"></label></fieldset>
        <label>Python skill<input type="checkbox" id="python"></label>
        <label>Upload resume<input type="file" accept="application/pdf"></label>
        <label>Gender<select><option value="">Choose one</option><option>Prefer not to say</option></select></label>
        <label>I agree to privacy terms<input id="consent" type="checkbox"></label>
        <div role="combobox" aria-label="City" aria-expanded="false" tabindex="0">Choose city</div>
        <button type="button" id="next">Next</button><button type="submit">Submit</button></form>
        <script>window.submits=0;window.nexts=0;document.querySelector('form').onsubmit=e=>{window.submits++;e.preventDefault()};document.querySelector('#next').onclick=()=>{window.nexts++;document.querySelector('h1').textContent='Review next page'};</script>` });
    });
    await page.goto(url);
    const initial = await page.evaluate(formDOM, { operation: "inspect", only_empty: true });
    assert.equal(initial.state, "ready", site);
    assert.ok(initial.unsupported_controls.some(x => x.kind === "custom_combobox"), site);
    assert.ok(initial.unsupported_controls.some(x => /self-identification/.test(x.reason)), site);
    assert.equal(initial.fields.some(x => x.label === "Email"), false, "existing value must not enter an unanswered plan");
    const values = { "Full name": "Alex Fictional", "Relevant project": "An owner-approved fictional project.", "Work arrangement": "Remote", Day: "true", "Python skill": "true", "I agree to privacy terms": "true" };
    const actions = initial.fields.filter(x => x.label in values).map(x => ({ field_id: x.field_id, kind: x.kind, value: values[x.label] }));
    const result = await page.evaluate(formDOM, { operation: "fill", document_id: initial.document_id, actions, only_empty: true });
    assert.equal(result.submitted, false);
    assert.equal(await page.locator("#name").inputValue(), "Alex Fictional");
    assert.equal(await page.locator("#email").inputValue(), "owner-entered@example.com");
    assert.equal(await page.locator("#arrangement").inputValue(), "Remote");
    assert.equal(await page.locator('input[value="day"]').isChecked(), true);
    assert.equal(await page.locator("#python").isChecked(), true);
    assert.equal(await page.locator("#consent").isChecked(), false);
    assert.equal(await page.locator("input[type=file]").evaluate(el => el.files.length), 0);
    assert.equal(await page.evaluate(() => window.nexts), 0, "fill must not advance");
    const replay = await page.evaluate(formDOM, { operation: "fill", document_id: initial.document_id, actions, only_empty: true });
    assert.equal(replay.state, "manual_required", "one-shot authorization");
    await page.reload();
    const stale = await page.evaluate(formDOM, { operation: "fill", document_id: initial.document_id, actions });
    assert.equal(stale.state, "manual_required", "refresh requires new inspection/review");
    assert.equal(await page.evaluate(() => window.submits), 0);
    await page.close();
    cases++;
  }
  assert.equal(mutations, 0);
  console.log(JSON.stringify({ fixture_sites_passed: cases, sites: sites.map(x => x[0]), live_sites_tested: 0, submitted: false, form_posts: mutations }));
} finally { await browser.close(); }
