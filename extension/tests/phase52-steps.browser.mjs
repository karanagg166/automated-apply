// Controlled fictional multipage employer journey, no real destination or submission.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";
const browser = await chromium.launch({ headless: true });
let nonGet = 0;
try {
  const page = await browser.newPage();
  await page.route("**/*", (route) => {
    if (route.request().method() !== "GET") nonGet++;
    return route.fulfill({
      contentType: "text/html",
      body: '<title>Fictional employer steps</title><h1>Fictional application</h1><div aria-current="step">Contact</div><form><label>Email<input type="email" id="email" required></label><button type="button" id="continue">Continue</button></form><script>window.submits=0;document.querySelector("form").onsubmit=e=>{e.preventDefault();window.submits++};document.querySelector("#continue").onclick=()=>{document.querySelector("[aria-current]").textContent="Experience";document.querySelector("form").innerHTML=\'<fieldset id="employment-a"><legend>Employer A</legend><label>Start date<input type="date" required id="start-a"></label></fieldset><fieldset id="employment-b"><legend>Employer B</legend><label>Start date<input type="date" required id="start-b"></label></fieldset><button type="submit">Submit</button>\';};</script>',
    });
  });
  await page.goto("https://fictional.example/application");
  const cdp = await page.context().newCDPSession(page);
  const { frameTree } = await cdp.send("Page.getFrameTree");
  const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
    frameId: frameTree.frame.id,
    worldName: "phase52-steps",
  });
  async function run(value) {
    const response = await cdp.send("Runtime.callFunctionOn", {
      executionContextId,
      functionDeclaration: formDOM.toString(),
      arguments: [{ value }],
      returnByValue: true,
      awaitPromise: true,
    });
    assert.equal(response.exceptionDetails, undefined);
    return response.result.value;
  }
  const contact = await run({
    operation: "inspect",
    only_empty: true,
    interactions_allowed: true,
  });
  assert.equal(contact.has_next, true);
  const filled = await run({
    operation: "fill",
    document_id: contact.document_id,
    only_empty: true,
    interaction_authorized: true,
    actions: [
      {
        field_id: contact.fields[0].field_id,
        kind: "email",
        value: "fictional@example.test",
      },
    ],
  });
  assert.equal(filled.results[0].status, "filled");
  // Owner performs save/continue. Extension never clicks a potentially submitting button.
  await page.locator("#continue").click();
  const stale = await run({
    operation: "fill",
    document_id: contact.document_id,
    only_empty: true,
    interaction_authorized: true,
    actions: [],
  });
  assert.equal(stale.state, "manual_required");
  const experience = await run({
    operation: "inspect",
    only_empty: true,
    interactions_allowed: true,
  });
  assert.notEqual(experience.document_id, contact.document_id);
  assert.notEqual(
    experience.fields[0].semantic_key,
    experience.fields[1].semantic_key,
  );
  assert.deepEqual(
    experience.fields.map((field) => field.page_step),
    ["Experience", "Experience"],
  );
  const result = await run({
    operation: "fill",
    document_id: experience.document_id,
    only_empty: true,
    interaction_authorized: true,
    actions: experience.fields.map((field, index) => ({
      field_id: field.field_id,
      kind: field.kind,
      value: index ? "2022-05-01" : "2020-01-01",
    })),
  });
  assert.equal(
    result.results.filter((field) => field.status === "filled").length,
    2,
  );
  assert.equal(await page.locator("#start-a").inputValue(), "2020-01-01");
  assert.equal(await page.locator("#start-b").inputValue(), "2022-05-01");
  assert.equal(await page.evaluate(() => window.submits), 0);
  assert.equal(nonGet, 0);
  console.log(
    JSON.stringify({
      cases: 1,
      steps: 2,
      verified_fields: 3,
      stale_step_rejected: true,
      employer_write_requests: nonGet,
      submissions: 0,
    }),
  );
} finally {
  await browser.close();
}
