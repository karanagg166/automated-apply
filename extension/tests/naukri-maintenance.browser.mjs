// Actual isolated extension reload; fictional native status, no owner Chrome.
import assert from "node:assert/strict";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";

const root = mkdtempSync(join(tmpdir(), "aa-reload-fixture-"));
for (const file of ["naukri-maintenance.js", "chrome-profile.js"])
  cpSync(new URL("../" + file, import.meta.url), join(root, file));
writeFileSync(
  join(root, "manifest.json"),
  JSON.stringify({
    manifest_version: 3,
    version: "0.0.1",
    name: "Fictional guarded reload",
    key: JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url)))
      .key,
    permissions: ["storage", "tabs"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "settings.html"),
  '<script type="module" src="settings.js"></script>',
);
writeFileSync(
  join(root, "settings.js"),
  `
import {guardedNaukriReload} from './naukri-maintenance.js';
void chrome.runtime.sendMessage({fixtureWake:true}).catch(()=>{});
window.beginReload=()=>guardedNaukriReload({requestId:'11111111-1111-4111-8111-111111111111',targetSha:'a'.repeat(40),profileBindingId:'fixture-profile',expectedRevision:157,expiresAt:new Date(Date.now()+60000).toISOString()}, {...chrome,runtime:{...chrome.runtime,sendNativeMessage:async(_,input)=>({version:1,request_id:input.request_id,ok:true,data:{submitted:false,queue:{state:'STOPPED',revision:157}}}),reload:()=>chrome.runtime.reload()}}).catch(error=>{window.reloadError=error.message;});
`,
);
writeFileSync(
  join(root, "fixture.js"),
  `
chrome.runtime.onInstalled.addListener(()=>{});
chrome.runtime.onMessage.addListener((_message,_sender,reply)=>{reply({fixtureReady:true});});
globalThis.ready=(async()=>{await chrome.storage.session.set({applicationBrowserSessionV1:'fixture-session'});})();
globalThis.snapshot=async()=>({windows:(await chrome.windows.getAll({windowTypes:['normal']})).map(w=>({id:w.id,focused:w.focused})).sort((a,b)=>a.id-b.id),tabs:(await chrome.tabs.query({})).map(t=>({id:t.id,windowId:t.windowId,url:t.url,active:t.active})).sort((a,b)=>a.id-b.id)});
globalThis.prepare=async()=>{await ready;const second=await chrome.windows.create({url:'about:blank',focused:false});await chrome.storage.local.set({connectedChromeProfileV1:{connected:true,id:'fixture-profile',secret:'fictional-only',windowId:second.id}});const setup=await chrome.tabs.create({url:chrome.runtime.getURL('settings.html'),windowId:second.id,active:false});return {setupId:setup.id,url:setup.url,before:await snapshot()};};
`,
);
// Ordinary developer mode is required for unpacked-extension reloads. Configure
// only this new fictional browser profile, never an installed owner profile.
mkdirSync(join(root, "profile", "Default"), { recursive: true });
writeFileSync(
  join(root, "profile", "Default", "Preferences"),
  JSON.stringify({ extensions: { ui: { developer_mode: false } } }),
);
const child = spawn(
  chromium.executablePath(),
  [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--enable-unsafe-extension-debugging",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--remote-debugging-port=0",
    `--user-data-dir=${join(root, "profile")}`,
    `--disable-extensions-except=${root}`,
    `--load-extension=${root}`,
    "about:blank",
  ],
  { stdio: ["ignore", "pipe", "pipe"] },
);
let browser;
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(Error("fixture_start_timeout")),
      20000,
    );
    child.stderr.on("data", (chunk) => {
      const match = chunk
        .toString()
        .match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
  });
  browser = await chromium.connectOverCDP(endpoint, { noDefaults: true });
  const context = browser.contexts()[0];
  let externalRequests = 0;
  await context.route(/^https?:/, (route) => {
    externalRequests++;
    return route.abort();
  });
  const fixtureManager = await context.newPage();
  await fixtureManager.goto("chrome://extensions/");
  await fixtureManager.waitForFunction(
    () =>
      !!document
        .querySelector("extensions-manager")
        ?.shadowRoot?.querySelector("extensions-toolbar")
        ?.shadowRoot?.querySelector("#devMode"),
  );
  await fixtureManager.evaluate(() => {
    const toggle = document
      .querySelector("extensions-manager")
      .shadowRoot.querySelector("extensions-toolbar")
      .shadowRoot.querySelector("#devMode");
    if (toggle.disabled) throw Error("fixture_developer_mode_unavailable");
    if (!toggle.checked) toggle.click();
  });
  await fixtureManager.close();
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (w) => w.url().endsWith("/fixture.js"),
    }));
  await worker.evaluate(async () => {
    await globalThis.ready;
  });
  const before = await worker.evaluate(() => globalThis.prepare());
  let settings;
  for (let i = 0; i < 100; i++) {
    settings = context.pages().find((p) => p.url().endsWith("/settings.html"));
    if (
      settings &&
      (await settings.evaluate(() => !!window.beginReload).catch(() => false))
    )
      break;
    await new Promise((r) => setTimeout(r, 25));
  }
  assert.ok(settings);
  // Establish the fictional owner's selection after CDP attaches the new page.
  // This fixture setup never targets the owner's real Chrome profiles.
  await worker.evaluate(async (setupId) => {
    const setup = await chrome.tabs.get(setupId);
    const owner = (await chrome.tabs.query({ windowId: setup.windowId })).find(
      (tab) => tab.id !== setupId,
    );
    await chrome.tabs.update(owner.id, { active: true });
  }, before.setupId);
  before.before = await worker.evaluate(() => globalThis.snapshot());
  assert.equal(
    await settings.evaluate(() => document.visibilityState),
    "hidden",
  );
  const manifest = JSON.parse(readFileSync(join(root, "manifest.json")));
  writeFileSync(
    join(root, "manifest.json"),
    JSON.stringify({ ...manifest, version: "0.0.2" }),
  );
  await settings
    .evaluate(async () => {
      await window.beginReload();
      return "requested_once";
    })
    .catch((error) => {
      if (!/context.*destroyed|target.*closed/i.test(error.message))
        throw error;
    });
  const guardError = await settings
    .evaluate(() => window.reloadError)
    .catch(() => null);
  assert.ok(!guardError, guardError);
  // Reloading an unpacked MV3 extension may leave its new worker asleep.
  // Readiness comes from a fresh inactive extension document, not a timeout.
  if (!settings.isClosed())
    await settings.reload({ waitUntil: "domcontentloaded" });
  else {
    // runtime.reload closes extension pages. Wake the new fixture worker from
    // a replacement inactive setup target; this is outside the tested helper.
    const protocol = await browser.newBrowserCDPSession();
    await protocol.send("Target.createTarget", {
      url: worker.url().replace("fixture.js", "settings.html"),
      background: true,
    });
    await protocol.detach();
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  // noDefaults deliberately leaves CDP attachment behavior untouched. Reconnect
  // to enumerate the new worker rather than assuming Playwright emits an event.
  const refreshed = await chromium.connectOverCDP(endpoint, {
    noDefaults: true,
  });
  const reloadedContext = refreshed.contexts()[0];
  const reloaded =
    reloadedContext
      .serviceWorkers()
      .find((w) => w.url().endsWith("/fixture.js")) ||
    (await reloadedContext.waitForEvent("serviceworker", {
      predicate: (w) => w.url().endsWith("/fixture.js"),
    }));
  const after = await reloaded.evaluate(async () => {
    await globalThis.ready;
    return {
      snapshot: await globalThis.snapshot(),
      manifestVersion: chrome.runtime.getManifest().version,
      intent: (await chrome.storage.local.get("naukriMaintenanceReloadV1"))
        .naukriMaintenanceReloadV1,
    };
  });
  assert.equal(after.manifestVersion, "0.0.2");
  assert.deepEqual(after.snapshot.windows, before.before.windows);
  assert.deepEqual(
    after.snapshot.tabs.filter((t) => !t.url.endsWith("/settings.html")),
    before.before.tabs.filter((t) => !t.url.endsWith("/settings.html")),
  );
  assert.equal(after.intent.expectedRevision, 157);
  assert.ok(after.intent.consumedAt);
  assert.equal(externalRequests, 0);
  const result = {
    fixture_only: true,
    actual_runtime_reload: true,
    journeys: 1,
    checks: [
      "two_window_focus_preserved",
      "owner_tabs_preserved",
      "inactive_setup_only",
      "intent_consumed_before_reload",
    ],
    external_requests: externalRequests,
  };
  const flag = process.argv.indexOf("--report");
  if (flag >= 0)
    writeFileSync(process.argv[flag + 1], JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  if (browser) {
    const protocol = await browser.newBrowserCDPSession();
    console.error(
      JSON.stringify({
        fixture_targets: (
          await protocol.send("Target.getTargets")
        ).targetInfos.map((t) => ({ type: t.type, url: t.url })),
      }),
    );
    await protocol.detach();
    const debugContext = browser.contexts()[0];
    for (const page of debugContext
      .pages()
      .filter((p) => p.url().endsWith("/settings.html"))) {
      console.error(
        JSON.stringify({
          fixture_page: await page
            .evaluate(() => ({
              title: document.title,
              body: document.body?.innerText?.slice(0, 500),
              runtime: typeof chrome?.runtime,
              version: chrome?.runtime?.getManifest?.().version,
              reloadError: window.reloadError,
            }))
            .catch((e) => ({ error: e.message })),
        }),
      );
    }
    const manager = await debugContext.newPage();
    await manager.goto("chrome://extensions/");
    console.error(
      JSON.stringify({
        fixture_extension: await manager.evaluate(() => {
          const list = document
            .querySelector("extensions-manager")
            ?.shadowRoot?.querySelector("extensions-item-list");
          return [
            ...(list?.shadowRoot?.querySelectorAll("extensions-item") || []),
          ].map((x) => ({
            id: x.id,
            state: x.data?.state,
            version: x.data?.version,
            disableReasons: x.data?.disableReasons,
            runtimeErrors: x.data?.runtimeErrors,
          }));
        }),
      }),
    );
  }
  throw error;
} finally {
  if (browser) await browser.close();
  child.kill("SIGTERM");
}
