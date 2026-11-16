import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Actual installed React, an isolated CDP world and fictional intercepted pages.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { formDOM } from "../form-dom.js";

const require = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);
const reactRoot = dirname(require.resolve("react/package.json"));
const domRoot = dirname(require.resolve("react-dom/package.json"));
const schedulerRoot = dirname(
  createRequire(join(domRoot, "package.json")).resolve(
    "scheduler/package.json",
  ),
);
const modules = {
  react: readFileSync(join(reactRoot, "cjs/react.development.js"), "utf8"),
  "react-dom": readFileSync(
    join(domRoot, "cjs/react-dom.development.js"),
    "utf8",
  ),
  scheduler: readFileSync(
    join(schedulerRoot, "cjs/scheduler.development.js"),
    "utf8",
  ),
  client: readFileSync(
    join(domRoot, "cjs/react-dom-client.development.js"),
    "utf8",
  ),
};
const bundle = `(() => {
  const process = {env: {NODE_ENV: "development"}}, cache = {};
  const factories = {${Object.entries(modules)
    .map(
      ([name, source]) =>
        `${JSON.stringify(name)}: (exports, require) => {${source}\n}`,
    )
    .join(",")}};
  function require(name) { if (!cache[name]) { cache[name] = {}; factories[name](cache[name], require); } return cache[name]; }
  globalThis.React = require("react"); globalThis.ReactDOMClient = require("client");
})();`;
const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE
    ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
    : "../../frontend/node_modules/@playwright/test/index.mjs"
);
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
let cases = 0,
  writes = 0;
