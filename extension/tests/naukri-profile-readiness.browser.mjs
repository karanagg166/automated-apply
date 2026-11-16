import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Focused isolated Chromium profile-readiness checks. Every provider response is a
// fictional fixture; no owner browser, live vacancy, keyboard or chooser.
import assert from "node:assert/strict";
import {
  cpSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const root = mkdtempSync(join(tmpdir(), "automated-apply-profile-readiness-"));
for (const name of [
  "naukri-queue.js",
  "naukri-chatbot.js",
  "naukri-execution.js",
  "naukri-profile-skills.js",
  "naukri-resume-download.js",
  "naukri-observation.js",
  "chrome-profile.js",
])
  cpSync(new URL("../" + name, import.meta.url), join(root, name));
writeFileSync(
  join(root, "manifest.json"),
  JSON.stringify({
    manifest_version: 3,
    version: "0.0.1",
    name: "Fictional profile readiness acceptance",
    permissions: ["scripting", "storage"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `import {NaukriQueue} from './naukri-queue.js';globalThis.readProfile=async(tabId,expected,adopt)=>{let count=0;const api={...chrome,scripting:{...chrome.scripting,executeScript:async args=>{count++;if(adopt&&count===2)await chrome.tabs.update(tabId,{active:true});return chrome.scripting.executeScript(args);}}};const q=new NaukriQueue(api,async()=>{throw Error('fixture_native_forbidden')});q.ownedTabId=tabId;let result;try{result=await q.observeProfileReady({id:'fixture',ownedTabId:tabId,operation:'verify_account',target_url:'https://www.naukri.com/mnjuser/profile',execution:{expected_account_sha256:expected}},{window_id:(await chrome.tabs.get(tabId)).windowId})}catch(e){result={kind:'needs_input',reason:e.message}}return {result,count};};`,
);
const started = performance.now();
const profile = join(root, "profile");
const child = spawn(
  fixtureExecutable(chromium),
  [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--enable-unsafe-extension-debugging",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--host-resolver-rules=MAP www.naukri.com ~NOTFOUND",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    `--disable-extensions-except=${root}`,
    `--load-extension=${root}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);

let browser;
let unexpected = 0,
  choosers = 0;
const evidence = [];
try {
  const endpoint = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(endpoint); i++) {
    if (i >= 100 || child.exitCode !== null)
      throw Error("isolated_start_timeout");
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.connectOverCDP(
    `http://127.0.0.1:${readFileSync(endpoint, "utf8").split("\n")[0]}`,
    { noDefaults: true },
  );
  const context = browser.contexts()[0];
  let mode = "";
  const { createHash } = await import("node:crypto");
  const expected = createHash("sha256")
    .update("verified@fictional.example")
    .digest("hex");
  await context.route("**/*", (route) => {
    if (new URL(route.request().url()).origin !== "https://www.naukri.com") {
      unexpected++;
      return route.abort();
    }
    const value =
      mode === "wrong"
        ? "different@fictional.example"
        : "verified@fictional.example";
    const email = `<div class="detail-list"><div class="with-cta"><span class="txt" name="Email">${value}</span></div></div>`;
    let body =
      '<button onclick="window.saves++">Save</button><script>window.saves=0;</script>';
    if (mode === "wrong" || mode === "ambiguous") body += email;
    if (mode === "ambiguous")
      body +=
        '<div class="detail-list"><div class="with-cta"><span class="txt" name="Email">another@fictional.example</span></div></div>';
    if (mode === "delayed")
      body += `<script>setTimeout(()=>document.body.insertAdjacentHTML('beforeend',${JSON.stringify(email)}),2700)</script>`;
    if (mode === "challenge") body += "<p>Access denied</p>";
    return route.fulfill({ contentType: "text/html", body });
  });
  context.on("page", (p) => p.on("filechooser", () => choosers++));
  const owner = context.pages()[0];
  await owner.bringToFront();
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker"));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.readProfile; i++) {
      if (i === 100) throw Error("fixture_start_timeout");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const ownerId = await worker.evaluate(
    async () => (await chrome.tabs.query({ active: true }))[0].id,
  );
  for (mode of [
    "delayed",
    "wrong",
    "ambiguous",
    "absent",
    "challenge",
    "adopt",
  ]) {
    const tab = await worker.evaluate(async () => {
      const t = await chrome.tabs.create({ url: "about:blank", active: false });
      await new Promise((r) => setTimeout(r, 200));
      await chrome.tabs.update(t.id, {
        url: "https://www.naukri.com/mnjuser/profile",
        active: false,
      });
      await new Promise((r) => setTimeout(r, 100));
      for (let i = 0; i < 100; i++) {
        if ((await chrome.tabs.get(t.id)).status === "complete") return t;
        await new Promise((r) => setTimeout(r, 50));
      }
      throw Error("fixture_document_timeout");
    });
    try {
      const t = performance.now();
      const r = await worker.evaluate(
        ({ id, expected, adopt }) => readProfile(id, expected, adopt),
        { id: tab.id, expected, adopt: mode === "adopt" },
      );
      const elapsed = Math.round(performance.now() - t);
      if (mode === "delayed") {
        assert.equal(
          r.result.execution?.state,
          "PROFILE_OBSERVED",
          JSON.stringify(r),
        );
        assert.ok(r.count > 1);
        assert.ok(elapsed >= 2000);
      } else {
        const reason =
          mode === "wrong" || mode === "ambiguous"
            ? "provider_account_identity_unverified"
            : mode === "challenge"
              ? "provider_challenge_requires_owner"
              : mode === "adopt"
                ? "owner_tab_active"
                : "profile_identity_hydrating";
        assert.equal(r.result.reason, reason);
        if (["wrong", "ambiguous", "challenge"].includes(mode))
          assert.equal(r.count, 1);
        if (mode === "absent") {
          assert.ok(r.count <= 40);
          assert.ok(elapsed < 13000);
        }
      }
      const saves = await worker.evaluate(
        async (id) =>
          (
            await chrome.scripting.executeScript({
              target: { tabId: id },
              world: "MAIN",
              func: () => window.saves,
            })
          )[0].result,
        tab.id,
      );
      assert.equal(saves, 0);
      evidence.push({
        name: mode,
        result: "PASS",
        read_injections: r.count,
        duration_ms: elapsed,
        save_clicks: saves,
      });
    } finally {
      await worker.evaluate((id) => chrome.tabs.remove(id), tab.id);
      await worker.evaluate(
        (id) => chrome.tabs.update(id, { active: true }),
        ownerId,
      );
    }
    assert.equal(owner.url(), "about:blank");
  }
  assert.equal(unexpected, 0);
  assert.equal(choosers, 0);
  const report = {
    fixture_only: true,
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - started),
    live_naukri_requests: 0,
    unexpected_requests: unexpected,
    chooser_events: choosers,
    evidence,
  };
  if (process.argv[2] === "--report")
    writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close();
  child.kill();
}
