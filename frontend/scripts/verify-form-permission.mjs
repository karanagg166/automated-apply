// Actual MV3 permission denial: the worker cannot silently obtain activeTab.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const profile = mkdtempSync(join(tmpdir(), "automated-apply-form-permission-"));
let context;
try {
  const extension = resolve(root, "extension");
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
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
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tabs[0].id, frameIds: [0] },
        world: "ISOLATED",
        func: () => document.querySelectorAll("input").length,
      });
      return { denied: false };
    } catch {
      return { denied: true };
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
