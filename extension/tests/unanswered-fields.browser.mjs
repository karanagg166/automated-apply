// Actual isolated Chromium; fictional intercepted pages only, no native host or owner data.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  let writes = 0;
  const url =
    "https://fictional-employer.zohorecruit.in/jobs/Careers/123456/Backend-Engineer?source=CareerSite&ref=fixture";
  await page.route("**/*", (route) => {
    assert.equal(route.request().method(), "GET");
    return route.fulfill({
      contentType: "text/html",
      body: `
      <form><label>Name<input name="name" value="Owner already answered"></label>
      <label>Email<input type="email" name="email"></label>
      <label>Project explanation<textarea name="project"></textarea></label>
      <label>Expected salary<input name="salary"></label>
      <label>Consent<input name="consent" type="checkbox"></label>
      <button type="submit">Submit application</button></form>
      <script>window.events=[]; for(const name of ['input','change','submit']) document.addEventListener(name,()=>window.events.push(name));</script>`,
    });
  });
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) writes += 1;
  });
  await page.goto(url);
  const inspect = async () =>
    await page.evaluate(
      `(${formDOM.toString()})({operation:"inspect",only_empty:true})`,
    );
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
  const result = await page.evaluate(
    ({ source, request }) => (0, eval)(`(${source})`)(request),
    {
      source: formDOM.toString(),
      request: {
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
      },
    },
  );
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
  console.log(
    "PASS: actual Chromium preserves existing/newly typed answers, fills only reviewed empty fields, leaves unknowns and consent untouched, exports no existing values, emits no events, makes zero writes/submissions.",
  );
} finally {
  await browser.close();
}
