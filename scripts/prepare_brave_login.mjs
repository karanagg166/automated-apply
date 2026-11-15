// Reuse one neutral window in the already-running owned profile. Never opens a window.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";
import {
  inactiveNaukriLoginPlan,
  stoppedQueue,
} from "./brave_setup_policy.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const evidence = join(root, ".local/operational-20261115");
const intent = join(evidence, "prepared-login-tab.private.json");
const extensionId = "gdjbmkffcpicbpiikcohlmokkmcpipgp";

async function main() {
  assert.equal(process.argv.length, 2, "login_setup_takes_no_arguments");
  assert(!existsSync(intent), "existing_login_intent_preserved");
  const release = JSON.parse(
    readFileSync(
      join(root, ".local/runtime-support/brave-extension-current.json"),
    ),
  );
  assert(
    release.extension_path.startsWith(
      join(root, ".local/runtime-support/brave-extension/"),
    ) && /^[a-f0-9]{40}$/.test(release.native_source_sha),
    "owned_brave_release_required",
  );
  for (const file of release.files) {
    assert(!/[\\/]/.test(file.name), "invalid_release_file");
    assert.equal(
      createHash("sha256")
        .update(readFileSync(join(release.extension_path, file.name)))
        .digest("hex"),
      file.sha256,
      "owned_release_bytes_changed",
    );
  }
  const configuration = join(
    root,
    ".local/runtime-support/rust-native",
    release.native_source_sha,
    "automated-apply-native.private.env",
  );
  const queue = await stoppedQueue(configuration);
  const [port] = readFileSync(
    join(root, ".local/browser-profiles/brave-automation/DevToolsActivePort"),
    "utf8",
  ).split("\n");
  assert(/^\d{4,5}$/.test(port), "owned_endpoint_invalid");
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {
    noDefaults: true,
    timeout: 5000,
  });
  const worker = browser
    .contexts()[0]
    ?.serviceWorkers()
    .find(
      (item) =>
        item.url() === `chrome-extension://${extensionId}/background.js`,
    );
  assert(worker, "owned_worker_required");
  const before = await worker.evaluate(async () => ({
    windows: await chrome.windows.getAll(),
    tabs: await chrome.tabs.query({}),
  }));
  const plan = inactiveNaukriLoginPlan(before.windows, before.tabs);
  writeFileSync(
    intent,
    JSON.stringify({
      state: "intent_recorded",
      window_id: plan.windowId,
      queue,
    }) + "\n",
    { mode: 0o600, flag: "wx" },
  );
  const result = await worker.evaluate(async (plan) => {
    const selected = (await chrome.tabs.query({ active: true })).map(
      ({ id, windowId }) => ({ id, windowId }),
    );
    const target = await chrome.tabs.get(
      selected.find((tab) => tab.windowId === plan.windowId)?.id,
    );
    if (
      target.url !== "about:blank" ||
      (target.pendingUrl && target.pendingUrl !== "about:blank")
    )
      throw Error("neutral_tab_changed");
    const tab = await chrome.tabs.create(plan);
    const after = (await chrome.tabs.query({ active: true })).map(
      ({ id, windowId }) => ({ id, windowId }),
    );
    return {
      state: "created",
      tab_id: tab.id,
      window_id: tab.windowId,
      tab_created_inactive: tab.active === false,
      selected_tabs_preserved:
        JSON.stringify(selected) === JSON.stringify(after),
      login_or_verification_form_submitted: false,
    };
  }, plan);
  writeFileSync(intent, JSON.stringify(result, null, 2) + "\n", {
    mode: 0o600,
  });
  assert(
    result.tab_created_inactive && result.selected_tabs_preserved,
    "login_tab_focus_check_failed",
  );
  await stoppedQueue(configuration);
  console.log(
    JSON.stringify({
      inactive_login_tab_created: true,
      selected_tabs_preserved: true,
      browser_or_window_launched: false,
      queue_stopped: true,
      login_or_verification_form_submitted: false,
    }),
  );
}
main().then(
  () => process.exit(0), // Disconnect CDP without closing the owner's browser.
  (error) => {
    const known = new Set([
      "owner_brave_window_required",
      "existing_naukri_tab_preserved",
      "unique_owned_neutral_window_required",
      "existing_login_intent_preserved",
      "owned_worker_required",
      "neutral_tab_changed",
      "login_tab_focus_check_failed",
    ]);
    console.error(
      JSON.stringify({
        status: "REFUSED_OR_UNCERTAIN",
        code: known.has(error.message)
          ? error.message
          : "brave_login_setup_failed",
        preserve_recorded_intent: existsSync(intent),
      }),
    );
    process.exit(1);
  },
);
