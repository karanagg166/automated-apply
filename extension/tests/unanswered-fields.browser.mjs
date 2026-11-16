import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Actual isolated Chromium; fictional intercepted pages only, no native host or owner data.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";

const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
try {
  const page = await browser.newPage();
  let writes = 0;
  const url =
    "https://fictional-employer.zohorecruit.in/jobs/Careers/123456/Backend-Engineer?source=CareerSite&ref=fixture";

  const pages = new Map();
  pages.set(
    "baseline",
    `
    <form><label>Name<input name="name" value="Owner already answered"></label>
    <label>Email<input type="email" name="email"></label>
    <label>Project explanation<textarea name="project"></textarea></label>
    <label>Expected salary<input name="salary"></label>
    <label>Consent<input name="consent" type="checkbox"></label>
    <button type="submit">Submit application</button></form>
    <script>window.events=[]; for(const name of ['input','change','submit']) document.addEventListener(name,()=>window.events.push(name));</script>`,
  );

  pages.set(
    "zoho-complex",
    `
    <form id="zr-application-form" action="/submit-never" method="post">
      <!-- Already answered text input -->
      <div class="zr-field-row">
        <div class="zr-label">Full Name <span class="zr-mandatory">*</span></div>
        <input type="text" name="full_name" value="Existing Fictional Candidate">
      </div>
      <!-- Empty required text/email/tel/url inputs with Zoho container & aria-labelledby labels -->
      <div class="zr-field-row" data-mandatory="true">
        <div id="lbl-email" class="zr-label">Email Address *</div>
        <input type="email" name="email" aria-labelledby="lbl-email">
      </div>
      <div class="zr-field-row">
        <label class="zr-label">Mobile <span class="zr-mandatory">*</span></label>
        <div class="zr-control"><input type="tel" name="mobile"></div>
      </div>
      <div class="zr-field-row">
        <div class="zr-label">LinkedIn Profile</div>
        <input type="url" name="linkedin" placeholder="https://linkedin.com/in/...">
      </div>
      <!-- Native select with Zoho -None- placeholder (unanswered) -->
      <div class="zr-field-row">
        <div class="zr-label">Notice Period *</div>
        <select name="notice_period">
          <option value="-None-">-None-</option>
          <option value="Immediate">Immediate</option>
          <option value="15 days">15 days</option>
          <option value="30 days">30 days</option>
        </select>
      </div>
      <!-- Native select already answered -->
      <div class="zr-field-row">
        <div class="zr-label">Country</div>
        <select name="country">
          <option value="-None-">-None-</option>
          <option value="India" selected>India</option>
          <option value="Remote">Remote</option>
        </select>
      </div>
      <!-- Multi-select (unsupported) -->
      <div class="zr-field-row">
        <div class="zr-label">Preferred Locations</div>
        <select name="locations" multiple>
          <option value="Bengaluru">Bengaluru</option>
          <option value="Hyderabad">Hyderabad</option>
        </select>
      </div>
      <!-- Unanswered radio group with required constraint -->
      <div class="zr-field-row" role="radiogroup" aria-labelledby="lbl-remote" aria-required="true">
        <div id="lbl-remote" class="zr-label">Remote work preference *</div>
        <div class="zr-radio-item"><input type="radio" name="remote_pref" value="Onsite" required><span>Onsite</span></div>
        <div class="zr-radio-item"><input type="radio" name="remote_pref" value="Remote" required><span>Remote</span></div>
      </div>
      <!-- Already answered radio group -->
      <div class="zr-field-row" role="radiogroup" aria-label="Willing to relocate">
        <label><input type="radio" name="relocate" value="Yes" checked> Yes</label>
        <label><input type="radio" name="relocate" value="No"> No</label>
      </div>
      <!-- Unlabelled radio group -->
      <div class="zr-field-row">
        <label><input type="radio" name="mystery_radio" value="Option A"> Option A</label>
        <label><input type="radio" name="mystery_radio" value="Option B"> Option B</label>
      </div>
      <!-- Unanswered checkbox group -->
      <fieldset>
        <legend>Work shift *</legend>
        <label><input type="checkbox" name="shift" value="Day"> Day</label>
        <label><input type="checkbox" name="shift" value="Flexible"> Flexible</label>
      </fieldset>
      <!-- Already answered checkbox group (one option already checked) -->
      <fieldset>
        <legend>Primary stack</legend>
        <label><input type="checkbox" name="stack" value="Python" checked> Python</label>
        <label><input type="checkbox" name="stack" value="Rust"> Rust</label>
      </fieldset>
      <!-- Consent checkbox inside fieldset (must never auto-check or get executable group_label) -->
      <fieldset>
        <legend>Applicant Declaration</legend>
        <label><input type="checkbox" name="declaration" value="true"> I agree to the privacy policy and background check</label>
      </fieldset>
      <!-- Custom comboboxes (input role=combobox and standalone lyte-dropdown) -->
      <div class="zr-field-row">
        <div id="lbl-city" class="zr-label">Current City *</div>
        <input type="text" name="city_combo" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-labelledby="lbl-city" required>
      </div>
      <div class="zr-field-row">
        <lyte-dropdown role="combobox" aria-label="Department" aria-required="true">
          <span class="lyte-placeholder">-None-</span>
        </lyte-dropdown>
      </div>
      <!-- Date fields (native and text datepicker) -->
      <div class="zr-field-row">
        <label>Available Start Date <input type="date" name="start_date" required></label>
      </div>
      <div class="zr-field-row">
        <div class="zr-label">Date of Birth</div>
        <input type="text" name="dob" placeholder="DD/MM/YYYY" class="zr-datepicker">
      </div>
      <!-- React / framework-controlled input -->
      <div class="zr-field-row">
        <label>Current CTC <input type="text" name="react_ctc" data-framework-controlled="true"></label>
      </div>
      <!-- Incomplete label field -->
      <div class="zr-field-row">
        <input type="text" name="unlabelled_notes" placeholder="Type here">
      </div>
      <!-- Hidden, collapsed conditional, disabled, and readonly fields -->
      <div class="zr-field-row" hidden>
        <label>Hidden Question <input type="text" name="hidden_q"></label>
      </div>
      <div class="zr-field-row" style="height: 0; overflow: hidden;">
        <label>Collapsed Conditional Question <input type="text" name="collapsed_q"></label>
      </div>
      <div class="zr-field-row" aria-hidden="true">
        <label>Aria Hidden Question <input type="text" name="aria_hidden_q"></label>
      </div>
      <div class="zr-field-row">
        <label>Disabled Requisition ID <input type="text" name="req_id" disabled></label>
        <label>Readonly Role <input type="text" name="ro_role" readonly></label>
      </div>
      <button type="submit">Submit application</button>
    </form>
    <script>window.events=[]; for(const name of ['input','change','submit']) document.addEventListener(name,()=>window.events.push(name));</script>`,
  );

  pages.set(
    "zoho-validation-and-steps",
    `
    <form id="zr-step-form" action="/submit-never" method="post">
      <div id="step-1" class="zr-step-active" data-step="1">
        <div class="zr-field-row">
          <label class="zr-label">Email *</label>
          <input type="email" name="email" class="zr-invalid" required>
          <div class="zr-error" role="alert">Please enter a valid email address</div>
        </div>
        <div class="zr-field-row">
          <label class="zr-label">Years of experience *</label>
          <input type="text" name="exp_years" pattern="[0-9]+" required>
        </div>
        <div id="conditional-block" hidden>
          <label class="zr-label">Current Employer *</label>
          <input type="text" name="employer" required>
        </div>
        <button id="next-btn" type="button" onclick="document.getElementById('step-1').hidden=true; document.getElementById('step-1').classList.remove('zr-step-active'); document.getElementById('step-2').hidden=false; document.getElementById('step-2').classList.add('zr-step-active');">Next</button>
      </div>
      <div id="step-2" data-step="2" hidden>
        <div class="zr-field-row">
          <label class="zr-label">GitHub URL *</label>
          <input type="url" name="github" required>
        </div>
        <div class="zr-field-row">
          <label class="zr-label">Portfolio URL</label>
          <input type="url" name="portfolio">
        </div>
        <button type="submit">Submit application</button>
      </div>
    </form>
    <script>window.events=[]; for(const name of ['input','change','submit']) document.addEventListener(name,()=>window.events.push(name));</script>`,
  );

  pages.set(
    "zoho-cross-origin-frame",
    `
    <form id="zr-framed-form">
      <div class="zr-field-row">
        <label>Email <input type="email" name="email"></label>
      </div>
      <iframe src="https://external-assessment.example.org/widget" title="External Assessment Frame" width="400" height="200"></iframe>
    </form>`,
  );

  pages.set(
    "zoho-sensitive",
    `
    <form id="zr-sensitive-form">
      <label>Full Name <input type="text" name="name" value="Private Name"></label>
      <label>PAN Card Number <input type="text" name="pan_number" value="AAAAA0000A"></label>
      <label>One-Time Password <input type="text" name="otp_code" autocomplete="one-time-code" value="999888"></label>
      <label>Account PIN <input type="text" name="atm_pin" value="7788"></label>
    </form>`,
  );

  pages.set(
    "zoho-adversarial",
    `
    <form id="zr-adversarial-form" action="/submit-never" method="post">
      <!-- Postal PIN code (India Zoho Recruit standard) must NOT trigger sensitive_control -->
      <div class="zr-field-row">
        <label class="zr-label">Postal PIN Code *</label>
        <input type="text" name="pincode" placeholder="Enter 6-digit PIN code" required>
      </div>
      <!-- Select with second option as 'None' (already answered) must NOT be reported as unanswered -->
      <div class="zr-field-row">
        <label class="zr-label">Secondary Language</label>
        <select name="sec_language">
          <option value="">Please select...</option>
          <option value="none" selected>None</option>
          <option value="fr">French</option>
        </select>
      </div>
      <!-- Declaration using 'hereby declare' and 'true and correct' must be treated as consent -->
      <div class="zr-field-row">
        <label><input type="checkbox" name="hereby_dec" value="true"> I hereby declare that the information provided is true and correct</label>
      </div>
      <!-- Sibling label with for attribute pointing to another control must not be adopted -->
      <div class="zr-field-row">
        <input type="checkbox" name="unrelated_peer" id="up1">
        <label for="other-target">Unrelated Sibling Label</label>
        <span id="desc-up1">Actual Option Description</span>
        <input type="text" id="other-target" name="other_target" value="Target Value">
      </div>
      <button type="submit">Submit application</button>
    </form>`,
  );

  let activeFixture = "baseline";
  await page.route("**/*", (route) => {
    const reqUrl = route.request().url();
    if (reqUrl.startsWith("https://external-assessment.example.org/")) {
      return route.fulfill({
        contentType: "text/html",
        body: "<p>Cross-origin assessment widget</p>",
      });
    }
    assert.equal(route.request().method(), "GET");
    return route.fulfill({
      contentType: "text/html",
      body: pages.get(activeFixture),
    });
  });
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) writes += 1;
  });

  const inspect = async () =>
    await page.evaluate(
      `(${formDOM.toString()})({operation:"inspect",only_empty:true})`,
    );
  const runFill = async (request) =>
    await page.evaluate(({ source, req }) => (0, eval)(`(${source})`)(req), {
      source: formDOM.toString(),
      req: request,
    });

  // 1. Baseline test: existing answers, user edit after inspection, consent untouched
  await page.goto(url);
  const snapshot = await inspect();
  assert.equal(
    snapshot.fields.some((field) => field.label === "Name"),
    false,
  );
  assert.equal(
    JSON.stringify(snapshot).includes("Owner already answered"),
    false,
  );
  assert.equal(snapshot.url, url);
  const field = (label) => snapshot.fields.find((item) => item.label === label);
  await page.locator("[name=project]").evaluate((element) => {
    element.value = "Owner typed after inspection";
  });
  const result = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: snapshot.document_id,
    actions: [
      {
        field_id: field("Email").field_id,
        kind: "email",
        value: "alex@example.com",
      },
      {
        field_id: field("Project explanation").field_id,
        kind: "textarea",
        value: "Reviewed fictional project",
      },
    ],
  });
  assert.deepEqual(
    result.results.map((item) => item.status),
    ["filled", "untouched"],
  );
  assert.equal(
    await page.locator("[name=name]").inputValue(),
    "Owner already answered",
  );
  assert.equal(
    await page.locator("[name=email]").inputValue(),
    "alex@example.com",
  );
  assert.equal(
    await page.locator("[name=project]").inputValue(),
    "Owner typed after inspection",
  );
  assert.equal(await page.locator("[name=salary]").inputValue(), "");
  assert.equal(await page.locator("[name=consent]").isChecked(), false);
  assert.deepEqual(await page.evaluate(() => window.events), []);
  assert.equal(writes, 0);
  assert.equal(result.submitted, false);

  // 2. Zoho Recruit complex fixture: labels, required markers, selects, radios, checkboxes, custom comboboxes, dates, framework inputs, hidden/disabled
  activeFixture = "zoho-complex";
  await page.goto(url);
  const zohoSnap = await inspect();
  assert.equal(zohoSnap.state, "ready");
  // No existing candidate values leaked in snapshot
  const serializedZohoSnap = JSON.stringify(zohoSnap);
  assert.equal(
    serializedZohoSnap.includes("Existing Fictional Candidate"),
    false,
  );
  assert.equal(serializedZohoSnap.includes("India"), false);

  const labels = zohoSnap.fields.map((f) =>
    f.group_label ? `${f.group_label}:${f.label}` : f.label,
  );
  assert.deepEqual(labels, [
    "Email Address",
    "Mobile",
    "LinkedIn Profile",
    "Notice Period",
    "Remote work preference:Onsite",
    "Remote work preference:Remote",
    "Work shift:Day",
    "Work shift:Flexible",
    "I agree to the privacy policy and background check",
    "Available Start Date",
    "Current CTC",
  ]);

  // Verify required detection from Zoho mandatory markers
  const findZohoField = (lbl, grp = null) =>
    zohoSnap.fields.find(
      (f) => f.label === lbl && (grp === null || f.group_label === grp),
    );
  assert.equal(findZohoField("Email Address").required, true);
  assert.equal(findZohoField("Mobile").required, true);
  assert.equal(findZohoField("LinkedIn Profile").required, false);
  assert.equal(findZohoField("Notice Period").required, true);
  assert.equal(
    findZohoField("Remote", "Remote work preference").required,
    true,
  );
  // Consent checkbox inside fieldset must have group_label === null
  const declarationField = findZohoField(
    "I agree to the privacy policy and background check",
  );
  assert.equal(declarationField.group_label, null);

  // Verify unsupported controls are accurately reported with reasons
  const unsupportedKinds = zohoSnap.unsupported_controls.map(
    (u) => `${u.kind}:${u.label}`,
  );
  assert.ok(unsupportedKinds.includes("custom_combobox:Department"));
  assert.ok(unsupportedKinds.includes("custom_combobox:Current City"));
  assert.equal(findZohoField("Available Start Date").kind, "date");
  assert.ok(unsupportedKinds.includes("text:Date of Birth"));
  assert.equal(
    zohoSnap.unsupported_controls.find((u) => u.label === "Date of Birth")
      .reason,
    "Sensitive self-identification requires manual entry",
  );
  assert.equal(findZohoField("Date of Birth"), undefined);
  assert.equal(findZohoField("Current CTC").preview_only, true);
  assert.ok(unsupportedKinds.includes("text:Type here"));
  assert.ok(unsupportedKinds.includes("radio:Option A"));
  assert.ok(unsupportedKinds.includes("select:Preferred Locations"));

  // Simulate trusted user typing into LinkedIn Profile after preparation
  await page
    .locator("[name=linkedin]")
    .fill("https://linkedin.com/in/owner-live-edit");
  await page.evaluate(() => {
    window.events = [];
  });

  // Fill supported fields, including radio group ("false" before "true"), checkbox group, native select, and verify consent & user-edited fields stay untouched
  const zohoFill = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: zohoSnap.document_id,
    actions: [
      {
        field_id: findZohoField("Email Address").field_id,
        kind: "email",
        value: "alex@example.com",
      },
      {
        field_id: findZohoField("Mobile").field_id,
        kind: "tel",
        value: "+919876543210",
      },
      {
        field_id: findZohoField("LinkedIn Profile").field_id,
        kind: "url",
        value: "https://linkedin.com/in/prepared-value",
      },
      {
        field_id: findZohoField("Notice Period").field_id,
        kind: "select",
        value: "30 days",
      },
      {
        field_id: findZohoField("Onsite", "Remote work preference").field_id,
        kind: "radio",
        value: "false",
      },
      {
        field_id: findZohoField("Remote", "Remote work preference").field_id,
        kind: "radio",
        value: "true",
      },
      {
        field_id: findZohoField("Day", "Work shift").field_id,
        kind: "checkbox",
        value: "false",
      },
      {
        field_id: findZohoField("Flexible", "Work shift").field_id,
        kind: "checkbox",
        value: "true",
      },
      {
        field_id: declarationField.field_id,
        kind: "checkbox",
        value: "true",
      },
    ],
  });

  const statusById = Object.fromEntries(
    zohoFill.results.map((r) => [r.field_id, r.status]),
  );
  assert.equal(statusById[findZohoField("Email Address").field_id], "filled");
  assert.equal(statusById[findZohoField("Mobile").field_id], "filled");
  assert.equal(
    statusById[findZohoField("LinkedIn Profile").field_id],
    "untouched",
  );
  assert.equal(statusById[findZohoField("Notice Period").field_id], "filled");
  assert.equal(
    statusById[findZohoField("Onsite", "Remote work preference").field_id],
    "filled",
  );
  assert.equal(
    statusById[findZohoField("Remote", "Remote work preference").field_id],
    "filled",
  );
  assert.equal(
    statusById[findZohoField("Day", "Work shift").field_id],
    "filled",
  );
  assert.equal(
    statusById[findZohoField("Flexible", "Work shift").field_id],
    "filled",
  );
  // Consent checkbox must NEVER be checked even if passed value: "true"
  assert.equal(statusById[declarationField.field_id], "untouched");
  assert.equal(await page.locator("[name=declaration]").isChecked(), false);
  // Pre-filled and user-edited values preserved
  assert.equal(
    await page.locator("[name=full_name]").inputValue(),
    "Existing Fictional Candidate",
  );
  assert.equal(
    await page.locator("[name=linkedin]").inputValue(),
    "https://linkedin.com/in/owner-live-edit",
  );
  assert.equal(await page.locator("[name=country]").inputValue(), "India");
  assert.equal(
    await page.locator("[name=notice_period]").inputValue(),
    "30 days",
  );
  assert.equal(
    await page.locator('input[name="remote_pref"][value="Remote"]').isChecked(),
    true,
  );
  assert.equal(
    await page.locator('input[name="remote_pref"][value="Onsite"]').isChecked(),
    false,
  );
  assert.equal(
    await page.locator('input[name="shift"][value="Flexible"]').isChecked(),
    true,
  );
  assert.equal(
    await page.locator('input[name="stack"][value="Python"]').isChecked(),
    true,
  );
  assert.equal(
    await page.locator('input[name="stack"][value="Rust"]').isChecked(),
    false,
  );
  assert.deepEqual(await page.evaluate(() => window.events), []);
  // Verify accidental form submit is blocked after fill
  const submitPrevented = await page.evaluate(() => {
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    document.getElementById("zr-application-form").dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  assert.equal(submitPrevented, true);

  // 3. Validation errors, conditional questions, dynamic inputs, unsafe DOM mutations, and multi-step navigation
  activeFixture = "zoho-validation-and-steps";
  await page.goto(url);
  const step1Snap = await inspect();
  assert.equal(step1Snap.state, "validation_errors");
  assert.equal(step1Snap.has_next, true);
  assert.equal(step1Snap.fields.length, 2);
  assert.equal(step1Snap.fields[0].label, "Email");
  assert.equal(step1Snap.fields[0].invalid, true);
  assert.equal(step1Snap.fields[1].label, "Years of experience");

  // Fill with an invalid pattern on Years of experience -> reports validation_error
  const valResult = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: step1Snap.document_id,
    actions: [
      {
        field_id: step1Snap.fields[0].field_id,
        kind: "email",
        value: "alex@example.com",
      },
      {
        field_id: step1Snap.fields[1].field_id,
        kind: "text",
        value: "two years",
      },
    ],
  });
  assert.equal(valResult.state, "needs_input");
  assert.deepEqual(valResult.results, [
    { field_id: "f0", status: "validation_error" },
    { field_id: "f1", status: "validation_error" },
  ]);

  // Revealing a conditional block after inspection invalidates the old snapshot
  await page.evaluate(() => {
    document.querySelector("[name=exp_years]").value = "";
  });
  const beforeConditional = await inspect();
  await page.evaluate(() => {
    document.getElementById("conditional-block").hidden = false;
  });
  const blockedByConditional = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: beforeConditional.document_id,
    actions: [
      {
        field_id: beforeConditional.fields[0].field_id,
        kind: "text",
        value: "2",
      },
    ],
  });
  assert.equal(blockedByConditional.state, "manual_required");
  assert.equal(await page.locator("[name=exp_years]").inputValue(), "");

  // Fresh inspection fills the new empty fields; the page's existing email
  // validation error still prevents a complete-form claim.
  const afterConditional = await inspect();
  assert.deepEqual(
    afterConditional.fields.map((f) => f.label),
    ["Years of experience", "Current Employer"],
  );
  const filledConditional = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: afterConditional.document_id,
    actions: [
      {
        field_id: afterConditional.fields[0].field_id,
        kind: "text",
        value: "2",
      },
      {
        field_id: afterConditional.fields[1].field_id,
        kind: "text",
        value: "Fictional Corp",
      },
    ],
  });
  assert.equal(filledConditional.state, "needs_input");
  assert.ok(filledConditional.results.every((r) => r.status === "filled"));
  assert.equal(await page.locator("[name=exp_years]").inputValue(), "2");
  assert.equal(
    await page.locator("[name=employer]").inputValue(),
    "Fictional Corp",
  );
  assert.ok(
    await page
      .locator("[name=email]")
      .evaluate((e) => e.classList.contains("zr-invalid")),
  );

  // Unsafe DOM mutation (mutating form.action) after inspection blocks fill
  await page.evaluate(() => {
    document.querySelector("[name=employer]").value = "";
  });
  const beforeMutation = await inspect();
  await page.evaluate(() => {
    document.getElementById("zr-step-form").action =
      "https://evil.example/steal";
  });
  const blockedByMutation = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: beforeMutation.document_id,
    actions: [
      {
        field_id: beforeMutation.fields[0].field_id,
        kind: "text",
        value: "Fictional Corp",
      },
    ],
  });
  assert.equal(blockedByMutation.state, "manual_required");
  assert.equal(blockedByMutation.reason, "dom_changed");
  assert.equal(await page.locator("[name=employer]").inputValue(), "");

  // Multi-step transition: advancing to Step 2 invalidates Step 1 snapshot and requires fresh inspection
  const preStepChange = await inspect();
  await page.locator("#next-btn").click();
  const staleStepFill = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: preStepChange.document_id,
    actions: [
      {
        field_id: "f0",
        kind: "url",
        value: "https://github.com/fictional",
      },
    ],
  });
  assert.equal(staleStepFill.state, "manual_required");
  assert.equal(await page.locator("[name=github]").inputValue(), "");

  // Fresh inspection on Step 2 succeeds and fills Step 2 fields
  const step2Snap = await inspect();
  assert.equal(step2Snap.state, "ready");
  assert.deepEqual(
    step2Snap.fields.map((f) => f.label),
    ["GitHub URL", "Portfolio URL"],
  );
  const step2Fill = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: step2Snap.document_id,
    actions: [
      {
        field_id: step2Snap.fields[0].field_id,
        kind: "url",
        value: "https://github.com/fictional",
      },
    ],
  });
  assert.equal(step2Fill.state, "form_filled");
  assert.equal(
    await page.locator("[name=github]").inputValue(),
    "https://github.com/fictional",
  );

  // 4. Cross-origin frame inside form requires manual handling
  activeFixture = "zoho-cross-origin-frame";
  await page.goto(url);
  const framedSnap = await inspect();
  assert.equal(framedSnap.state, "manual_required");
  assert.equal(framedSnap.manual_reason, "cross_origin_frame");
  assert.equal(
    framedSnap.unsupported_controls.some((u) => u.kind === "iframe"),
    true,
  );

  // 5. Sensitive fields (PAN, OTP, secret PIN) trigger manual_required and never leak values
  activeFixture = "zoho-sensitive";
  await page.goto(url);
  const sensitiveSnap = await inspect();
  assert.equal(sensitiveSnap.state, "manual_required");
  assert.equal(sensitiveSnap.manual_reason, "sensitive_control");
  const sensitiveJson = JSON.stringify(sensitiveSnap);
  assert.equal(sensitiveJson.includes("AAAAA0000A"), false);
  assert.equal(sensitiveJson.includes("999888"), false);
  assert.equal(sensitiveJson.includes("7788"), false);
  assert.equal(sensitiveJson.includes("Private Name"), false);

  // 6. Adversarial edge cases: postal PIN code vs secret PIN, later 'None' select preservation, 'hereby declare' consent, sibling label[for]
  activeFixture = "zoho-adversarial";
  await page.goto(url);
  const advSnap = await inspect();
  assert.equal(advSnap.state, "ready");

  // Postal PIN code is recognized as ordinary text input (NOT sensitive)
  const pinField = advSnap.fields.find((f) => f.label === "Postal PIN Code");
  assert.ok(pinField);
  assert.equal(pinField.kind, "text");
  assert.equal(pinField.required, true);

  // Secondary Language (selected option is "None" at index 1) is answered, so absent from unanswered fields
  const secLangField = advSnap.fields.find((f) =>
    f.label.includes("Secondary Language"),
  );
  assert.equal(secLangField, undefined);

  // Consent checkbox with 'hereby declare' is detected as consent
  const herebyField = advSnap.fields.find((f) =>
    f.label.includes("hereby declare"),
  );
  assert.ok(herebyField);
  assert.equal(herebyField.group_label, null);

  // Sibling label[for="other-target"] is not adopted as unrelated_peer's label;
  // instead, unrelated_peer is safely reported as an unlabelled unsupported control
  const unrelatedControl = advSnap.unsupported_controls.find(
    (u) => u.label === "unrelated_peer",
  );
  assert.ok(unrelatedControl);
  assert.equal(
    unrelatedControl.reason,
    "Incomplete or missing field label requires manual entry",
  );

  // Verify fill on adversarial form preserves hereby declare consent and fills postal PIN
  const advFill = await runFill({
    operation: "fill",
    only_empty: true,
    document_id: advSnap.document_id,
    actions: [
      {
        field_id: pinField.field_id,
        kind: "text",
        value: "560001",
      },
      {
        field_id: herebyField.field_id,
        kind: "checkbox",
        value: "true",
      },
    ],
  });
  assert.equal(advFill.state, "needs_input");
  const herebyResult = advFill.results.find(
    (r) => r.field_id === herebyField.field_id,
  );
  assert.equal(herebyResult.status, "untouched");
  assert.equal(await page.locator("[name=hereby_dec]").isChecked(), false);
  assert.equal(await page.locator("[name=pincode]").inputValue(), "560001");

  assert.equal(writes, 0);
  console.log(
    "PASS: actual Chromium preserves existing/newly typed answers, supports Zoho Recruit labels/selects/radio & checkbox groups, detects custom comboboxes/dates/framework inputs/cross-origin frames/sensitive fields, blocks stale DOM/step fills and accidental submissions, and leaks zero candidate values.",
  );
} finally {
  await browser.close();
}
