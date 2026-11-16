import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Fictional Chromium acceptance only: no live destination, credentials or submission.
import assert from "node:assert/strict";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../form-dom.js";
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
let nonGet = 0,
  cases = 0;
try {
  for (const behavior of [
    "retained",
    "reset",
    "no_selection",
    "detached",
    "closed",
  ]) {
    const page = await browser.newPage();
    await page.route("**/*", (route) => {
      if (route.request().method() !== "GET") nonGet++;
      return route.fulfill({
        contentType: "text/html",
        body: `<form><label>Career stage<input role=combobox aria-expanded=${behavior === "closed" ? "false" : "true"} aria-controls=stages></label><div id=stages role=listbox ${behavior === "closed" ? "hidden" : ""}><div role=option>Graduate</div><div role=option>Experienced</div></div><button type=submit>Submit</button></form>`,
      });
    });
    await page.goto("https://fictional.example/application");
    await page.evaluate((behavior) => {
      window.submits = 0;
      window.optionClicks = 0;
      document.querySelector("form").addEventListener("submit", (e) => {
        window.submits++;
        e.preventDefault();
      });
      const input = document.querySelector("input"),
        list = document.querySelector("[role=listbox]");
      list.querySelector("[role=option]").addEventListener("click", (e) => {
        window.optionClicks++;
        if (behavior === "no_selection") return;
        input.value = e.target.textContent;
        input.setAttribute("aria-expanded", "false");
        list.hidden = true;
        if (behavior === "reset")
          setTimeout(() => {
            input.value = "";
          }, 350);
        if (behavior === "detached") list.remove();
      });
    }, behavior);
    const inspection = await page.evaluate(formDOM, {
      operation: "inspect",
      only_empty: true,
      interactions_allowed: true,
    });
    assert.equal(
      await page.evaluate(() => window.optionClicks),
      0,
      "inspection never opens/selects options",
    );
    if (behavior === "closed") {
      assert.equal(inspection.fields.length, 0);
      assert.ok(
        inspection.unsupported_controls.some(
          (control) => control.kind === "custom_combobox",
        ),
      );
    } else {
      assert.equal(inspection.fields[0].preview_only, false);
      const result = await page.evaluate(formDOM, {
        operation: "fill",
        document_id: inspection.document_id,
        only_empty: true,
        interaction_authorized: true,
        actions: [
          {
            field_id: inspection.fields[0].field_id,
            kind: "select",
            value: "Graduate",
          },
        ],
      });
      if (behavior === "retained") {
        assert.equal(result.state, "form_filled");
        assert.equal(result.results[0].status, "filled");
      }
      if (["reset", "no_selection"].includes(behavior))
        assert.equal(result.results[0].status, "failed");
      if (behavior === "detached")
        assert.equal(result.state, "manual_required");
      assert.equal(await page.evaluate(() => window.optionClicks), 1);
      assert.equal(result.submitted, false);
    }
    assert.equal(await page.evaluate(() => window.submits), 0);
    await page.close();
    cases++;
  }
  assert.equal(nonGet, 0);
  console.log(
    JSON.stringify({
      actual_chromium_combobox_cases: cases,
      non_get_requests: nonGet,
      submitted: false,
      live_sites_tested: 0,
    }),
  );
} finally {
  await browser.close();
}
