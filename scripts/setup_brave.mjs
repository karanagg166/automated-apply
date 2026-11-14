// Register the extension in a fresh owned Brave profile, using inactive setup
// tabs only. Never opens a portal, imports cookies or enables queue commands.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const profile = join(root, ".local/browser-profiles/brave-automation");
const release = JSON.parse(
  readFileSync(
    join(root, ".local/runtime-support/brave-extension-current.json"),
  ),
);
const extension = resolve(release.extension_path);
assert(
  extension.startsWith(join(root, ".local/runtime-support/brave-extension/")),
  "owned_brave_extension_required",
);
const executable =
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const id = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
assert(existsSync(executable), "brave_not_installed");
assert(existsSync(profile), "private_brave_profile_not_prepared");
const manifest = JSON.parse(readFileSync(join(extension, "manifest.json")));
const digest = createHash("sha256")
  .update(Buffer.from(manifest.key, "base64"))
  .digest("hex")
  .slice(0, 32);
assert.equal(
  [...digest].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join(""),
  id,
);
const endpointFile = join(profile, "DevToolsActivePort");
if (existsSync(endpointFile)) {
  const [oldPort] = readFileSync(endpointFile, "utf8").trim().split("\n");
  assert(/^\d{4,5}$/.test(oldPort), "invalid_old_owned_endpoint");
  let live = false;
  try {
    live = (
      await fetch(`http://127.0.0.1:${oldPort}/json/version`, {
        signal: AbortSignal.timeout(1000),
        redirect: "error",
      })
    ).ok;
  } catch {
    /* closed owned process */
  }
  assert(!live, "existing_brave_debug_endpoint_preserved");
  renameSync(endpointFile, `${endpointFile}.previous-${Date.now()}`);
}
const child = spawn(
  executable,
  [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);
let browser;
try {
  for (let i = 0; !existsSync(endpointFile); i++) {
    assert(i < 300 && child.exitCode === null, "brave_setup_start_timeout");
    await new Promise((r) => setTimeout(r, 100));
  }
  const [port] = readFileSync(endpointFile, "utf8").trim().split("\n");
  assert(/^\d+$/.test(port), "invalid_owned_debug_endpoint");
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {
    noDefaults: true,
  });
  const context = browser.contexts()[0];
  context.setDefaultTimeout(30000);
  const worker =
    context
      .serviceWorkers()
      .find((w) => w.url() === `chrome-extension://${id}/background.js`) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (w) => w.url() === `chrome-extension://${id}/background.js`,
      timeout: 30000,
    }));
  const ownerBefore = await worker.evaluate(async () =>
    (await chrome.tabs.query({ active: true })).map(({ id, windowId }) => ({
      id,
      windowId,
    })),
  );
  const tabId = await worker.evaluate(async () => {
    const [active] = await chrome.tabs.query({ active: true });
    assertOwnedWindow(active);
    function assertOwnedWindow(tab) {
      if (!tab?.windowId) throw Error("owned_window_required");
    }
    const tab = await chrome.tabs.create({
      url: chrome.runtime.getURL("popup.html"),
      active: false,
      windowId: active.windowId,
    });
    return tab.id;
  });
  let popup;
  for (let i = 0; !popup; i++) {
    popup = context
      .pages()
      .find((p) => p.url() === `chrome-extension://${id}/popup.html`);
    assert(i < 300, "inactive_popup_unavailable");
    if (!popup) await new Promise((r) => setTimeout(r, 100));
  }
  await popup.waitForLoadState("domcontentloaded");
  const health = await popup.evaluate(async () => {
    const request = {
      version: 1,
      request_id: crypto.randomUUID(),
      command: "health",
    };
    const response = await chrome.runtime.sendNativeMessage(
      "com.automated_apply.brave",
      request,
    );
    return {
      ok: response?.ok === true && response.request_id === request.request_id,
      code: response?.error_code,
    };
  });
  assert(health.ok, health.code || "brave_native_health_failed");
  const status = await popup.evaluate(async () => {
    const result = await chrome.runtime.sendMessage({
      command: "chrome_profile",
      action: "connect",
      label: "Brave automation",
    });
    return {
      ok: result?.ok,
      connected: result?.connected,
      commandsEnabled: result?.commandsEnabled,
      code: result?.error_code,
    };
  });
  assert(
    status.ok && status.connected && !status.commandsEnabled,
    status.code || "brave_profile_connection_failed",
  );
  const siteAccess = await popup.evaluate(() =>
    chrome.permissions.contains({ origins: ["https://www.naukri.com/*"] }),
  );
  await worker.evaluate((tabId) => chrome.tabs.remove(tabId), tabId);
  const ownerAfter = await worker.evaluate(async () =>
    (await chrome.tabs.query({ active: true })).map(({ id, windowId }) => ({
      id,
      windowId,
    })),
  );
  assert.deepEqual(ownerAfter, ownerBefore, "owned_active_tab_changed");
  const result = {
    browser: "brave",
    version: browser.version(),
    native_health: "PASS",
    connected: true,
    queue_commands_enabled: false,
    owned_active_tab_preserved: true,
    naukri_site_access: siteAccess,
    real_portal_requests: 0,
    extension_version: manifest.version,
    profile_stopped_for_owner_login: true,
  };
  const target = resolve(
    root,
    ".local/operational-20261115/brave-setup.private.json",
  );
  writeFileSync(target, JSON.stringify(result, null, 2) + "\n", {
    flag: "wx",
    mode: 0o600,
  });
  console.log(JSON.stringify(result));
} finally {
  if (browser) await browser.close().catch(() => {});
  if (child.exitCode === null) child.kill("SIGTERM");
  if (child.exitCode === null)
    await new Promise((r) => {
      child.once("exit", r);
      setTimeout(r, 5000);
    });
}
