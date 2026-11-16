import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Isolated Chromium only. Provider HTML and account are fictional; no native host.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
const root = mkdtempSync(join(tmpdir(), "automated-apply-history-cards-")),
  profile = join(root, "profile"),
  url = "https://www.naukri.com/myapply/historypage",
  req = "291026123456";
cpSync(
  new URL("../naukri-execution.js", import.meta.url),
  join(root, "naukri-execution.js"),
);
writeFileSync(
  join(root, "manifest.json"),
  JSON.stringify({
    manifest_version: 3,
    version: "0.0.1",
    name: "Fictional history-card acceptance",
    permissions: ["scripting"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `import {executeNaukri} from './naukri-execution.js';globalThis.fixtureReady=true;globalThis.create=async()=>{const t=await chrome.tabs.create({url:'about:blank',active:false});await chrome.tabs.update(t.id,{url:${JSON.stringify(url)},active:false});for(let i=0;i<100;i++){if((await chrome.tabs.get(t.id)).status==='complete')return t.id;await new Promise(r=>setTimeout(r,50));}throw Error('fixture_not_loaded')};globalThis.run=async(id,work)=>(await chrome.scripting.executeScript({target:{tabId:id,frameIds:[0]},world:'ISOLATED',func:executeNaukri,args:[work]}))[0].result;`,
);
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
let browser,
  unexpected = 0,
  chooser = 0,
  mode = "valid";
const evidence = [],
  start = performance.now();
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
  await context.route("**/*", (route) => {
    const u = new URL(route.request().url());
    if (u.protocol === "chrome-extension:") return route.continue();
    if (u.origin !== "https://www.naukri.com") {
      unexpected++;
      return route.abort();
    }
    const email =
      mode === "account"
        ? "different@fictional.example"
        : "verified@fictional.example";
    const card = `<div class="ot__jdTupleContainer jdTupleContainer select"><div class="jdTitle">Backend Developer</div><div class="subheading"><span class="company">Fictional Employer</span></div><section class="apply-status green-text"><span class="title">Application sent 5 days ago</span></section><div class="mock-interview-prep"><a href="/mock-interview-questions/test?flowType=JD&flowId=${mode === "conflict" ? "291026999999" : req}">Mock</a><a href="/ai-interview-questions/question-bank?jobId=${req}">Q&A</a></div></div>`;
    return route.fulfill({
      contentType: "text/html",
      body: `<header><span class="email">${email}</span></header><div class="jdTuplesContainer">${card}${mode === "duplicate" ? card : ""}</div><script>window.clicks=0;document.addEventListener('click',()=>window.clicks++);window.opens=0;window.open=()=>{window.opens++;};</script>`,
    });
  });
  context.on("page", (p) => p.on("filechooser", () => chooser++));
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", (w) =>
      w.url().endsWith("/fixture.js"),
    ));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.fixtureReady; i++) {
      if (i === 100) throw Error("fixture_not_ready");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const work = {
    id: "fictional-work",
    url,
    operation: "reconcile_application",
    requisition: req,
    execution: {
      expected_account_sha256: createHash("sha256")
        .update("verified@fictional.example")
        .digest("hex"),
      expected_title: "Backend Developer",
      expected_company: "Fictional Employer",
    },
  };
  let first;
  for (const name of [
    "valid",
    "independent",
    "conflict",
    "duplicate",
    "account",
  ]) {
    mode = name;
    const tab = await worker.evaluate(() => globalThis.create());
    const v = await worker.evaluate(
      ({ tab, work }) => globalThis.run(tab, work),
      { tab, work },
    );
    const counts = await worker.evaluate(
      async (tab) =>
        (
          await chrome.scripting.executeScript({
            target: { tabId: tab },
            world: "MAIN",
            func: () => ({ clicks: window.clicks, opens: window.opens }),
          })
        )[0].result,
      tab,
    );
    assert.deepEqual(counts, { clicks: 0, opens: 0 });
    if (name === "valid" || name === "independent") {
      assert.equal(v.execution?.state, "APPLICATION_SENT");
      if (first) assert.notEqual(v.execution.document_id, first);
      first = v.execution.document_id;
    } else assert.equal(v.kind, "needs_input");
    evidence.push({
      name,
      result: "PASS",
      provider_clicks: counts.clicks,
      new_window_requests: counts.opens,
    });
    await worker.evaluate((tab) => chrome.tabs.remove(tab), tab);
  }
  assert.equal(unexpected, 0);
  assert.equal(chooser, 0);
  const report = {
    fixture_only: true,
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - start),
    live_naukri_requests: 0,
    unexpected_requests: unexpected,
    chooser_events: chooser,
    evidence,
  };
  if (process.argv[2] === "--report")
    writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close();
  child.kill();
}
