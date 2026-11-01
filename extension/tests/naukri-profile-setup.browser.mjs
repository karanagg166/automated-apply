// Real isolated Chromium + shipped maintenance code. Fictional page and native
// responses only; never attaches to the owner's Chrome or visits live Naukri.
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

const root = mkdtempSync(
  join(tmpdir(), "automated-apply-profile-setup-fixture-"),
);
for (const name of [
  "naukri-queue.js",
  "naukri-chatbot.js",
  "naukri-execution.js",
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
    name: "Fictional inactive profile setup",
    permissions: ["storage", "scripting"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `
import { NaukriQueue } from './naukri-queue.js';
globalThis.prepare=async(mode='normal')=>{
 const [owner]=await chrome.tabs.query({active:true});
 await chrome.storage.local.set({connectedChromeProfileV1:{id:'fictional',secret:'f'.repeat(64),connected:true,windowId:owner.windowId}});
 await chrome.storage.session.clear();
 await chrome.storage.session.set({applicationBrowserSessionV1:'fictional-session'});
 globalThis.owner=owner;globalThis.calls=[];globalThis.ackCount=0;
 globalThis.request={kind:'open_naukri_profile_setup',request_id:crypto.randomUUID(),expires_at:new Date(Date.now()+60000).toISOString(),url:'https://example.org/never-use-override'};
 if(mode==='expired')request.expires_at=new Date(Date.now()-1).toISOString();
 if(mode==='unknown')request.kind='arbitrary_url';
 globalThis.send=async(_,name,input)=>{
  calls.push({name,tab:input.tab_id,work:input.work_id,adopted:input.work_report?.reason==='owner_tab_active'});
  if(name!=='poll_naukri_work')throw Error('unexpected_job_operation');
  if(input.tab_id){if(mode==='lost_ack'&&++ackCount===1)throw Error('fictional_lost_ack');return {work:null,maintenance_recorded:true};}
  return {work:null,maintenance:request};
 };
 const create=chrome.tabs.create.bind(chrome.tabs);
 globalThis.api={...chrome,tabs:{...chrome.tabs,create:async(input)=>{calls.push({name:'create',input});const tab=await create(input);if(mode==='lost_create')throw Error('fictional_lost_create');return tab;},update:async()=>{throw Error('automation_must_not_navigate_or_activate');},remove:async()=>{throw Error('automation_must_not_close_setup_or_owner');}},scripting:{executeScript:async()=>{throw Error('setup_must_not_read_or_write_DOM');}}};
 globalThis.queue=new NaukriQueue(api,send,async()=>{});
 await queue.tick();
 return {ownerId:owner.id,ownerWindow:owner.windowId,calls,setup:(await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1,tabs:await chrome.tabs.query({})};
};
globalThis.tick=async()=>{await queue.tick();return {calls,setup:(await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1,tabs:await chrome.tabs.query({})};};
globalThis.adoptAndReconstruct=async()=>{
 const setup=(await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1;
 await chrome.tabs.update(setup.tab_id,{active:true});
 for(let i=0;i<50;i++){if((await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1.ownerAdopted)break;await new Promise(r=>setTimeout(r,20));}
 const adopted=(await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1.ownerAdopted;
 await chrome.tabs.update(owner.id,{active:true});request={...request,request_id:crypto.randomUUID()};queue=new NaukriQueue(api,send,async()=>{});await queue.tick();
 return {adopted,oldTab:await chrome.tabs.get(setup.tab_id),setup:(await chrome.storage.session.get('naukriProfileSetupTabV1')).naukriProfileSetupTabV1,calls,tabs:await chrome.tabs.query({})};
};`,
);
const started = performance.now();
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
const endpoint = join(profile, "DevToolsActivePort");
for (let i = 0; !existsSync(endpoint); i++) {
  if (i >= 150) throw Error("fixture_browser_start_deadline");
  await new Promise((resolve) => setTimeout(resolve, 100));
}
const [port] = readFileSync(endpoint, "utf8").trim().split("\n");
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {
  noDefaults: true,
});
const context = browser.contexts()[0];
let unexpectedRequests = 0,
  fixtureRequests = 0,
  chooserEvents = 0;
const evidence = [];
try {
  const fictionalOwner = context.pages()[0] || (await context.newPage());
  await fictionalOwner.goto("about:blank");
  await fictionalOwner.bringToFront(); // Isolated fictional owner; never real Chrome.
  await context.route("**/*", (route) => {
    if (new URL(route.request().url()).protocol === "chrome-extension:")
      return route.continue(); // Local fixture modules, never provider traffic.
    if (route.request().url() !== "https://www.naukri.com/mnjuser/profile") {
      unexpectedRequests++;
      return route.abort();
    }
    fixtureRequests++;
    return route.fulfill({
      contentType: "text/html",
      body: "<h1>Fictional profile</h1><button onclick='window.accidentalSaves=(window.accidentalSaves||0)+1'>Save</button>",
    });
  });
  context.on("page", (page) => page.on("filechooser", () => chooserEvents++));
  const worker =
    context
      .serviceWorkers()
      .find((item) => item.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (item) => item.url().endsWith("/fixture.js"),
    }));
  for (let attempt = 0; ; attempt++) {
    if (await worker.evaluate(() => typeof globalThis.prepare === "function"))
      break;
    if (attempt >= 50) throw Error("fixture_worker_start_deadline");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const original = await worker.evaluate(() =>
    chrome.tabs.query({ active: true }),
  );
  const first = await worker.evaluate(() => prepare());
  assert.equal(first.setup.ownerAdopted, false);
  assert.equal(first.calls.filter((c) => c.name === "create").length, 1);
  assert.equal(
    first.calls.find((c) => c.name === "create").input.active,
    false,
  );
  assert.equal(first.setup.window_id, first.ownerWindow);
  assert.equal(first.calls.find((c) => c.tab)?.work, first.setup.request_id);
  // This protocol only creates/acknowledges an inactive tab. Its initial
  // navigation can precede Playwright page interception; DNS stays blocked.
  // A URL/ACK is not profile-load, account or Save evidence. Live inspection
  // must separately verify the loaded DOM and bound identity before use.
  const second = await worker.evaluate(() => tick());
  assert.equal(second.calls.filter((c) => c.name === "create").length, 1);
  assert.equal(second.setup.tab_id, first.setup.tab_id);
  evidence.push("one_inactive_fixed_URL_and_idempotent_ACK");
  const adopted = await worker.evaluate(() => adoptAndReconstruct());
  assert.equal(adopted.adopted, true);
  assert.equal(adopted.oldTab.url, "https://www.naukri.com/mnjuser/profile");
  assert.notEqual(adopted.setup.tab_id, adopted.oldTab.id);
  assert.equal(adopted.oldTab.active, false);
  evidence.push("adopted_tab_preserved_across_worker_reconstruction");
  for (const mode of ["lost_create", "lost_ack", "expired", "unknown"]) {
    const before = await worker.evaluate((m) => prepare(m), mode);
    const after = await worker.evaluate(() => tick());
    assert.equal(
      after.calls.filter((c) => c.name === "create").length,
      ["expired", "unknown"].includes(mode) ? 0 : 1,
    );
    if (mode === "lost_create") assert.equal(after.setup.status, "creating");
    if (mode === "lost_ack")
      assert.equal(after.setup.tab_id, before.setup.tab_id);
    evidence.push(mode);
  }
  const active = await worker.evaluate(() =>
    chrome.tabs.query({ active: true }),
  );
  assert.deepEqual(
    active.map((t) => [t.windowId, t.id]),
    original.map((t) => [t.windowId, t.id]),
  );
  assert.equal(unexpectedRequests, 0);
  assert.equal(chooserEvents, 0);
  const report = {
    fixture_only: true,
    profile_document_load_tested: false,
    live_naukri_requests: 0,
    dns_route_to_provider_blocked: true,
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - started),
    fixtureRequests,
    unexpectedRequests,
    chooserEvents,
    owner_selection_unchanged: true,
    evidence,
  };
  const args = process.argv.slice(2);
  if (args.length === 2 && args[0] === "--report")
    writeFileSync(args[1], JSON.stringify(report, null, 2) + "\n");
  else if (args.length)
    throw Error(
      "usage: node tests/naukri-profile-setup.browser.mjs [--report FILE]",
    );
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
  child.kill();
  // Preserve isolated artifacts; never cleans a workspace/release/profile.
}
