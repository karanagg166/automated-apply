import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Fictional intercepted pages only. No employer request, installed profile or native host.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { formDOM } from "../form-dom.js";

const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE
    ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
    : "../../frontend/node_modules/@playwright/test/index.mjs"
);
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
let cases = 0;
try {
  for (const change of [
    "destination",
    "navigation",
    "replacement",
    "label",
    "login",
    "value",
  ]) {
    const page = await browser.newPage();
    let writes = 0;
    await page.route("**/*", (route) => {
      if (route.request().method() !== "GET") writes += 1;
      return route.fulfill({
        contentType: "text/html",
        body: '<form action="/original"><label>Full name<input id="first"></label><label>Email<input id="second" type="email"></label><button type="submit">Submit</button></form>',
      });
    });
    await page.goto("https://fictional.example/apply");
    const inspection = await page.evaluate(formDOM, {
      operation: "inspect",
      only_empty: true,
    });
    assert.equal(inspection.state, "ready");
    await page.evaluate((change) => {
      window.changeEvents = 0;
      document
        .querySelector("#first")
        .addEventListener("change", () => window.changeEvents++);
      document.querySelector("#first").addEventListener("input", () => {
        const second = document.querySelector("#second");
        if (change === "destination") document.forms[0].action = "/changed";
        if (change === "navigation") history.pushState({}, "", "/other-job");
        if (change === "replacement")
          second.replaceWith(second.cloneNode(true));
        if (change === "label")
          second.parentElement.firstChild.textContent = "Government ID";
        if (change === "login") {
          const password = document.createElement("input");
          password.type = "password";
          document.forms[0].append(password);
        }
        if (change === "value") second.value = "owner-entered@example.com";
      });
    }, change);
    const result = await page.evaluate(formDOM, {
      operation: "fill",
      document_id: inspection.document_id,
      only_empty: true,
      emit_events: true,
      actions: inspection.fields.map((field, i) => ({
        field_id: field.field_id,
        kind: field.kind,
        value: i ? "draft@example.com" : "Alex Fictional",
      })),
    });
    assert.equal(result.submitted, false);
    assert.notEqual(result.state, "form_filled", change);
    assert.equal(
      await page.locator("#second").inputValue(),
      change === "value" ? "owner-entered@example.com" : "",
      change,
    );
    assert.equal(writes, 0);
    if (change !== "value")
      assert.equal(await page.evaluate("window.changeEvents"), 0);
    cases += 1;
    await page.close();
  }
  // Required manual fields must keep a successful subset from claiming completion.
  const page = await browser.newPage();
  await page.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<form><label>Full name<input required></label><label>Portfolio<input type="url" required></label></form>',
    }),
  );
  await page.goto("https://fictional.example/apply");
  const inspection = await page.evaluate(formDOM, {
    operation: "inspect",
    only_empty: true,
  });
  const action = {
    field_id: inspection.fields[0].field_id,
    kind: "text",
    value: "Alex Fictional",
  };
  const request = {
    operation: "fill",
    document_id: inspection.document_id,
    only_empty: true,
    actions: [action],
  };
  const result = await page.evaluate(formDOM, request);
  assert.equal(result.state, "needs_input");
  assert.equal(result.results[0].status, "filled");
  cases += 1;
  assert.equal(
    (await page.evaluate(formDOM, request)).state,
    "manual_required",
  );
  cases += 1;
  await page.close();
  // The separate Chrome worker shares this DOM engine and must also preserve values.
  const worker = await browser.newPage();
  await worker.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<form action="/apply"><label>Full name<input value="Owner answer"></label><label>Resume<input type="file" required></label></form>',
    }),
  );
  await worker.goto("https://fictional.example/apply");
  const workerInspection = await worker.evaluate(formDOM, {
    operation: "inspect",
  });
  const workerResult = await worker.evaluate(formDOM, {
    operation: "fill",
    document_id: workerInspection.document_id,
    emit_events: true,
    actions: [
      {
        field_id: workerInspection.fields[0].field_id,
        kind: "text",
        value: "Replacement",
      },
    ],
  });
  assert.equal(workerResult.results[0].status, "untouched");
  assert.equal(
    await worker.locator("input").first().inputValue(),
    "Owner answer",
  );
  cases += 1;
  await worker.locator('input[type="file"]').setInputFiles({
    name: "fictional.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 fictional"),
  });
  const uploadRequest = {
    operation: "upload_element",
    document_id: workerInspection.document_id,
    field_id: workerInspection.fields[1].field_id,
  };
  assert.equal(await worker.evaluate(formDOM, uploadRequest), null);
  assert.equal(
    (
      await worker.evaluate(formDOM, {
        operation: "verify_fill",
        document_id: workerInspection.document_id,
      })
    ).state,
    "form_filled",
  );
  cases += 1;
  await worker.locator('input[type="file"]').setInputFiles([]);
  await worker.evaluate("document.forms[0].action='/changed'");
  assert.equal(await worker.evaluate(formDOM, uploadRequest), null);
  cases += 1;
  await worker.close();
  for (const change of ["value", "disabled", "hidden", "replacement"]) {
    const dropdown = await browser.newPage();
    await dropdown.route("**/*", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: '<form><label>Work location<select><option value="">Select</option><option value="remote">Remote</option></select></label></form>',
      }),
    );
    await dropdown.goto("https://fictional.example/apply");
    const snapshot = await dropdown.evaluate(formDOM, {
      operation: "inspect",
      only_empty: true,
    });
    await dropdown.evaluate((change) => {
      const option = document.querySelectorAll("option")[1];
      if (change === "value") option.value = "onsite";
      if (change === "disabled") option.disabled = true;
      if (change === "hidden") option.hidden = true;
      if (change === "replacement") option.replaceWith(option.cloneNode(true));
    }, change);
    const result = await dropdown.evaluate(formDOM, {
      operation: "fill",
      document_id: snapshot.document_id,
      actions: [{ field_id: "f0", kind: "select", value: "Remote" }],
      only_empty: true,
    });
    assert.equal(result.state, "manual_required", change);
    assert.equal(await dropdown.locator("select").inputValue(), "");
    cases++;
    await dropdown.close();
  }
  // Another inspection in this same document must revoke the earlier snapshot.
  const reinspection = await browser.newPage();
  await reinspection.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<form><label>Full name<input></label></form>",
    }),
  );
  await reinspection.goto("https://fictional.example/apply");
  const old = await reinspection.evaluate(formDOM, { operation: "inspect" });
  const fresh = await reinspection.evaluate(formDOM, { operation: "inspect" });
  assert.notEqual(old.document_id, fresh.document_id);
  assert.equal(
    (
      await reinspection.evaluate(formDOM, {
        operation: "fill",
        document_id: old.document_id,
        actions: [{ field_id: "f0", kind: "text", value: "Stale answer" }],
      })
    ).state,
    "manual_required",
  );
  assert.equal(await reinspection.locator("input").inputValue(), "");
  cases++;
  await reinspection.close();
  for (const kind of ["radio", "checkbox"]) {
    const group = await browser.newPage();
    await group.route("**/*", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: `<form><label>Full name<input id="first"></label><fieldset><legend>Work arrangement</legend><label>Remote<input id="remote" type="${kind}" name="arrangement"></label><label>Onsite<input id="onsite" type="${kind}" name="arrangement"></label></fieldset></form>`,
      }),
    );
    await group.goto("https://fictional.example/apply");
    const snapshot = await group.evaluate(formDOM, { operation: "inspect" });
    await group.evaluate(() =>
      document.querySelector("#first").addEventListener("input", () => {
        document.querySelector("#onsite").checked = true;
      }),
    );
    const result = await group.evaluate(formDOM, {
      operation: "fill",
      document_id: snapshot.document_id,
      emit_events: true,
      actions: [
        { field_id: "f0", kind: "text", value: "Fictional" },
        { field_id: "f1", kind, value: "true" },
      ],
    });
    assert.equal(result.state, "needs_input");
    assert.equal(result.results[1].status, "untouched");
    assert.equal(await group.locator("#remote").isChecked(), false);
    assert.equal(await group.locator("#onsite").isChecked(), true);
    cases++;
    await group.close();
  }
  for (const asynchronous of [false, true]) {
    const controlled = await browser.newPage();
    await controlled.route("**/*", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<form><label>Full name<input></label></form>",
      }),
    );
    await controlled.goto("https://fictional.example/apply");
    const snapshot = await controlled.evaluate(formDOM, {
      operation: "inspect",
    });
    await controlled.evaluate((asynchronous) => {
      const input = document.querySelector("input");
      input.addEventListener("input", () => {
        if (asynchronous)
          setTimeout(() => {
            input.value = "";
          }, 0);
        else input.value = "";
      });
    }, asynchronous);
    const result = await controlled.evaluate(formDOM, {
      operation: "fill",
      document_id: snapshot.document_id,
      emit_events: true,
      actions: [{ field_id: "f0", kind: "text", value: "Fictional" }],
    });
    if (!asynchronous) {
      assert.equal(result.state, "needs_input");
      assert.equal(result.results[0].status, "failed");
    }
    await controlled.waitForFunction(
      () => document.querySelector("input").value === "",
    );
    const verification = await controlled.evaluate(formDOM, {
      operation: "verify_fill",
      document_id: snapshot.document_id,
    });
    assert.equal(verification.state, "needs_input");
    assert.deepEqual(verification.results, [
      { field_id: "f0", status: "failed" },
    ]);
    cases++;
    await controlled.close();
  }
  for (const label of [
    "Gender",
    "Disability status",
    "Passport number",
    "Government ID",
    "Sexual orientation",
  ]) {
    const sensitive = await browser.newPage();
    await sensitive.route("**/*", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: `<form><label>${label}<input></label></form>`,
      }),
    );
    await sensitive.goto("https://fictional.example/apply");
    const blocked = await sensitive.evaluate(formDOM, {
      operation: "inspect",
      only_empty: true,
    });
    assert.ok(["manual_required", "unsupported"].includes(blocked.state));
    assert.equal(blocked.fields.length, 0);
    cases += 1;
    await sensitive.close();
  }
  console.log(
    JSON.stringify({
      cases_passed: cases,
      submitted: false,
      external_requests: 0,
    }),
  );
} finally {
  await browser.close();
}
