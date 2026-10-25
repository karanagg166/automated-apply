// Real Chrome for Testing + native host + loopback backend. No form field actions.
// UI gestures are invoked through the extension's own preview entry point; owner
// toolbar/context-menu gestures remain a separate acceptance item.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  chmodSync,
  cpSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
const [python, envFile, formFile] = process.argv.slice(2);
assert.ok(python?.startsWith("/") && envFile?.startsWith("/"));
const root = resolve("..");
const extension = process.env.PHASE1_EXTENSION_DIRECTORY
  ? resolve(process.env.PHASE1_EXTENSION_DIRECTORY)
  : join(root, "extension");
const manifest = JSON.parse(readFileSync(join(extension, "manifest.json")));
const keyHash = createHash("sha256")
  .update(Buffer.from(manifest.key, "base64"))
  .digest("hex")
  .slice(0, 32);
const identity = [...keyHash]
  .map((c) => String.fromCharCode(97 + parseInt(c, 16)))
  .join("");
const base = mkdtempSync(join(tmpdir(), "automated-apply-actual-chrome-"));
chmodSync(base, 0o700);
const profile = join(base, "profile");
mkdirSync(join(profile, "NativeMessagingHosts"), {
  recursive: true,
  mode: 0o700,
});
const quote = (s) => "'" + s.replaceAll("'", "'\\''") + "'";
const wrapper = join(base, "native-host");
const bindWrapper = (configuration) =>
  writeFileSync(
    wrapper,
    `#!/bin/sh\ncd ${quote(root)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(configuration)} "$@"\n`,
    { mode: 0o700 },
  );
