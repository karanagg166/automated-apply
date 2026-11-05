// One isolated real-Chrome alarm/reload/stop journey; native messaging is absent.
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
const root = mkdtempSync(join(tmpdir(), "automated-apply-retained-alarm-"));
for (const name of [
  "naukri-retained.js",
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
    name: "Fictional retained alarm acceptance",
    permissions: ["storage", "alarms"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(join(root, "fixture.js"), "globalThis.fixtureReady=true;");
writeFileSync(
  join(root, "settings.html"),
  '<!doctype html><script type="module" src="fixture-page.js"></script><p>Fictional inactive controller</p>',
);
writeFileSync(
  join(root, "fixture-page.js"),
  `import {retainedAlarmController,configureRetainedHeartbeat} from './naukri-retained.js';const id='11111111-1111-4111-8111-111111111111';globalThis.controller=retainedAlarmController(chrome,async()=>({ok:true,connected:true}),s=>globalThis.lastStatus=s,async(api,a,b,work,reads)=>{if(work!==id||reads!==true)throw Error('fictional_scope_changed');const count=(await api.storage.session.get('fixtureRunTotal')).fixtureRunTotal||0;await api.storage.session.set({fixtureRunTotal:count+1});});window.addEventListener('pagehide',()=>{controller.dispose();void configureRetainedHeartbeat(chrome,null);});if(!await controller.resume())await controller.start(id,true);globalThis.fixturePageReady=true;`,
);
const profile = join(root, "profile");
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
    "--host-resolver-rules=MAP www.naukri.com ~NOTFOUND",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    `--disable-extensions-except=${root}`,
    `--load-extension=${root}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);
let browser,
  unexpected = 0,
  chooser = 0;
const started = performance.now();
try {
  const endpoint = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(endpoint); i++) {
    if (i === 100 || child.exitCode !== null)
      throw Error("isolated_start_timeout");
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.connectOverCDP(
    `http://127.0.0.1:${readFileSync(endpoint, "utf8").split("\n")[0]}`,
    { noDefaults: true },
  );
  const context = browser.contexts()[0];
  let extensionPrefix = "";
  await context.route("**/*", (route) => {
    if (extensionPrefix && route.request().url().startsWith(extensionPrefix))
      return route.continue();
    if (
      route
        .request()
        .url()
        .startsWith("https://www.naukri.com/job-listings-fictional-")
    )
      return route.fulfill({
        contentType: "text/html",
        body: "<p>Unchanged fictional form</p>",
      });
    unexpected++;
    return route.abort();
  });
  context.on("page", (p) => {
    p.on("filechooser", () => chooser++);
    p.on("pageerror", (e) => console.error("fixture_page_error", e.message));
  });
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", (w) =>
      w.url().endsWith("/fixture.js"),
    ));
  extensionPrefix = worker.url().slice(0, worker.url().lastIndexOf("/") + 1);
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.fixtureReady || !chrome.storage?.local; i++) {
      if (i === 100) throw Error("fixture_api_not_ready");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const ids = await worker.evaluate(async () => {
    const windowId = (await chrome.windows.getCurrent()).id;
    const form = await chrome.tabs.create({
      url: "https://www.naukri.com/job-listings-fictional-123456789012",
      active: false,
      windowId,
    });
    for (let i = 0; i < 100; i++) {
      const current = await chrome.tabs.get(form.id);
      if (
        current.status === "complete" &&
        current.url ===
          "https://www.naukri.com/job-listings-fictional-123456789012"
      )
        break;
      if (i === 99) throw Error("fictional_form_not_ready");
      await new Promise((r) => setTimeout(r, 50));
    }
    await chrome.storage.local.set({
      connectedChromeProfileV1: {
        id: "profile",
        secret: "fictional",
        connected: true,
        windowId,
      },
    });
    await chrome.storage.session.set({
      applicationBrowserSessionV1: "session",
      naukriParkedQuestionnairesV1: {
        "11111111-1111-4111-8111-111111111111": {
          id: "11111111-1111-4111-8111-111111111111",
          form_pending: true,
          ownedTabId: form.id,
          url: "https://www.naukri.com/job-listings-fictional-123456789012",
          binding: {
            profile_binding_id: "profile",
            browser_session_id: "session",
            window_id: windowId,
          },
        },
      },
    });
    const settings = await chrome.tabs.create({
      url: chrome.runtime.getURL("settings.html"),
      active: false,
      windowId,
    });
    return {
      form: form.id,
      settings: settings.id,
      url: chrome.runtime.getURL("settings.html"),
    };
  });
  let page;
  for (let i = 0; !page; i++) {
    page = context.pages().find((p) => p.url() === ids.url);
    if (i === 100) throw Error("settings_unavailable");
    if (!page) await new Promise((r) => setTimeout(r, 50));
  }
  await page.waitForFunction(() => globalThis.fixturePageReady, null, {
    timeout: 10000,
  });
  await page.waitForFunction(
    async () =>
      ((await chrome.storage.session.get("fixtureRunTotal")).fixtureRunTotal ||
        0) >= 2,
    null,
    { timeout: 45000 },
  );
  const before = await page.evaluate(async () => ({
    count: (await chrome.storage.session.get("fixtureRunTotal"))
      .fixtureRunTotal,
    active: (await chrome.tabs.getCurrent()).active,
    form: (
      await chrome.tabs.query({
        url: "https://www.naukri.com/job-listings-fictional-*",
      })
    ).length,
  }));
  assert.equal(before.active, false);
  assert.equal(before.form, 1);
  await page.reload();
  await page.waitForFunction(() => globalThis.fixturePageReady, null, {
    timeout: 10000,
  });
  const after = await page.evaluate(async () => ({
    count: (await chrome.storage.session.get("fixtureRunTotal"))
      .fixtureRunTotal,
    form: (
      await chrome.tabs.query({
        url: "https://www.naukri.com/job-listings-fictional-*",
      })
    ).length,
  }));
  assert.ok(after.count > before.count);
  assert.equal(after.form, 1);
  const stopped = await page.evaluate(async () => {
    await controller.stop();
    return {
      normal: !!(await chrome.alarms.get("connected-chrome-heartbeat")),
      automatic: !!(await chrome.alarms.get(
        "naukri-retained-form-continuation",
      )),
    };
  });
  assert.deepEqual(stopped, { normal: true, automatic: false });
  assert.equal(unexpected, 0);
  assert.equal(chooser, 0);
  const report = {
    fixture_only: true,
    journeys: 1,
    checks: ["hidden_alarm", "same_tab_reload", "stop_restores_heartbeat"],
    duration_ms: Math.round(performance.now() - started),
    live_naukri_requests: 0,
    unexpected_requests: unexpected,
    chooser_events: chooser,
  };
  if (process.argv[2] === "--report")
    writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close();
  child.kill();
}
