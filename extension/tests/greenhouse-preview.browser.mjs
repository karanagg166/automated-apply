import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Fictional Greenhouse form with the real popup and inspector, using a fixture worker.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  chromium,
  expect,
} from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";

const application = "11111111-1111-4111-8111-111111111111";
const url = "https://job-boards.greenhouse.io/fictional-employer/jobs/1";
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
try {
  const context = await browser.newContext({
    viewport: { width: 600, height: 1000 },
  });
  const requests = [],
    workerCalls = [];
  let showFictionalChallenge = true;
  const fictionalChallenge = `
    <div data-sitekey=fictional><p>Fictional security widget</p></div>
    <button id=finish-fictional type=button onclick="document.querySelector('[data-sitekey]').remove();this.remove()">Complete fictional check</button>`;
  const approved = new Map([
    ["Email", "alex@example.org"],
    ["Country", "Country 125"],
    ["Career stage", "Graduate"],
    ["Available start date", "2026-11-01"],
    ["End month", "2026-12"],
    ["Industry", "Software"],
  ]);
  const html = `<h1>Fictional Greenhouse application</h1>
    <form action="/never-submit" method="post">
    <label>Full name<input value="Owner already answered"></label>
    <label>Email<input type=email required></label>
    <label>Country<select><option value="">Select</option>${Array.from({ length: 249 }, (_, i) => `<option value=c${i}>Country ${i}</option>`).join("")}</select></label>
    <label>Career stage<input role=combobox list=stages></label>
    <datalist id=stages><option value=Graduate><option value=Experienced></datalist>
    <label>Available start date<input type=date min=2026-01-01 max=2026-12-31></label>
    <label>End month<input type=month></label>
    <label>Industry<input role=combobox aria-expanded=true aria-controls=industries></label>
    <div role=listbox id=industries><div role=option>Software</div><div role=option>Finance</div></div>
    <fieldset><legend>Employer 1</legend><div role=combobox><input role=combobox aria-label="Start year"></div></fieldset>
    <fieldset><legend>Employer 2</legend><div role=combobox><input role=combobox aria-label="Start year"></div></fieldset>
    <label>Gender<select><option value="">Select</option><option>Woman</option><option>Man</option></select></label>
    <label>Declaration<input type=checkbox>I agree to the privacy policy</label>
    <label>Upload resume<input type=file></label>
    ${fictionalChallenge}
    <button type=submit>Submit application</button></form>
    <script>window.events=[];for(const kind of ['input','change','submit'])document.addEventListener(kind,()=>window.events.push(kind));</script>`;
  await context.route("**/*", async (route) => {
    requests.push({
      method: route.request().method(),
      url: route.request().url(),
    });
    const target = new URL(route.request().url());
    if (target.href === url)
      return route.fulfill({
        contentType: "text/html",
        body: showFictionalChallenge
          ? html
          : html.replace(fictionalChallenge, ""),
      });
    if (
      target.hostname === "extension.fixture" &&
      /^\/[a-z-]+\.(html|js|css)$/.test(target.pathname)
    )
      return route.fulfill({
        contentType: target.pathname.endsWith(".js")
          ? "application/javascript"
          : target.pathname.endsWith(".css")
            ? "text/css"
            : "text/html",
        body: await readFile(new URL(`..${target.pathname}`, import.meta.url)),
      });
    await route.abort();
    throw Error(
      `Unexpected request: ${route.request().method()} ${target.origin}${target.pathname}`,
    );
  });
  const form = await context.newPage();
  await form.goto(url);
  const popup = await context.newPage();
  const task = {
    id: application,
    application_id: application,
    packet_revision: 3,
    profile_version: 2,
    target_url: url,
    current_url: url,
    tab_id: 1,
    state: "PACKET_READY",
  };
  let lastPlan;
  await popup.exposeFunction("fixtureWorker", async (req) => {
    if (req.command === "naukri_queue")
      return {
        ok: true,
        queue: { state: "STOPPED", revision: 1, total: 0, counts: {} },
      };
    assert.equal(req.command, "application_assistant");
    if (req.action === "list") return { ok: true, tasks: [task] };
    workerCalls.push(req);
    if (req.action === "prepare") {
      const inspection = await form.evaluate(formDOM, {
        operation: "inspect",
        only_empty: true,
      });
      lastPlan = {
        id: crypto.randomUUID(),
        application_id: application,
        packet_revision: 3,
        target_url: url,
        inspection,
        security_status: inspection.security_status,
        manual_reason: inspection.manual_reason,
        unsupported_controls: inspection.unsupported_controls,
        expires_at: "2099-01-01T00:00:00Z",
        state: inspection.state === "manual_required" ? "read_only" : "preview",
        actions: inspection.fields.map((f) => ({
          field_id: f.field_id,
          kind: f.kind,
          value: approved.get(f.label) || null,
          needs_input: !approved.has(f.label),
          preview_only: f.preview_only,
          evidence: approved.has(f.label)
            ? ["reviewed_packet_answer:fictional:3"]
            : [],
        })),
      };
      return { ok: true, task, plan: lastPlan };
    }
    assert.equal(req.action, "fill");
    assert.equal(req.task_id, task.id);
    assert.equal(lastPlan.state, "preview");
    const actions = lastPlan.actions.filter((a) =>
      req.field_ids.includes(a.field_id),
    );
    assert.equal(actions.length, req.field_ids.length);
    assert.ok(actions.every((a) => !a.preview_only && !a.needs_input));
    assert.equal(req.interaction_authorized, false);
    const result = await form.evaluate(formDOM, {
      operation: "fill",
      document_id: lastPlan.inspection.document_id,
      actions,
      only_empty: true,
    });
    return { ok: true, task, result };
  });
  await popup.addInitScript(() => {
    window.chrome = {
      permissions: { contains: async () => true },
      runtime: {
        sendMessage: async (req) => window.fixtureWorker(req),
      },
      storage: {
        session: { get: async () => ({}) },
        onChanged: { addListener() {} },
      },
    };
  });
  await popup.goto("https://extension.fixture/popup.html");
  await popup.locator("#prepare-answers").click();
  await popup
    .getByText("Read-only preview generated.", { exact: false })
    .waitFor();
  assert.equal(await popup.locator("#fill-form").isDisabled(), true);
  const preview = await popup.locator("#form-plan").textContent();
  assert.match(preview, /if the widget remains unverified/);
  assert.match(preview, /alex@example.org/);
  assert.match(preview, /Country 125/);
  assert.equal((preview.match(/Start year/g) || []).length, 2);
  assert.match(preview, /Employer 1/);
  assert.match(preview, /Employer 2/);
  assert.match(preview, /Sensitive self-identification/);
  assert.doesNotMatch(preview, /\b(?:Woman|Man)\b/);
  assert.equal(
    workerCalls.some((c) => c.action === "fill"),
    false,
  );
  assert.deepEqual(await form.evaluate(() => window.events), []);
  const screenshot = process.env.AUTOMATED_APPLY_FIXTURE_SCREENSHOT_PATH;
  if (screenshot) await popup.screenshot({ path: screenshot, fullPage: true });
  // A DOM change is insufficient to establish that the challenge is complete.
  await form.locator("#finish-fictional").click();
  assert.equal(await popup.locator("#fill-form").isDisabled(), true);
  await popup.locator("#prepare-answers").click();
  await expect(popup.locator("#challenge-status")).toHaveText("UNKNOWN");
  await expect(popup.locator("#fill-form")).toBeDisabled();
  const oldDocument = lastPlan.inspection.document_id;
  showFictionalChallenge = false;
  await form.reload();
  await popup.locator("#prepare-answers").click();
  await expect(popup.locator("#answer-status")).toContainText(
    "5 answers prepared.",
  );
  assert.notEqual(lastPlan.inspection.document_id, oldDocument);
  assert.equal(await popup.locator("#fill-form").isDisabled(), true);
  await popup.locator("#review-answers").click();
  await popup.locator("#fill-form").click();
  await popup
    .getByText("5 fields verified by value readback", { exact: false })
    .waitFor();
  assert.equal(
    await form.locator("input[type=email]").inputValue(),
    "alex@example.org",
  );
  assert.equal(await form.locator("select").first().inputValue(), "c125");
  assert.equal(await form.locator("[list=stages]").inputValue(), "Graduate");
  assert.equal(await form.locator("[type=date]").inputValue(), "2026-11-01");
  assert.equal(await form.locator("[type=month]").inputValue(), "2026-12");
  assert.equal(
    await form.locator("input").first().inputValue(),
    "Owner already answered",
  );
  assert.equal(
    await form.locator("[aria-controls=industries]").inputValue(),
    "",
  );
  assert.equal(await form.locator("select").nth(1).inputValue(), "");
  assert.equal(await form.locator("[type=checkbox]").isChecked(), false);
  assert.deepEqual(await form.evaluate(() => window.events), []);
  assert.ok(requests.every((r) => r.method === "GET"));
  assert.equal(workerCalls.filter((c) => c.action === "fill").length, 1);
  console.log(
    "PASS: fictional Greenhouse preview, manual security handoff, fresh review, exact choices/date/month, preservation and no submission",
  );
} finally {
  await browser.close();
}
