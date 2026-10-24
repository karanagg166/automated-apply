// Actual MV3 APIs and Native Messaging in a disposable Chromium profile.
// This is separate evidence from installation/gestures in the owner's Chrome.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  chmodSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const [python, envFile, extensionId] = process.argv.slice(2);
assert.ok(python?.startsWith("/") && envFile?.startsWith("/"));
assert.match(extensionId || "", /^[a-p]{32}$/);
const profile = mkdtempSync(join(tmpdir(), "automated-apply-mv3-"));
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
let context;
try {
  const wrapper = join(profile, "native-host");
  writeFileSync(
    wrapper,
    `#!/bin/sh\ncd ${quote(root)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(envFile)} "$@"\n`,
    { mode: 0o700 },
  );
  chmodSync(wrapper, 0o700);
  mkdirSync(join(profile, "NativeMessagingHosts"), { mode: 0o700 });
  writeFileSync(
    join(profile, "NativeMessagingHosts/com.automated_apply.agent.json"),
    JSON.stringify({
      name: "com.automated_apply.agent",
      description: "Isolated Automated Apply test host",
      path: wrapper,
      type: "stdio",
      allowed_origins: [`chrome-extension://${extensionId}/`],
    }),
    { mode: 0o600 },
  );
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
    (await context.waitForEvent("serviceworker", { timeout: 15000 }));
  assert.equal(worker.url().split("/")[2], extensionId);
  const result = await worker.evaluate(async () => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await chrome.contextMenus.update("automated-apply-preview", {
      enabled: true,
    });
    const result = await chrome.runtime.sendNativeMessage(
      "com.automated_apply.agent",
      {
        version: 1,
        request_id: crypto.randomUUID(),
        command: "preview_application_url",
        url: "https://docs.google.com/forms/d/fictional-native-e2e/viewform",
        title: "Fictional form",
      },
    );
    await chrome.storage.session.set({ lastResult: result });
    const health = await chrome.runtime.sendNativeMessage(
      "com.automated_apply.agent",
      { version: 1, request_id: crypto.randomUUID(), command: "health" },
    );
    return { result, health };
  });
  assert.equal(result.result.ok, true, JSON.stringify(result.result));
  assert.equal(result.result.data.submitted, false);
  assert.equal(result.result.data.platform, "google_forms");
  assert.equal(result.health.ok, true);
  const page = await context.newPage();
  await page.goto(`chrome-extension://${extensionId}/popup.html`);
  await expect(page.locator("#status")).toContainText("returned a preview", {
    timeout: 10000,
  });
  await page.screenshot({
    path: resolve(root, "reports/phase1/isolated-mv3-popup.png"),
  });
  console.log(
    JSON.stringify({
      state: "passed",
      evidence:
        "actual MV3 native messaging with loopback HTTP and disposable PostgreSQL",
      context_menu_registered: true,
      owner_chrome_profile: false,
      submitted: false,
    }),
  );
} finally {
  if (context) await context.close();
  rmSync(profile, { recursive: true, force: true });
}
