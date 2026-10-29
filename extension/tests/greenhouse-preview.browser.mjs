// One fictional Greenhouse journey: real Chromium + inspector/bridge/popup,
// bounded fake native transport; no installed extension, live site or owner data.
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";

const application = "11111111-1111-4111-8111-111111111111";
const url = "https://job-boards.greenhouse.io/fictional-employer/jobs/1";
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 600, height: 1000 },
  });
  const requests = [],
    nativeCalls = [];
  const approved = new Map([
    ["Email", "alex@example.org"],
    ["Country", "Country 125"],
    ["Career stage", "Graduate"],
    ["Available start date", "2026-11-01"],
    ["End month", "2026-12"],
    ["Industry", "Software"],
    ["Full name", "Alex Example"],
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
    <div data-sitekey=fictional><p>Fictional security widget (no CAPTCHA service)</p></div>
    <button id=finish-fictional type=button onclick="document.querySelector('[data-sitekey]').remove();this.remove()">Complete fictional check</button>
    <button type=submit>Submit application</button></form>
    <script>window.events=[];for(const kind of ['input','change','submit'])document.addEventListener(kind,()=>window.events.push(kind));</script>`;
  await context.route("**/*", async (route) => {
    requests.push({
      method: route.request().method(),
      url: route.request().url(),
    });
    const target = new URL(route.request().url());
    if (target.href === url)
      return route.fulfill({ contentType: "text/html", body: html });
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
  let lastPlan;
  await popup.exposeFunction("fixtureScript", (req) =>
    form.evaluate(formDOM, req),
  );
  await popup.exposeFunction("fixtureNative", (req) => {
    nativeCalls.push(req);
    if (["inspect_form", "prepare_form_answers"].includes(req.command)) {
      lastPlan = {
        id: crypto.randomUUID(),
        application_id: application,
        packet_revision: 3,
        target_url: url,
        inspection: req.inspection,
        expires_at: "2099-01-01T00:00:00Z",
        state:
          req.inspection.state === "manual_required" ? "read_only" : "preview",
        approved_fields: [],
        actions: req.inspection.fields.map((f) => ({
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
    } else if (req.command === "authorize_form") {
      assert.equal(lastPlan.state, "preview");
      assert.ok(
        req.field_ids.every((id) =>
          lastPlan.actions.some(
            (a) => a.field_id === id && !a.preview_only && !a.needs_input,
          ),
        ),
      );
      lastPlan.state = "consumed";
      lastPlan.approved_fields = req.field_ids;
    } else assert.equal(req.command, "record_form_fill");
    return {
      version: 1,
      request_id: req.request_id,
      ok: true,
      data: { submitted: false, plan: lastPlan },
    };
  });
  await popup.addInitScript(
    ({ url }) => {
      window.chrome = {
        tabs: { query: async () => [{ id: 1, url }] },
        scripting: {
          executeScript: async (req) => [
            { result: await window.fixtureScript(req.args[0]) },
          ],
        },
        runtime: {
          sendNativeMessage: async (_host, req) => window.fixtureNative(req),
        },
        storage: {
          session: { get: async () => ({}) },
          onChanged: { addListener() {} },
        },
      };
    },
    { url },
  );
  await popup.goto("https://extension.fixture/popup.html");
  await popup
    .locator("details")
    .filter({ hasText: "Use an existing saved application" })
    .locator("summary")
    .click();
  await popup.locator("#application-id").fill(application);
  await popup.locator("#inspect-form").click();
  await popup
    .getByText("Read-only answers prepared.", { exact: false })
    .waitFor();
  assert.equal(await popup.locator("#fill-form").isDisabled(), true);
  const preview = await popup.locator("#form-plan").textContent();
  assert.match(preview, /completion is unverified/);
  assert.match(preview, /alex@example.org/);
  assert.match(preview, /Country 125/);
  assert.equal((preview.match(/Start year/g) || []).length, 2);
  assert.match(preview, /Employer 1/);
  assert.match(preview, /Employer 2/);
  assert.match(preview, /Sensitive self-identification/);
  assert.equal(
    nativeCalls.some((c) => c.command === "authorize_form"),
    false,
  );
  assert.deepEqual(await form.evaluate(() => window.events), []);
  const screenshot = new URL(
    "../../docs/screenshots/razorpay-fictional-preview.png",
    import.meta.url,
  );
  await mkdir(new URL("../../docs/screenshots/", import.meta.url), {
    recursive: true,
  });
  await popup.screenshot({ path: screenshot.pathname, fullPage: true });

  // This is a fixture button, not a real challenge. The old plan stays blocked.
  await form.locator("#finish-fictional").click();
  assert.equal(await popup.locator("#fill-form").isDisabled(), true);
  const oldDocument = lastPlan.inspection.document_id;
  await popup.locator("#inspect-form").click();
  await popup.getByText("5 answers ready.", { exact: false }).waitFor();
  assert.notEqual(lastPlan.inspection.document_id, oldDocument);
  await popup.locator("#fill-form").click();
  await popup.getByText("5 fields filled.", { exact: false }).waitFor();
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
  assert.equal(
    nativeCalls.filter((c) => c.command === "authorize_form").length,
    1,
  );
  console.log(
    "PASS: fictional Greenhouse Chromium preview, manual security handoff, fresh review, exact native choices/date/month, preservation and no submission",
  );
} finally {
  await browser.close();
}
