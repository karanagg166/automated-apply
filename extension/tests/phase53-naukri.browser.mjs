// Isolated fictional Naukri-shaped DOM; no login, personal profile or employer traffic.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";
const browser = await chromium.launch({
  headless: true,
  args: ["--host-resolver-rules=MAP www.naukri.com ~NOTFOUND"],
});
let nonGet = 0;
try {
  const context = await browser.newContext();
  await context.route("https://www.naukri.com/**", (route) => {
    if (route.request().method() !== "GET") nonGet++;
    return route.fulfill({
      contentType: "text/html",
      body: '<header class="nI-gNb-header"><form role="search"><label>Keyword<input id="keyword" value="Owner search"></label></form></header><h1>Fictional Backend Engineer</h1><button>Apply</button><script>window.submits=0;window.retained="";</script>',
    });
  });
  const page = await context.newPage();
  await page.goto("https://www.naukri.com/job-listings-fictional-291026123456");
  const cdp = await context.newCDPSession(page);
  let executionContextId;
  async function isolatedWorld() {
    const { frameTree } = await cdp.send("Page.getFrameTree");
    ({ executionContextId } = await cdp.send("Page.createIsolatedWorld", {
      frameId: frameTree.frame.id,
      worldName: "phase53-fictional-naukri",
    }));
  }
  const run = async (request) => {
    const result = await cdp.send("Runtime.callFunctionOn", {
      executionContextId,
      functionDeclaration: formDOM.toString(),
      arguments: [{ value: request }],
      returnByValue: true,
      awaitPromise: true,
    });
    assert.equal(result.exceptionDetails, undefined);
    return result.result.value;
  };
  await isolatedWorld();
  const postingOnly = await run({ operation: "inspect", only_empty: true });
  assert.equal(postingOnly.fields.length, 0);
  assert.equal(postingOnly.completed_count, 0);
  assert.equal(postingOnly.has_submit, false);
  // Fixture setup models an owner-opened explicit application dialog. The test
  // never clicks the posting's Apply control or assumes that doing so is safe.
  await page.evaluate(() => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.innerHTML =
      '<form><label>Email<input id="email" type="email" required></label><label>Phone<input id="phone" value="owner-entered"></label><button type="submit">Submit</button></form>';
    document.body.append(dialog);
    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      window.submits++;
    });
    dialog.querySelector("#email").addEventListener("input", (event) => {
      window.retained = event.target.value;
    });
  });
  const inspected = await run({
    operation: "inspect",
    only_empty: true,
    interactions_allowed: true,
  });
  assert.deepEqual(
    inspected.fields.map((field) => field.label),
    ["Email"],
  );
  assert.equal(inspected.completed_count, 1);
  const stale = await run({
    operation: "validate_fill",
    document_id: postingOnly.document_id,
  });
  assert.equal(stale.state, "manual_required");
  const filled = await run({
    operation: "fill",
    document_id: inspected.document_id,
    only_empty: true,
    interaction_authorized: true,
    actions: [
      {
        field_id: inspected.fields[0].field_id,
        kind: "email",
        value: "alex@example.com",
      },
    ],
  });
  assert.equal(filled.results[0].status, "filled");
  assert.equal(await page.evaluate(() => window.retained), "alex@example.com");
  assert.equal(await page.locator("#keyword").inputValue(), "Owner search");
  assert.equal(await page.locator("#phone").inputValue(), "owner-entered");
  assert.equal(await page.evaluate(() => window.submits), 0);
  await page.reload();
  await isolatedWorld();
  const afterRefresh = await run({
    operation: "fill",
    document_id: inspected.document_id,
    actions: [],
  });
  assert.equal(afterRefresh.state, "manual_required");
  assert.equal(nonGet, 0);
  console.log(
    JSON.stringify({
      cases: 3,
      scope: "fictional isolated Chromium Naukri-shaped DOM",
      posting_search_excluded: true,
      retained_fields: 1,
      stale_and_refresh_rejected: true,
      existing_values_preserved: true,
      submissions: 0,
      employer_write_requests: nonGet,
      genuine_naukri_fill: false,
    }),
  );
} finally {
  await browser.close();
}
