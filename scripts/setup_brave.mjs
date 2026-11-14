// Register the extension in a fresh owned Brave profile, using inactive setup
// tabs only. Never opens a portal, imports cookies or enables queue commands.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  openSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";
import {
  assertSetupProfile,
  assertSetupTabs,
  stoppedQueue,
} from "./brave_setup_policy.mjs";
assert.equal(process.argv.length, 2, "setup_takes_no_runtime_reload_flags");

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
for (const file of release.files) {
  assert(
    file.name === file.name.split("/").pop() && !file.name.includes("\\"),
    "invalid_owned_release_file",
  );
  assert.equal(
    createHash("sha256")
      .update(readFileSync(join(extension, file.name)))
      .digest("hex"),
    file.sha256,
    "owned_release_bytes_changed",
  );
}
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
assert(
  /^[a-f0-9]{40}$/.test(release.native_source_sha),
  "native_release_required",
);
const configPath = join(
  root,
  ".local/runtime-support/rust-native",
  release.native_source_sha,
  "automated-apply-native.private.env",
);
const queue = await stoppedQueue(configPath);
const entry = JSON.parse(
  readFileSync(join(profile, "Default/Secure Preferences")),
).extensions?.settings?.[id];
assertSetupProfile(queue, entry, extension);
const endpointFile = join(profile, "DevToolsActivePort");
let browser, child;
let portalRequests = 0;
async function launchOwned() {
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
  const diagnostics = openSync(
    join(root, ".local/operational-20261115/brave-process.private.log"),
    "a",
    0o600,
  );
  child = spawn(
    executable,
    [
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-background-networking",
      "--disable-component-update",
      "--disable-sync",
      "--enable-logging=stderr",
      "--remote-debugging-address=127.0.0.1",
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", diagnostics] },
  );
  closeSync(diagnostics);
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
  context.on("request", (request) => {
    try {
      const host = new URL(request.url()).hostname;
      if (host === "naukri.com" || host.endsWith(".naukri.com"))
        portalRequests++;
    } catch {
      /* non-network URL */
    }
  });
  await context.route(/^https?:\/\/([^/]+\.)?naukri\.com\//, (route) =>
    route.abort(),
  );
  context.setDefaultTimeout(30000);
  const inventory = await browser.newBrowserCDPSession();
  const { targetInfos } = await inventory.send("Target.getTargets");
  await inventory.detach();
  assertSetupTabs(
    targetInfos.filter((target) => target.type === "page"),
    id,
  );
  let worker = context
    .serviceWorkers()
    .find((w) => w.url() === `chrome-extension://${id}/background.js`);
  if (!worker) {
    // An MV3 registration can be dormant after a process restart. A verified
    // inactive extension document triggers its normal message listener.
    const ready = context.waitForEvent("serviceworker", {
      predicate: (w) => w.url() === `chrome-extension://${id}/background.js`,
      timeout: 30000,
    });
    ready.catch(() => {});
    const inspector = await browser.newBrowserCDPSession();
    const pageEvent = context.waitForEvent("page", { timeout: 5000 });
    pageEvent.catch(() => {});
    let target;
    try {
      target = (
        await inspector.send("Target.createTarget", {
          url: "about:blank",
          background: true,
        })
      ).targetId;
      const wake = await pageEvent;
      for (let attempt = 0; attempt < 10; attempt++) {
        await wake
          .goto(`chrome-extension://${id}/popup.html`, {
            waitUntil: "domcontentloaded",
            timeout: 1000,
          })
          .catch(() => {});
        const seen = await Promise.race([
          ready.then(() => true),
          new Promise((resolve) => setTimeout(() => resolve(false), 200)),
        ]);
        if (seen) break;
      }
      worker = await ready;
    } finally {
      if (target)
        await inspector
          .send("Target.closeTarget", { targetId: target })
          .catch(() => {});
      await inspector.detach().catch(() => {});
    }
  }
  return { context, worker };
}
async function stopOwned() {
  if (browser) await browser.close().catch(() => {});
  browser = undefined;
  if (child && child.exitCode === null && child.signalCode === null) {
    child.kill("SIGTERM");
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 5000);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
  assert(
    !child || child.exitCode !== null || child.signalCode !== null,
    "owned_browser_shutdown_unconfirmed",
  );
}
try {
  let { context, worker } = await launchOwned();
  // Verify the bytes actually served by this owned extension before connecting.
  // An unchanged stable ID alone cannot prove that a browser loaded this release.
  const verify = (target) =>
    target.evaluate(async (files) => {
      for (const file of files) {
        const response = await fetch(chrome.runtime.getURL(file.name), {
          cache: "no-store",
        });
        if (!response.ok) throw Error("brave_extension_bytes_unavailable");
        const digest = Array.from(
          new Uint8Array(
            await crypto.subtle.digest("SHA-256", await response.arrayBuffer()),
          ),
          (value) => value.toString(16).padStart(2, "0"),
        ).join("");
        if (digest !== file.sha256)
          throw Error("brave_extension_bytes_mismatch");
      }
      return files.length;
    }, release.files);
  const checked = await verify(worker);
  assert.equal(checked, release.files.length);
  await worker.evaluate(() => {
    const send = chrome.runtime.sendNativeMessage.bind(chrome.runtime);
    chrome.runtime.sendNativeMessage = (host, ...arguments_) => {
      if (host !== "com.automated_apply.brave")
        throw Error("brave_runtime_native_host_mismatch");
      return send(host, ...arguments_);
    };
  });
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
  assert.equal(portalRequests, 0, "unexpected_setup_portal_request");
  const result = {
    browser: "brave",
    version: browser.version(),
    native_health: "PASS",
    installed_files_verified: checked,
    connected: true,
    queue_commands_enabled: false,
    owned_active_tab_preserved: true,
    naukri_site_access: siteAccess,
    real_portal_requests: portalRequests,
    request_observation: "after_debug_attach",
    extension_version: manifest.version,
    profile_stopped_for_owner_login: true,
  };
  const target = resolve(
    root,
    ".local/operational-20261115/brave-setup.latest.private.json",
  );
  writeFileSync(target, JSON.stringify(result, null, 2) + "\n", {
    mode: 0o600,
  });
  console.log(JSON.stringify(result));
} finally {
  await stopOwned();
}
