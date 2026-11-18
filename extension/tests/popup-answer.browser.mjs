// Real popup in an isolated browser with fictional application-assistant replies.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  chromium,
  expect,
} from "../../frontend/node_modules/@playwright/test/index.mjs";
import { fixtureExecutable } from "./browser-fixture-engine.mjs";

const host = "https://extension-fixture.invalid";
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
try {
  const page = await browser.newPage({
    viewport: { width: 560, height: 1000 },
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    assert.equal(url.origin, host);
    const path = url.pathname.slice(1);
    assert.match(path, /^[a-z-]+\.(?:js|css|html)$/);
    await route.fulfill({
      contentType: path.endsWith(".js")
        ? "application/javascript"
        : path.endsWith(".css")
          ? "text/css"
          : "text/html",
      body: await readFile(new URL(`../${path}`, import.meta.url)),
    });
  });
  await page.addInitScript(() => {
    const id = "11111111-1111-4111-8111-111111111111";
    const url =
      "https://fictional-employer.zohorecruit.in/jobs/Careers/123456/Backend-Engineer";
    const task = {
      id,
      application_id: id,
      packet_revision: 4,
      profile_version: 2,
      tab_id: 7,
      state: "FORM_INSPECTED",
      target_url: url,
    };
    const plan = {
      id,
      application_id: id,
      packet_revision: 4,
      target_url: url,
      inspection: {
        document_id: id,
        fields: [
          { field_id: "f0", label: "Email", required: true },
          { field_id: "f1", label: "Expected salary", required: true },
          {
            field_id: "f2",
            label: "Yes",
            group_label: "Work authorization",
            required: true,
          },
          {
            field_id: "f3",
            label: "I agree to the privacy policy",
            required: true,
          },
        ],
      },
      actions: [
        {
          field_id: "f0",
          kind: "email",
          value: "alex@example.com",
          evidence: ["candidate_profile:fixture"],
        },
        {
          field_id: "f1",
          kind: "text",
          needs_input: true,
          missing_input_id: "a".repeat(32),
        },
        {
          field_id: "f2",
          kind: "radio",
          value: "true",
          evidence: ["candidate_profile:fixture"],
        },
        { field_id: "f3", kind: "checkbox", needs_input: true },
      ],
      unsupported_controls: [
        {
          label: "Preferred office location",
          required: true,
          reason: "Custom combobox or dropdown requires manual selection",
        },
        {
          label: "Available start date",
          required: true,
          reason: "Date field requires manual entry",
        },
        {
          label: "LinkedIn profile",
          reason: "Framework-controlled input requires manual typing",
        },
      ],
    };
    window.fixture = {
      calls: [],
      prepareError: null,
      fillError: null,
      validationError: false,
      permission: true,
    };
    window.chrome = {
      storage: {
        session: { get: async () => ({}), remove: async () => {} },
        onChanged: { addListener() {} },
      },
      permissions: {
        contains: async () => window.fixture.permission,
      },
      runtime: {
        sendMessage: async (request) => {
          if (request.command === "naukri_queue")
            return {
              ok: true,
              queue: { state: "STOPPED", revision: 1, total: 0, counts: {} },
            };
          if (request.command !== "application_assistant")
            throw Error("unexpected fixture message");
          if (request.action === "list") return { ok: true, tasks: [task] };
          window.fixture.calls.push(request);
          if (request.action === "prepare")
            return window.fixture.prepareError || { ok: true, task, plan };
          if (request.action !== "fill" || request.task_id !== task.id)
            throw Error("unexpected fixture action");
          if (window.fixture.fillError)
            return { ok: false, error_code: window.fixture.fillError };
          return {
            ok: true,
            task,
            result: {
              results: request.field_ids.map((field_id) => ({
                field_id,
                status:
                  window.fixture.validationError && field_id === "f2"
                    ? "validation_error"
                    : "filled",
              })),
              verification: "retained_after_blur",
            },
          };
        },
      },
    };
  });
  await page.goto(host + "/popup.html");
  const status = page.locator("#answer-status");
  const fill = page.locator("#fill-form");
  const formPlan = page.locator("#form-plan");
  const calls = () => page.evaluate(() => window.fixture.calls);
  const prepare = async () => {
    await page.locator("#prepare-answers").click();
    await expect(status).toContainText("2 answers prepared");
    await expect(fill).toBeDisabled();
  };
  const review = () => page.locator("#review-answers").click();

  await prepare();
  assert.deepEqual(
    (await calls()).map((call) => call.action),
    ["prepare"],
  );
  assert.equal((await calls())[0].task_id, undefined);
  const savedQuestion = page.locator("#missing-answers a");
  await expect(savedQuestion).toHaveAttribute(
    "href",
    "http://127.0.0.1:3000/profile?missing_input=" + "a".repeat(32),
  );
  await expect(savedQuestion).toContainText("Expected salary");
  assert.equal(await page.locator("#missing-answers script").count(), 0);
  const planText = await formPlan.innerText();
  assert.match(planText, /alex@example\.com/);
  assert.match(planText, /Work authorization \(Yes\) \(required\)[\s\S]*true/);
  assert.match(
    planText,
    /Expected salary[\s\S]*Saved question needs your factual input/,
  );
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

  await review();
  await expect(fill).toBeEnabled();
  await page.locator('#approved-fields input[data-field-id="f2"]').uncheck();
  await expect(fill).toBeDisabled();
  await review();
  await page.evaluate(() => {
    window.fixture.permission = false;
  });
  await fill.click();
  await expect(status).toContainText("lacks its submission guard permission");
  assert.deepEqual(
    (await calls()).map((call) => call.action),
    ["prepare"],
  );
  await page.evaluate(() => {
    window.fixture.permission = true;
  });
  await fill.click();
  await expect(status).toContainText("1 fields retained after blur");
  await expect(status).toContainText("No application submitted");
  assert.deepEqual((await calls()).at(-1).field_ids, ["f0"]);
  assert.equal(
    JSON.stringify((await calls()).at(-1)).includes("alex@example.com"),
    false,
  );
  await expect(fill).toBeDisabled();

  await page.evaluate(() => {
    window.fixture.validationError = true;
  });
  await prepare();
  await review();
  await fill.click();
  await expect(status).toContainText("1 errors");
  await expect(fill).toBeDisabled();

  for (const [code, message] of [
    ["step_changed", "The form step changed"],
    ["dom_changed", "The form changed after answers were prepared"],
    ["fill_plan_stale", "review authorization expired"],
  ]) {
    await page.evaluate((value) => {
      window.fixture.fillError = value;
    }, code);
    await prepare();
    await review();
    await fill.click();
    await expect(status).toContainText(message);
    await expect(fill).toBeDisabled();
    await expect(formPlan).toBeEmpty();
  }

  for (const [code, reason, message] of [
    [
      "unsupported_application_form",
      "cross_origin_frame",
      "cross-origin frame",
    ],
    ["unsupported_application_form", "sensitive_control", "Sensitive fields"],
    ["profile_review_required", null, "Review and save your real profile"],
  ]) {
    await page.evaluate(
      ([error_code, manual_reason]) => {
        window.fixture.prepareError = { ok: false, error_code, manual_reason };
      },
      [code, reason],
    );
    await page.locator("#prepare-answers").click();
    await expect(status).toContainText(message);
    await expect(fill).toBeDisabled();
    await expect(formPlan).toBeEmpty();
  }
  console.log(
    "PASS: isolated popup shows saved evidence, binds explicit field review, requires the network guard, and prevents reuse of stale previews.",
  );
} finally {
  await browser.close();
}
