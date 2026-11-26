// Actual MV3 permission denial: the worker cannot silently obtain activeTab.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { fixtureExecutable } from "../tests/browser-fixture-engine.mjs";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const profile = mkdtempSync(join(tmpdir(), "automated-apply-form-permission-"));
let context;
try {
  const extension = resolve(root, "extension");
  context = await chromium.launchPersistentContext(profile, {
    executablePath: fixtureExecutable(),
    headless: true,
    timeout: 15_000,
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "--host-resolver-rules=MAP * ~NOTFOUND",
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker", { timeout: 5_000 }));
  await context.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<label>Full name<input></label><button>Submit</button>",
    }),
  );
  const page = await context.newPage();
  await page.goto("https://jobs.lever.co/fictional-owner/fictional-permission");
  const result = await worker.evaluate(async () => {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs.length !== 1 || !Number.isInteger(tabs[0].id))
      throw new Error("fixture_target_tab_unavailable");
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tabs[0].id, frameIds: [0] },
        world: "ISOLATED",
        func: () => document.querySelectorAll("input").length,
      });
      return { denied: false };
    } catch (error) {
      return {
        denied:
          /Cannot access contents of (?:url|the page)|host permission/i.test(
            error.message,
          ),
      };
    }
  });
  assert.equal(
    result.denied,
    true,
    "Inspection must fail without the actual activeTab gesture grant",
  );
  console.log(
    JSON.stringify({
      state: "passed",
      browser: context.browser().version(),
      activeTab_silently_acquired: false,
      submitted: false,
    }),
  );
} finally {
  await context?.close();
  rmSync(profile, { recursive: true, force: true });
}
