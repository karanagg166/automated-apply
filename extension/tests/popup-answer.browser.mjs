// Actual popup UI in isolated Chromium with fictional browser/native responses.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 560, height: 1000 },
  });
  await page.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname.slice(1);
    assert.match(path, /^[a-z-]+\.(?:js|css|html)$/);
    const contentType = path.endsWith(".js")
      ? "application/javascript"
      : path.endsWith(".css")
        ? "text/css"
        : "text/html";
    await route.fulfill({
      contentType,
      body: await readFile(new URL(`../${path}`, import.meta.url)),
    });
  });
  await page.addInitScript(() => {
    const id = "11111111-1111-4111-8111-111111111111";
    const url =
      "https://fictional-employer.zohorecruit.in/jobs/Careers/123456/Backend-Engineer?source=CareerSite&ref=fixture";
    window.nativeCalls = [];
    window.fillMode = "ok";
    window.inspectMode = "ok";
    window.planExpired = false;
    const baseInspection = {
      version: 1,
      document_id: id,
      url,
      state: "ready",
      fields: [
        { field_id: "f0", kind: "email", label: "Email", required: true },
        {
          field_id: "f1",
          kind: "text",
          label: "Expected salary",
          required: true,
        },
        {
          field_id: "f2",
          kind: "radio",
          label: "Yes",
          group_label: "Work authorization",
          required: true,
        },
        {
          field_id: "f3",
          kind: "checkbox",
          label: "I agree to the privacy policy",
          required: true,
        },
      ],
      unsupported_controls: [
        {
          label: "Preferred office location",
          kind: "custom_combobox",
          required: true,
          reason: "Custom combobox or dropdown requires manual selection",
        },
        {
          label: "Available start date",
          kind: "date",
          required: true,
          reason: "Date field requires manual entry",
        },
        {
          label: "LinkedIn profile",
          kind: "framework_input",
          required: false,
          reason: "Framework-controlled input requires manual typing",
        },
      ],
    };
    const makePlan = () => ({
      id,
      target_url: url,
      expires_at: window.planExpired
        ? "2020-01-01T00:00:00Z"
        : "2099-01-01T00:00:00Z",
      inspection: {
        version: 1,
        document_id: id,
        url,
        state: "ready",
        fields: baseInspection.fields,
      },
      approved_fields: ["f0", "f2"],
      actions: [
        {
          field_id: "f0",
          kind: "email",
          value: "alex@example.com",
          needs_input: false,
          evidence: ["candidate_profile:fictional"],
        },
        {
          field_id: "f1",
          kind: "text",
          value: null,
          needs_input: true,
          evidence: [],
        },
        {
          field_id: "f2",
          kind: "radio",
          value: "true",
          needs_input: false,
          evidence: ["candidate_profile:fictional"],
        },
        {
          field_id: "f3",
          kind: "checkbox",
          value: null,
          needs_input: true,
          evidence: [],
        },
      ],
    });
    window.chrome = {
      storage: {
        session: { get: async () => ({}), remove: async () => {} },
        onChanged: { addListener() {} },
      },
      tabs: {
        query: async () => [{ id: 7, url, title: "Fictional application" }],
      },
      scripting: {
        executeScript: async (request) => {
          if (request.args?.[0]?.operation === "fill") {
            if (window.fillMode === "step_changed") {
              return [
                {
                  result: {
                    state: "manual_required",
                    reason: "step_changed",
                    results: [],
                    submitted: false,
                  },
                },
              ];
            }
            if (window.fillMode === "dom_changed") {
              return [
                {
                  result: {
                    state: "manual_required",
                    reason: "dom_changed",
                    results: [],
                    submitted: false,
                  },
                },
              ];
            }
            if (window.fillMode === "validation_error") {
              return [
                {
                  result: {
                    state: "needs_input",
                    results: [
                      { field_id: "f0", status: "filled" },
                      { field_id: "f2", status: "validation_error" },
                    ],
                    submitted: false,
                  },
                },
              ];
            }
            return [
              {
                result: {
                  state: "form_filled",
                  results: [
                    { field_id: "f0", status: "filled" },
                    { field_id: "f2", status: "filled" },
                  ],
                  submitted: false,
                },
              },
            ];
          }
          if (window.inspectMode === "cross_origin_frame") {
            return [
              {
                result: {
                  version: 1,
                  document_id: id,
                  url,
                  state: "manual_required",
                  manual_reason: "cross_origin_frame",
                  fields: [],
                },
              },
            ];
          }
          if (window.inspectMode === "sensitive_control") {
            return [
              {
                result: {
                  version: 1,
                  document_id: id,
                  url,
                  state: "manual_required",
                  manual_reason: "sensitive_control",
                  fields: [],
                },
              },
            ];
          }
          return [{ result: structuredClone(baseInspection) }];
        },
      },
      runtime: {
        sendNativeMessage: async (_host, request) => {
          window.nativeCalls.push(request);
          return window.denyAnswers
            ? {
                version: 1,
                request_id: request.request_id,
                ok: false,
                error_code: "profile_review_required",
              }
            : {
                version: 1,
                request_id: request.request_id,
                ok: true,
                data: { submitted: false, plan: makePlan() },
              };
        },
      },
    };
  });
  await page.goto("https://extension-fixture.invalid/popup.html");
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 answers ready"),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), true);
  const planText = await page.locator("#form-plan").innerText();
  assert.match(planText, /alex@example\.com/);
  assert.match(planText, /Work authorization \(Yes\) \(required\)[\s\S]*true/);
  assert.match(planText, /Expected salary[\s\S]*Needs a reviewed fact/);
  assert.match(
    planText,
    /I agree to the privacy policy[\s\S]*Consent and legal declarations are never selected automatically/,
  );
  assert.match(
    planText,
    /Preferred office location \(required\)[\s\S]*Custom combobox or dropdown requires manual selection/,
  );
  assert.match(
    planText,
    /Available start date \(required\)[\s\S]*Date field requires manual entry/,
  );
  assert.match(
    planText,
    /LinkedIn profile[\s\S]*Framework-controlled input requires manual typing/,
  );
  assert.deepEqual(
    await page.evaluate(() => window.nativeCalls.map((call) => call.command)),
    ["prepare_form_answers"],
  );
  // Ensure client-only unsupported_controls were stripped from native payload
  assert.equal(
    await page.evaluate(
      () => "unsupported_controls" in window.nativeCalls[0].inspection,
    ),
    false,
  );
  if (process.env.AA_SCREENSHOT_PATH)
    await page.screenshot({
      path: process.env.AA_SCREENSHOT_PATH,
      fullPage: true,
    });
  await page.locator("#fill-form").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 fields filled"),
  );
  assert.deepEqual(
    await page.evaluate(() => window.nativeCalls.map((call) => call.command)),
    ["prepare_form_answers", "authorize_form", "record_form_fill"],
  );
  assert.deepEqual(await page.evaluate(() => window.nativeCalls[1].field_ids), [
    "f0",
    "f2",
  ]);
  // Verify record_form_fill never leaks candidate answer values
  const recordedJson = await page.evaluate(() =>
    JSON.stringify(window.nativeCalls[2]),
  );
  assert.equal(recordedJson.includes("alex@example.com"), false);
  assert.equal(await page.locator("#fill-form").isEnabled(), false);

  // Validation error reported after fill
  await page.evaluate(() => {
    window.fillMode = "validation_error";
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 answers ready"),
  );
  await page.locator("#fill-form").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes(
        "1 field filled (1 validation error — review highlighted fields on the page)",
      ),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);

  // Step change between prepare and fill requires fresh review
  await page.evaluate(() => {
    window.fillMode = "step_changed";
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 answers ready"),
  );
  await page.locator("#fill-form").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes(
        "The form step changed. Prepare and review fresh answers for this step before filling",
      ),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);
  assert.equal(await page.locator("#form-plan").innerText(), "");

  // DOM mutation between prepare and fill requires fresh review
  await page.evaluate(() => {
    window.fillMode = "dom_changed";
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 answers ready"),
  );
  await page.locator("#fill-form").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes(
        "The form changed after answers were prepared. Prepare and review fresh answers before filling",
      ),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);
  assert.equal(await page.locator("#form-plan").innerText(), "");

  // Expired review authorization is blocked before authorize_form or DOM fill
  await page.evaluate(() => {
    window.fillMode = "ok";
    window.planExpired = true;
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.startsWith("2 answers ready"),
  );
  const callsBeforeExpiredFill = await page.evaluate(
    () => window.nativeCalls.length,
  );
  await page.locator("#fill-form").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes("review authorization expired"),
  );
  assert.equal(
    await page.evaluate(() => window.nativeCalls.length),
    callsBeforeExpiredFill,
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);

  // Cross-origin frame inspection error
  await page.evaluate(() => {
    window.planExpired = false;
    window.inspectMode = "cross_origin_frame";
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes("cross-origin frame that cannot be inspected safely"),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);

  // Sensitive field inspection error
  await page.evaluate(() => {
    window.inspectMode = "sensitive_control";
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes(
        "Sensitive fields (such as password, OTP, payment or national ID controls) were detected",
      ),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);

  // Missing profile review error
  await page.evaluate(() => {
    window.inspectMode = "ok";
    window.denyAnswers = true;
  });
  await page.locator("#prepare-answers").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#answer-status")
      .textContent.includes("Review and save your real profile"),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), false);
  assert.equal(await page.locator("#form-plan").innerText(), "");
  console.log(
    "PASS: actual popup prepares answers without a packet ID, renders grouped/consent/unsupported Zoho controls, requires a fresh review after step/DOM changes or expired authorization, blocks cross-origin and sensitive forms, fills once, and explains missing profile review.",
  );
} finally {
  await browser.close();
}
