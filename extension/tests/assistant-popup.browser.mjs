import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Actual popup DOM with a fictional worker boundary; no live employer interaction.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
try {
  const page = await browser.newPage({
    viewport: { width: 460, height: 1200 },
  });
  await page.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname.slice(1);
    if (!/^[a-z-]+\.(?:js|css|html)$/.test(path))
      throw Error("unexpected_popup_asset");
    await route.fulfill({
      contentType: path.endsWith("js")
        ? "application/javascript"
        : path.endsWith("css")
          ? "text/css"
          : "text/html",
      body: await readFile(new URL(`../${path}`, import.meta.url)),
    });
  });
  await page.addInitScript(() => {
    const id = "11111111-1111-4111-8111-111111111111",
      url = "https://jobs.lever.co/fictional/fictional/apply";
    window.calls = [];
    window.permissionCalls = [];
    const task = {
      id,
      application_id: id,
      version: 1,
      company_name: "Fictional Employer",
      job_title: "Fictional Engineer",
      packet_revision: 3,
      profile_version: 2,
      tab_id: 7,
      target_url: url,
      current_url: url,
      state: "PACKET_READY",
      challenge_state: "NONE",
      next_action: "Inspect this step.",
    };
    const inspection = {
      document_id: id,
      url,
      state: "ready",
      challenge_state: "NONE",
      completed_count: 1,
      fields: [
        { field_id: "f0", label: "Email", kind: "email", required: true },
        { field_id: "f1", label: "Expected salary", kind: "text" },
      ],
    };
    const plan = {
      id,
      application_id: id,
      packet_revision: 3,
      target_url: url,
      state: "preview",
      inspection,
      actions: [
        {
          field_id: "f0",
          kind: "email",
          value: "fictional@example.test",
          evidence: ["candidate_profile:fictional"],
          needs_input: false,
        },
        {
          field_id: "f1",
          kind: "text",
          needs_input: true,
          missing_input_id: "a".repeat(32),
          evidence: [],
        },
      ],
    };
    window.challenge = false;
    window.chrome = {
      storage: {
        session: { get: async () => ({}), remove: async () => {} },
        onChanged: { addListener() {} },
      },
      permissions: {
        contains: async () => true,
        request: async (value) => {
          window.permissionCalls.push(value);
          return true;
        },
      },
      runtime: {
        sendMessage: async (message) => {
          window.calls.push(message);
          if (message.action === "list") return { ok: true, tasks: [task] };
          if (message.action === "destination" || message.action === "open")
            return { ok: true, task };
          if (message.action === "inspect") return { ok: true, inspection };
          if (message.action === "prepare") {
            task.state = window.challenge
              ? "CHALLENGE_REQUIRED"
              : "NEEDS_INPUT";
            task.challenge_state = window.challenge
              ? "WIDGET_PRESENT_UNVERIFIED"
              : "NONE";
            task.next_action = window.challenge
              ? "Complete the challenge manually; this proposal is read-only."
              : "Review proposed answers and provide missing facts.";
            return {
              ok: true,
              task,
              plan: {
                ...plan,
                state: window.challenge ? "read_only" : "preview",
                inspection: {
                  ...inspection,
                  challenge_state: window.challenge
                    ? "WIDGET_PRESENT_UNVERIFIED"
                    : "NONE",
                },
              },
            };
          }
          if (message.action === "fill") {
            task.network_guard_active = true;
            return {
              ok: true,
              task,
              result: {
                state: "needs_input",
                verification: "retained_after_blur",
                results: [{ field_id: "f0", status: "filled" }],
                submitted: false,
              },
            };
          }
          if (message.action === "return_control") {
            task.network_guard_active = false;
            return { ok: true, task, synchronized: true };
          }
          task.state = message.action === "cancel" ? "FAILED_FINAL" : "PAUSED";
          return {
            ok: true,
            task: {
              ...task,
              state: message.action === "cancel" ? "FAILED_FINAL" : "PAUSED",
            },
          };
        },
      },
    };
  });
  await page.goto("https://extension-fixture.example/popup.html");
  assert.equal(await page.locator("#fill-form").isDisabled(), true);
  await page
    .locator("#application-id")
    .fill("11111111-1111-4111-8111-111111111111");
  await page.locator("#open-application").click();
  assert.match(
    await page.locator("#answer-status").innerText(),
    /Destination: https:\/\/jobs.lever.co/,
  );
  assert.deepEqual(await page.evaluate(() => window.permissionCalls), []);
  await page.locator("#open-application").click();
  assert.deepEqual(await page.evaluate(() => window.permissionCalls), [
    { origins: ["https://jobs.lever.co/*"] },
  ]);
  await page.locator("#inspect-form").click();
  assert.match(
    await page.locator("#answer-status").innerText(),
    /No fields changed/,
  );
  await page.locator("#allow-interactions").check();
  await page.locator("#prepare-answers").click();
  assert.match(
    await page.locator("#field-summary").innerText(),
    /1 ready · 1 already completed · 1 missing/,
  );
  assert.equal(await page.locator("#fill-form").isDisabled(), true);
  assert.equal(await page.locator("#missing-answers a").count(), 1);
  await page.locator("#review-answers").click();
  assert.equal(await page.locator("#fill-form").isEnabled(), true);
  assert.match(await page.locator("#review-status").innerText(), /revision 3/);
  await page.locator("#fill-form").click();
  assert.match(
    await page.locator("#answer-status").innerText(),
    /retained after blur.*No application submitted/,
  );
  assert.equal(await page.locator("#fill-form").isDisabled(), true);
  assert.deepEqual(
    await page.evaluate(() =>
      window.calls
        .filter((m) => m.action === "fill")
        .map((m) => m.interaction_authorized),
    ),
    [true],
  );
  await page.locator("#prepare-answers").click();
  await page.locator("#ask-telegram").click();
  assert.match(
    await page.locator("#answer-status").innerText(),
    /specific prompt/,
  );
  await page.evaluate(() => {
    window.challenge = true;
  });
  await page.locator("#prepare-answers").click();
  assert.equal(await page.locator("#review-answers").isDisabled(), true);
  assert.equal(await page.locator("#fill-form").isDisabled(), true);
  assert.match(
    await page.locator("#challenge-status").innerText(),
    /WIDGET_PRESENT_UNVERIFIED/,
  );
  await page.screenshot({
    path: new URL(
      "../../docs/phase52/screenshots/extension-popup-fictional.png",
      import.meta.url,
    ).pathname,
    fullPage: true,
  });
  await page.locator("#cancel-form").click();
  assert.match(await page.locator("#answer-status").innerText(), /cancelled/);
  assert.equal(
    await page.evaluate(
      () => window.calls.filter((m) => m.action === "fill").length,
    ),
    1,
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#return-control").click();
  assert.match(
    await page.locator("#answer-status").innerText(),
    /networking restored/,
  );
  console.log(
    JSON.stringify({
      cases: 9,
      scope: "fictional popup worker contract",
      submissions: 0,
    }),
  );
} finally {
  await browser.close();
}
