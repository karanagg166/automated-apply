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
    const inspection = {
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
      ],
    };
    const plan = {
      id,
      target_url: url,
      inspection,
      approved_fields: ["f0"],
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
      ],
    };
    window.chrome = {
      storage: {
        session: { get: async () => ({}), remove: async () => {} },
        onChanged: { addListener() {} },
      },
      tabs: {
        query: async () => [{ id: 7, url, title: "Fictional application" }],
      },
      scripting: {
        executeScript: async (request) => [
          {
            result:
              request.args?.[0]?.operation === "fill"
                ? {
                    state: "form_filled",
                    results: [{ field_id: "f0", status: "filled" }],
                    submitted: false,
                  }
                : inspection,
          },
        ],
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
                data: { submitted: false, plan },
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
      .textContent.startsWith("1 answer ready"),
  );
  assert.equal(await page.locator("#fill-form").isEnabled(), true);
  assert.match(
    await page.locator("#form-plan").innerText(),
    /alex@example.com/,
  );
  assert.match(
    await page.locator("#form-plan").innerText(),
    /Expected salary[\s\S]*Needs a reviewed fact/,
  );
  assert.deepEqual(
    await page.evaluate(() => window.nativeCalls.map((call) => call.command)),
    ["prepare_form_answers"],
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
      .textContent.startsWith("1 field filled"),
  );
  assert.deepEqual(
    await page.evaluate(() => window.nativeCalls.map((call) => call.command)),
    ["prepare_form_answers", "authorize_form", "record_form_fill"],
  );
  assert.deepEqual(await page.evaluate(() => window.nativeCalls[1].field_ids), [
    "f0",
  ]);
  assert.equal(await page.locator("#fill-form").isEnabled(), false);
  await page.evaluate(() => {
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
    "PASS: actual popup prepares answers without a packet ID, shows missing facts, requires a review click before exact-field authorization, fills once, and explains missing profile review.",
  );
} finally {
  await browser.close();
}
