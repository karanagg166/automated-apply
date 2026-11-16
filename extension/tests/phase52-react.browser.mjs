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
const { chromium } =
  await import("../../frontend/node_modules/@playwright/test/index.mjs");
const browser = await chromium.launch({
  executablePath: fixtureExecutable(chromium),
  headless: true,
});
let cases = 0,
  writes = 0;
try {
  for (const [kind, reset] of [
    ["text", false],
    ["textarea", false],
    ["select", false],
    ["checkbox", false],
    ["radio", false],
    ["text", true],
  ]) {
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
    await page.evaluate(
      ({ kind, reset }) => {
        const h = React.createElement;
        function Form() {
          const [value, set] = React.useState(
            kind === "checkbox" || kind === "radio" ? false : "",
          );
          window.retainedReactValue = value;
          const props = {
            name: "answer",
            onChange: (event) =>
              set(
                kind === "checkbox" || kind === "radio"
                  ? event.target.checked
                  : event.target.value,
              ),
            onBlur: () => {
              if (reset) setTimeout(() => set(""), 350);
            },
          };
          if (kind === "checkbox" || kind === "radio") props.checked = value;
          else props.value = value;
          const control =
            kind === "textarea"
              ? h("textarea", props)
              : kind === "select"
                ? h(
                    "select",
                    props,
                    h("option", { value: "" }, "Select"),
                    h("option", { value: "remote" }, "Remote"),
                  )
                : h("input", { ...props, type: kind });
          return h(
            "form",
            {
              onSubmit: (event) => {
                window.submits++;
                event.preventDefault();
              },
            },
            h(
              "fieldset",
              {},
              h("legend", {}, "Work arrangement"),
              h(
                "label",
                {},
                kind === "radio" ? "Remote" : "Preferred work location",
                control,
              ),
            ),
            h("button", { type: "submit" }, "Submit"),
          );
        }
        window.submits = 0;
        ReactDOMClient.createRoot(document.querySelector("#root")).render(
          h(Form),
        );
      },
      { kind, reset },
    );
    await page.locator("input,textarea,select").waitFor();
    const cdp = await page.context().newCDPSession(page);
    const { frameTree } = await cdp.send("Page.getFrameTree");
    const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
      frameId: frameTree.frame.id,
      worldName: "phase52-react-retention",
    });
    const run = async (request) => {
      const result = await cdp.send("Runtime.callFunctionOn", {
        functionDeclaration: formDOM.toString(),
        executionContextId,
        arguments: [{ value: request }],
        returnByValue: true,
        awaitPromise: true,
      });
      assert.equal(result.exceptionDetails, undefined);
      return result.result.value;
    };
    const inspection = await run({
      operation: "inspect",
      only_empty: true,
      interactions_allowed: true,
    });
    assert.equal(inspection.fields.length, 1);
    assert.equal(inspection.fields[0].preview_only, false);
    const value =
      kind === "checkbox" || kind === "radio"
        ? "true"
        : kind === "select"
          ? "Remote"
          : "Alex Fictional";
    const result = await run({
      operation: "fill",
      document_id: inspection.document_id,
      only_empty: true,
      interaction_authorized: true,
      actions: [
        {
          field_id: inspection.fields[0].field_id,
          kind: inspection.fields[0].kind,
          value,
        },
      ],
    });
    const retained = await page.evaluate(() => window.retainedReactValue);
    assert.equal(
      retained,
      reset
        ? ""
        : kind === "checkbox" || kind === "radio"
          ? true
          : kind === "select"
            ? "remote"
            : "Alex Fictional",
    );
    if (reset) assert.equal(result.results[0].status, "failed");
    else {
      assert.equal(
        result.results[0].status,
        "filled",
        JSON.stringify({ kind, result }),
      );
      assert.equal(
        result.state,
        "form_filled",
        JSON.stringify({ kind, result }),
      );
    }
    assert.equal(result.submitted, false);
    assert.equal(await page.evaluate(() => window.submits), 0);
    cases++;
    await page.close();
  }
  assert.equal(writes, 0);
  console.log(
    JSON.stringify({
      actual_react_cases: cases,
      retained_after_blur_verified: 5,
      delayed_reset_detected: 1,
      non_get_requests: writes,
      submissions: 0,
      live_sites_filled: 0,
    }),
  );
} finally {
  await browser.close();
}