try {
  for (const dynamic of [false, true]) {
    const page = await browser.newPage();
    await page.route("**/*", (route) => {
      if (route.request().method() !== "GET") writes++;
      return route.fulfill({
        contentType: "text/html",
        body: '<div id="root"></div>',
      });
    });
    await page.goto("https://fictional.example/apply");
    await page.addScriptTag({ content: bundle });
    await page.evaluate((dynamic) => {
      const h = React.createElement;
      function Form() {
        const [values, set] = React.useState({
          name: "",
          location: "",
          remote: false,
          onsite: false,
        });
        window.reactValues = values;
        const change = (key, value) => set((old) => ({ ...old, [key]: value }));
        return h(
          "form",
          {
            onSubmit: (e) => {
              window.submitEvents++;
              e.preventDefault();
            },
          },
          h(
            "label",
            {},
            "Full name",
            h("input", {
              value: values.name,
              onChange: (e) => change("name", e.target.value),
            }),
          ),
          h(
            "label",
            {},
            "Work location",
            h(
              "select",
              {
                value: values.location,
                onChange: (e) => change("location", e.target.value),
              },
              h("option", { value: "" }, "Select"),
              h(
                "option",
                { value: dynamic && values.name ? "onsite" : "remote" },
                "Remote",
              ),
            ),
          ),
          h(
            "fieldset",
            {},
            h("legend", {}, "Work arrangement"),
            h(
              "label",
              {},
              "Remote",
              h("input", {
                type: "checkbox",
                checked: values.remote,
                onChange: (e) => change("remote", e.target.checked),
              }),
            ),
          ),
          h(
            "fieldset",
            {},
            h("legend", {}, "Office preference"),
            h(
              "label",
              {},
              "Onsite",
              h("input", {
                type: "radio",
                name: "office",
                checked: values.onsite,
                onChange: (e) => change("onsite", e.target.checked),
              }),
            ),
          ),
          h("button", { type: "submit" }, "Submit"),
        );
      }
      window.submitEvents = 0;
      ReactDOMClient.createRoot(document.querySelector("#root")).render(
        h(Form),
      );
    }, dynamic);
    await page.locator("input").first().waitFor();
    const cdp = await page.context().newCDPSession(page);
    const { frameTree } = await cdp.send("Page.getFrameTree");
    const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
      frameId: frameTree.frame.id,
      worldName: "phase35-react-form-test",
    });
    const evaluate = async (request) => {
      const result = await cdp.send("Runtime.callFunctionOn", {
        functionDeclaration: formDOM.toString(),
        executionContextId,
        arguments: [{ value: request }],
        returnByValue: true,
      });
      assert.equal(result.exceptionDetails, undefined);
      return result.result.value;
    };
    const inspection = await evaluate({ operation: "inspect" });
    const result = await evaluate({
      operation: "fill",
      document_id: inspection.document_id,
      emit_events: true,
      actions: [
        { field_id: "f0", kind: "text", value: "Alex Fictional" },
        { field_id: "f1", kind: "select", value: "Remote" },
        { field_id: "f2", kind: "checkbox", value: "true" },
        { field_id: "f3", kind: "radio", value: "true" },
      ],
    });
    // React re-renders this radio-containing step after the first answer.
    // The reviewed snapshot must stop before touching the remaining controls.
    assert.equal(result.state, "manual_required");
    assert.equal(await page.locator("select").inputValue(), "");
    assert.deepEqual(await page.evaluate(() => window.reactValues), {
      name: "Alex Fictional",
      location: "",
      remote: false,
      onsite: false,
    });
    assert.equal(await page.evaluate(() => window.submitEvents), 0);
    assert.equal(writes, 0);
    cases++;
    await page.close();
  }
  for (const kind of ["checkbox", "radio"]) {
    const page = await browser.newPage();
    await page.route("**/*", (route) => {
      if (route.request().method() !== "GET") writes++;
      return route.fulfill({
        contentType: "text/html",
        body: '<div id="root"></div>',
      });
    });
    await page.goto("https://fictional.example/apply");
    await page.addScriptTag({ content: bundle });
    await page.evaluate((kind) => {
      const h = React.createElement;
      function Form() {
        const [checked, set] = React.useState(false);
        window.reactChecked = checked;
        return h(
          "form",
          {
            onSubmit: (e) => {
              window.submitEvents++;
              e.preventDefault();
            },
          },
          h(
            "fieldset",
            {},
            h("legend", {}, "Work arrangement"),
            h(
              "label",
              {},
              "Remote",
              h("input", {
                type: kind,
                name: "arrangement",
                checked,
                onChange: (e) => set(e.target.checked),
              }),
            ),
          ),
        );
      }
      window.submitEvents = 0;
      ReactDOMClient.createRoot(document.querySelector("#root")).render(
        h(Form),
      );
    }, kind);
    await page.locator("input").waitFor();
    const cdp = await page.context().newCDPSession(page);
    const { frameTree } = await cdp.send("Page.getFrameTree");
    const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
      frameId: frameTree.frame.id,
      worldName: "phase35-react-choice-test",
    });
    const evaluate = async (request) => {
      const result = await cdp.send("Runtime.callFunctionOn", {
        functionDeclaration: formDOM.toString(),
        executionContextId,
        arguments: [{ value: request }],
        returnByValue: true,
      });
      assert.equal(result.exceptionDetails, undefined);
      return result.result.value;
    };
    const inspection = await evaluate({ operation: "inspect" });
    const result = await evaluate({
      operation: "fill",
      document_id: inspection.document_id,
      emit_events: true,
      actions: [{ field_id: "f0", kind, value: "true" }],
    });
    assert.equal(
      await page.evaluate(() => window.reactChecked),
      true,
      `${kind}: DOM success must update actual React state (${result.state})`,
    );
    assert.equal(await page.locator("input").isChecked(), true);
    assert.equal(await page.evaluate(() => window.submitEvents), 0);
    assert.equal(writes, 0);
    cases++;
    await page.close();
  }
  console.log(
    JSON.stringify({
      actual_react_cases_passed: cases,
      form_posts: writes,
      submitted: false,
    }),
  );
} finally {
  await browser.close();
}