bindWrapper(envFile);
const hostPath = join(
  profile,
  "NativeMessagingHosts/com.automated_apply.agent.json",
);
const host = {
  name: "com.automated_apply.agent",
  description: "Isolated Phase1 acceptance",
  type: "stdio",
  path: wrapper,
  allowed_origins: [`chrome-extension://${identity}/`],
};
writeFileSync(hostPath, JSON.stringify(host), { mode: 0o600 });
const report = {
  evidence_type: "actual_Chrome_for_Testing_MV3_native_HTTP",
  profile: "isolated",
  stable_extension_id: identity,
  checks: [],
  correlations: [],
  form_fields_read: false,
  form_fields_filled: false,
  submitted: false,
  owner_gestures_verified: false,
};
const previewResults = [];
let context;
const launch = async (path = extension) => {
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${path}`, `--load-extension=${path}`],
  });
  report.browser_version = await context.browser().version();
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker", { timeout: 15000 }));
  assert.equal(worker.url().split("/")[2], identity);
  return worker;
};
const preview = async (worker, page) => {
  let control = context
    .pages()
    .find((p) => p.url() === `chrome-extension://${identity}/popup.html`);
  if (!control) {
    control = await context.newPage();
    await control.goto(`chrome-extension://${identity}/popup.html`);
  }
  const result = await control.evaluate(
    async ({ url, title }) => {
      const module = await import(chrome.runtime.getURL("preview.js"));
      return await module.preview({ id: 123, url, title });
    },
    { url: page.url(), title: await page.title() },
  );
  if (result.ok) {
    assert.equal(result.data.submitted, false);
    report.correlations.push(result.correlation_id);
    previewResults.push(result);
  } else {
    report.last_preview_error = result.error_code;
  }
  return result;
};
try {
  const endpointLine = readFileSync(envFile, "utf8").match(
    /^LOCAL_AGENT_ENDPOINT=(.*)$/m,
  );
  assert.ok(endpointLine, "local backend endpoint required");
  const rawEndpoint = endpointLine[1].trim();
  const endpoint = rawEndpoint.startsWith('"')
    ? JSON.parse(rawEndpoint)
    : rawEndpoint;
  assert.match(endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
  let ready = false;
  for (let attempt = 1; attempt <= 15; attempt++) {
    report.startup_health_attempts = attempt;
    try {
      ready = (
        await fetch(`${endpoint}/health`, { signal: AbortSignal.timeout(2000) })
      ).ok;
    } catch {
      /* A bounded cold-start wait; later offline tests still require failure. */
    }
    if (ready) break;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  assert.equal(ready, true, "local backend did not become healthy");
  let worker = await launch();
  let page = context.pages()[0];
  await page.goto("https://example.org/");
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("ordinary_https");
  await page.reload();
  await new Promise((r) => setTimeout(r, 1600));
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("page_refresh");
  const cdp = await context.newCDPSession(page);
  await cdp.send("ServiceWorker.enable");
  await cdp.send("ServiceWorker.stopAllWorkers");
  const control = context.pages().find((p) => p.url().endsWith("/popup.html"));
  await control.reload();
  await control.locator("#repair").click();
  await expect(control.locator("#menu-status")).toContainText("registered");
  worker =
    context.serviceWorkers().find((w) => w.url().includes(identity)) ||
    (await context.waitForEvent("serviceworker", { timeout: 10000 }));
  await page.goto("https://example.org/worker-recovery");
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("service_worker_stop_and_message_recovery");
  await cdp.detach();
  const originalConfiguration = readFileSync(envFile, "utf8");
  assert.equal(
    (originalConfiguration.match(/^LOCAL_AGENT_ENDPOINT=.*$/gm) || []).length,
    1,
  );
  const offlineConfiguration = join(base, "offline.private.env");
  writeFileSync(
    offlineConfiguration,
    originalConfiguration.replace(
      /^LOCAL_AGENT_ENDPOINT=.*$/m,
      'LOCAL_AGENT_ENDPOINT="http://127.0.0.1:18089"',
    ),
    { mode: 0o600 },
  );
  bindWrapper(offlineConfiguration);
  await page.goto("https://example.org/phase1-offline");
  const offline = await preview(worker, page);
  assert.equal(offline.error_code, "backend_offline");
  const offlinePopup = context
    .pages()
    .find((p) => p.url().endsWith("/popup.html"));
  await expect(offlinePopup.locator("#status")).toContainText(
    "backend_offline",
  );
  report.checks.push("backend_offline_refused_loopback_visible");
  bindWrapper(envFile);
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("backend_recovery");
  if (formFile) {
    const { form_url } = JSON.parse(readFileSync(formFile));
    assert.equal(new URL(form_url).hostname, "docs.google.com");
    await page.goto(form_url, { waitUntil: "domcontentloaded" });
    assert.equal(new URL(page.url()).hostname, "docs.google.com");
    assert.ok(new URL(page.url()).pathname.startsWith("/forms/"));
    assert.equal((await preview(worker, page)).ok, true);
    report.checks.push("real_approved_google_form_preview");
    // Exercise a real HTTP redirect into the approved target, without any form input.
    const redirect =
      "https://www.google.com/url?q=" + encodeURIComponent(form_url);
    await page.goto(redirect, { waitUntil: "domcontentloaded" });
    if (new URL(page.url()).hostname === "www.google.com") {
      const link = page.locator("a").filter({ hasText: "here" }).first();
      if (await link.count()) await link.click();
    }
    if (new URL(page.url()).hostname === "docs.google.com") {
      assert.equal((await preview(worker, page)).ok, true);
      report.checks.push("real_google_redirect_to_form");
    } else {
      report.redirect_status =
        "google_redirect_interstitial_owner_action_required";
    }
  }
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${identity}/popup.html`);
  await expect(popup.locator("#status")).toContainText("returned a preview");
  await popup.screenshot({
    path: join(root, "reports/phase1/current/actual-chrome-popup.png"),
  });
  report.checks.push("rendered_extension_popup");
  await popup.close();
  const unsupported = await context
    .pages()
    .find((p) => p.url().endsWith("/popup.html"))
    .evaluate(async () => {
      const { preview } = await import(chrome.runtime.getURL("preview.js"));
      return await preview({ id: 999, url: "chrome://extensions" });
    });
  assert.equal(unsupported.error_code, "unsupported_page");
  report.checks.push("unsupported_page");
  const duplicates = await context
    .pages()
    .find((p) => p.url().endsWith("/popup.html"))
    .evaluate(async () => {
      const { preview } = await import(chrome.runtime.getURL("preview.js"));
      return await Promise.all([
        preview({ id: 42, url: "https://example.org/duplicate" }),
        preview({ id: 42, url: "https://example.org/duplicate" }),
      ]);
    });
  assert.equal(duplicates[0].request_id, duplicates[1].request_id);
  report.checks.push("duplicate_gesture_coalesced");
  // Chrome's real origin gate rejects an obsolete registration, before the host runs.
  writeFileSync(
    hostPath,
    JSON.stringify({
      ...host,
      allowed_origins: [`chrome-extension://${"a".repeat(32)}/`],
    }),
  );
  const stale = await worker.evaluate(async () => {
    try {
      await chrome.runtime.sendNativeMessage("com.automated_apply.agent", {
        version: 1,
        request_id: crypto.randomUUID(),
        command: "health",
      });
      return "unexpected_success";
    } catch (e) {
      return /forbidden/i.test(e.message)
        ? "origin_rejected"
        : "unexpected_error";
    }
  });
  assert.equal(stale, "origin_rejected");
  report.checks.push("stale_extension_origin_rejected");
  writeFileSync(hostPath, JSON.stringify(host));
  const management = await context.newPage();
  await management.goto("chrome://extensions");
  const developer = management.getByRole("switch", {
    name: "Developer mode",
    exact: true,
  });
  if (!(await developer.isChecked())) await developer.click();
  await management.getByRole("button", { name: "Reload", exact: true }).click();
  await new Promise((r) => setTimeout(r, 800));
  report.reload_ui = await management.locator("body").ariaSnapshot();
  const wake = await context.newPage();
  await wake.goto(`chrome-extension://${identity}/popup.html`);
  await expect(wake.locator("#menu-status")).toContainText("registered");
  worker =
    context.serviceWorkers().find((w) => w.url().includes(identity)) ||
    (await context.waitForEvent("serviceworker", { timeout: 10000 }));
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("extension_reload");
  await context.close();
  context = null;
  const relocated = join(base, "relocated-extension");
  cpSync(extension, relocated, { recursive: true });
  worker = await launch(relocated);
  page = context.pages()[0];
  await page.goto("https://example.org/");
  assert.equal((await preview(worker, page)).ok, true);
  report.checks.push("chrome_restart_and_relocated_install");
  writeFileSync(
    join(root, "reports/phase1/current/actual-chrome-results.private.json"),
    JSON.stringify(previewResults, null, 2) + "\n",
    { mode: 0o600 },
  );
  writeFileSync(
    join(root, "reports/phase1/current/actual-chrome-acceptance.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(JSON.stringify(report));
} catch (error) {
  report.failure_stage = String(error.message)
    .replace(/chrome-extension:\/\/[^/]+/g, "chrome-extension://[stable-id]")
    .slice(0, 400);
  writeFileSync(
    join(root, "reports/phase1/current/actual-chrome-attempt.json"),
    JSON.stringify(report, null, 2),
  );
  throw error;
} finally {
  if (context) await context.close();
  rmSync(base, { recursive: true, force: true });
}
