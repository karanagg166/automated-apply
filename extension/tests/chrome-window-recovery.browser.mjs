// Real isolated Chromium window APIs; fictional native policy, no provider pages.
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

const started = performance.now();
const root = mkdtempSync(join(tmpdir(), "apply-window-recovery-"));
cpSync(
  new URL("../chrome-profile.js", import.meta.url),
  join(root, "chrome-profile.js"),
);
writeFileSync(
  join(root, "manifest.json"),
  JSON.stringify({
    manifest_version: 3,
    version: "0.0.1",
    name: "Isolated recovery fixture",
    permissions: ["storage", "background"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `
import {ChromeProfileConnection} from './chrome-profile.js';
globalThis.recover = async (allowed) => {
 const before = await chrome.windows.getLastFocused({populate:true});
 const owner = before.tabs.find(t=>t.active);
 const value={id:'fixture',secret:'f'.repeat(64),connected:true,commandsEnabled:true,windowId:null};
 await chrome.storage.local.set({connectedChromeProfileV1:value});
 await chrome.storage.session.set({applicationBrowserSessionV1:'fixture-session'});
 let created=null; const requests=[];
 const api={...chrome,windows:{...chrome.windows,
   get:async(id)=>{if(created?.id===id)return chrome.windows.get(id);throw Error('closed fixture binding');},
   getLastFocused:async()=>{throw Error('fixture windowless profile');},
   create:async(input)=>{created=await chrome.windows.create(input);return created;}
 },runtime:{...chrome.runtime,sendNativeMessage:async(_,input)=>{
   requests.push(input.command);
   return {version:1,request_id:input.request_id,ok:true,data:{submitted:false,background_window_allowed:allowed,profile:{id:value.id,connected:true,selected:true,commands_enabled:true,status:input.window_id===null?'PROFILE_OFFLINE':'CONNECTED'}}};
 }}};
 const connection=Object.assign(Object.create(ChromeProfileConnection.prototype),{api,value,ready:Promise.resolve()});
 const profile=await connection.heartbeat();
 const after=await chrome.windows.getLastFocused({populate:true});
 const createdSnapshot=created ? await chrome.windows.get(created.id,{populate:true}) : null;
 const result={beforeWindow:before.id,afterWindow:after.id,beforeTab:owner.id,afterTab:after.tabs.find(t=>t.active)?.id,created:createdSnapshot,profileStatus:profile.status,requests};
 if(created)await chrome.windows.remove(created.id);
 return result;
};`,
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
  if (i > 100 || child.exitCode !== null) {
    child.kill();
    throw Error("isolated_browser_start_timeout");
  }
  await new Promise((r) => setTimeout(r, 100));
}
const browser = await chromium.connectOverCDP(
  `http://127.0.0.1:${readFileSync(endpoint, "utf8").split("\n")[0]}`,
  { noDefaults: true },
);
let externalRequests = 0;
try {
  const context = browser.contexts()[0];
  await context.route(/^https?:\/\//, (route) => {
    externalRequests++;
    return route.abort();
  });
  const worker =
    context
      .serviceWorkers()
      .find((worker) => worker.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (worker) => worker.url().endsWith("/fixture.js"),
    }));
  for (let i = 0; ; i++) {
    if (await worker.evaluate(() => typeof globalThis.recover === "function"))
      break;
    if (i >= 50) throw Error("fixture_worker_module_not_ready");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  for (const allowed of [false, true]) {
    const result = await worker.evaluate(
      (allowed) => globalThis.recover(allowed),
      allowed,
    );
    assert.equal(result.beforeWindow, result.afterWindow);
    assert.equal(result.beforeTab, result.afterTab);
    if (allowed) {
      assert.equal(result.created.focused, false);
      assert.equal(result.created.tabs.length, 1);
      assert.equal(result.profileStatus, "CONNECTED");
      assert.equal(result.requests.length, 2);
    } else {
      assert.equal(result.created, null);
      assert.equal(result.profileStatus, "PROFILE_OFFLINE");
      assert.equal(result.requests.length, 1);
    }
    assert.ok(result.requests.every((c) => c === "heartbeat_chrome_profile"));
  }
  assert.equal(externalRequests, 0);
  console.log(
    JSON.stringify({
      cases: 2,
      passed: 2,
      externalRequests,
      providerRequests: 0,
      focusPreserved: true,
      seconds: Math.round((performance.now() - started) / 10) / 100,
    }),
  );
} finally {
  await browser.close();
  child.kill();
}
