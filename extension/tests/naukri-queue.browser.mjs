// Real isolated Chromium tabs + shipped queue/DOM code; fictional provider pages
// and native responses only. Never opens the owner's Chrome or a live vacancy.
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

const root = mkdtempSync(join(tmpdir(), "automated-apply-background-fixture-"));
for (const name of [
  "naukri-queue.js",
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
    name: "Fictional background queue acceptance",
    permissions: ["storage", "scripting"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `
import { NaukriQueue } from './naukri-queue.js';
globalThis.calls = [];
globalThis.prepare = async (operation, url, stop=false) => {
  const [owner] = await chrome.tabs.query({active:true});
  await chrome.storage.local.set({connectedChromeProfileV1:{id:'fictional', secret:'f'.repeat(64),connected:true,windowId:owner.windowId}});
  await chrome.storage.session.set({applicationBrowserSessionV1:'fictional-session'});
  globalThis.calls=[];
  let work={id:'fictional',revision:1,lease_token:'fictional-token',operation,url,binding:{tab_id:null,window_id:owner.windowId}};
  const send=async (_, name, input) => {
    calls.push({name,input});
    if(name==='poll_naukri_work') return {work};
    if(name==='bind_naukri_work') await new Promise((r)=>setTimeout(r,200));
    if(name==='admit_naukri_work' && stop) throw Error('queue_lease_lost');
    work={...work,revision:work.revision+1,binding:{...work.binding,tab_id:input.tab_id}};
    return {work};
  };
  globalThis.queue = new NaukriQueue(chrome,send);
  await queue.tick();
  return {calls, tabs:await chrome.tabs.query({}), ownerId:owner.id};
};`,
);
const started = performance.now();
// Connect with the documented noDefaults option: ordinary Playwright page
// attachment otherwise forces focus emulation, making inactive tabs "visible".
// The real browser owns its visibility; no DOM visibility spoofing is used.
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
const endpointFile = join(profile, "DevToolsActivePort");
for (let i = 0; !existsSync(endpointFile); i++) {
  if (i >= 100 || child.exitCode !== null) {
    child.kill();
    throw Error("isolated_browser_start_timeout");
  }
  await new Promise((r) => setTimeout(r, 100));
}
const [port] = readFileSync(endpointFile, "utf8").trim().split("\n");
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {
  noDefaults: true,
});
const context = browser.contexts()[0];
context.setDefaultTimeout(15000);
let unexpectedRequests = 0,
  chooserEvents = 0,
  fixtureRequests = 0;
const req = "291026123456";
const jobUrl = `https://www.naukri.com/job-listings-fictional-${req}`;
const searchUrl = "https://www.naukri.com/backend-developer-jobs";
const evidence = [];
let modern = false,
  scenario = "";
try {
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== "https://www.naukri.com") {
      unexpectedRequests++;
      return route.abort();
    }
    fixtureRequests++;
    let body = url.pathname.endsWith("-jobs")
      ? `<button id="filter-sort" type="button" aria-controls="filter-sort-menu" onclick="document.querySelector('#filter-sort-menu').style.visibility='visible'">Recommended</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a onclick="document.querySelector('#filter-sort').textContent='Date';document.querySelector('#old-result').href='${jobUrl}'">Date</a></li></ul><a id="old-result" href="https://www.naukri.com/job-listings-older-291026123457">Fictional job</a>`
      : `<div class="styles_jd-header"><h1>Backend Developer</h1><span class="styles_comp-name">Fictional Labs</span><span class="styles_loc-wrap">India</span><span class="styles_exp-wrap">0 - 3 Yrs</span><span>120 Applicants</span><button onclick="window.accidentalClicks=(window.accidentalClicks||0)+1">Apply</button></div><div class="styles_job-desc">Build Python services</div><div class="styles_key-skill"><span class="chip">Python</span></div><script type="application/ld+json">${JSON.stringify({ "@type": "JobPosting", title: "Backend Developer", datePosted: new Date().toISOString(), identifier: { value: req } })}</script>`;
    if (scenario === "unconfirmed_search_sort")
      body = body.replace(
        "document.querySelector('#filter-sort').textContent='Date';",
        "",
      );
    if (scenario === "search_access_restriction")
      body = "<p>Access denied</p>" + body;
    if (modern)
      body = body
        .replace(
          '<div class="styles_jd-header">',
          '<section id="job_header" class="styles_job-header-container">',
        )
        .replace("<h1>", '<h1 class="styles_jd-header-title">')
        .replace(
          '<span class="styles_comp-name">Fictional Labs</span>',
          '<div class="styles_jd-header-comp-name"><a>Fictional Labs</a><span>3.9 95 Reviews</span></div>',
        )
        .replace("styles_exp-wrap", "styles_jhc__exp__abc")
        .replace(
          '<span class="styles_loc-wrap">India</span>',
          '<div class="styles_jhc__loc___Du2H"><i class="ni-icon-location"></i><span class="styles_jhc__location__W_pVs"><a>India</a></span></div>',
        )
        .replace(
          "120 Applicants",
          "<label>Applicants: </label><span>120</span>",
        )
        .replace("</button></div>", "</button></section>");
    if (scenario === "single_years_employment")
      body = body
        .replace("0 - 3 Yrs", "0 years")
        .replace(">India<", ">Hybrid - Bengaluru<")
        .replace(
          '"datePosted":',
          '"employmentType":"Full Time, Permanent","datePosted":',
        );
    return route.fulfill({ contentType: "text/html", body });
  });
  context.on("page", (page) =>
    page.on("filechooser", () => {
      chooserEvents++;
    }),
  );
  const owner = context.pages()[0] || (await context.newPage());
  await owner.goto("about:blank");
  await owner.bringToFront(); // Isolated fictional owner tab; never real Chrome.
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (w) => w.url().endsWith("/fixture.js"),
    }));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.prepare; i++) {
      if (i >= 100) throw Error("fixture_module_start_timeout");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  for (const [name, operation, url, stop] of [
    ["background_job_facts", "inspect_job", jobUrl, false],
    ["current_header_layout", "inspect_job", jobUrl, false],
    ["single_years_employment", "inspect_job", jobUrl, false],
    ["background_search_links", "search_jobs", searchUrl, false],
    ["unconfirmed_search_sort", "search_jobs", searchUrl, false],
    ["search_access_restriction", "search_jobs", searchUrl, false],
    ["stop_before_search_sort", "search_jobs", searchUrl, true],
    ["stop_before_dom", "inspect_job", jobUrl, true],
  ]) {
    modern = ["current_header_layout", "single_years_employment"].includes(
      name,
    );
    scenario = name;
    const result = await worker.evaluate(
      ({ operation, url, stop }) => globalThis.prepare(operation, url, stop),
      { operation, url, stop },
    );
    const finished = result.calls.find((c) => c.name === "finish_naukri_work");
    if (
      name === "unconfirmed_search_sort" ||
      name === "search_access_restriction"
    ) {
      assert.equal(finished, undefined);
      assert.equal(
        result.calls.find((c) => c.name === "abandon_naukri_work")?.input
          .work_report.reason,
        name === "unconfirmed_search_sort"
          ? "search_date_sort_not_confirmed"
          : "provider_challenge_requires_owner",
      );
    } else if (stop) {
      assert.equal(finished, undefined);
      assert.ok(result.calls.some((c) => c.name === "abandon_naukri_work"));
    } else {
      assert.ok(finished, JSON.stringify(result.calls));
      assert.equal(
        finished.input.work_report.kind,
        operation === "inspect_job" ? "job_facts" : "source_candidates",
        JSON.stringify(finished.input.work_report),
      );
      if (operation === "inspect_job")
        assert.equal(finished.input.work_report.job.applicants_min, 120);
      else assert.deepEqual(finished.input.work_report.candidates, [jobUrl]);
      if (name === "single_years_employment") {
        assert.equal(finished.input.work_report.job.experience_min, 0);
        assert.equal(finished.input.work_report.job.experience_max, 0);
        assert.equal(
          finished.input.work_report.job.employment_type,
          "full_time",
        );
        assert.equal(finished.input.work_report.job.remote_type, "hybrid");
      }
    }
    assert.equal(result.tabs.length, 1);
    assert.equal(result.tabs[0].id, result.ownerId);
    assert.equal(result.tabs[0].active, true);
    assert.equal(owner.url(), "about:blank");
    evidence.push({
      name,
      result: "PASS",
      actual_inactive_chromium_tab: true,
      owner_tab_preserved: true,
      provider_requests_routed_to_fixture: true,
    });
  }
  const backgroundFocus = await worker.evaluate(async () => {
    const [original] = await chrome.tabs.query({ active: true });
    const other = await chrome.windows.create({
      url: "https://www.naukri.com/mnjuser/homepage",
      focused: false,
    });
    const focused = (await chrome.windows.get(other.id)).focused;
    const busy = await globalThis.queue.ownerUsingNaukri();
    await chrome.windows.remove(other.id);
    return {
      focused,
      busy,
      ownerStillActive: (await chrome.tabs.get(original.id)).active,
    };
  });
  assert.deepEqual(backgroundFocus, {
    focused: false,
    busy: false,
    ownerStillActive: true,
  });
  evidence.push({
    name: "selected_naukri_in_unfocused_window_allows_background_work",
    result: "PASS",
    owner_tab_preserved: true,
  });
  const maintenance = await worker.evaluate(async () => {
    const [original] = await chrome.tabs.query({ active: true });
    const request = {
      kind: "open_extension_manager",
      request_id: crypto.randomUUID(),
      expires_at: new Date(Date.now() + 60000).toISOString(),
    };
    await globalThis.queue.maintenance(request, {
      window_id: original.windowId,
    });
    const saved = (await chrome.storage.session.get("naukriMaintenanceTabV1"))
      .naukriMaintenanceTabV1;
    const tab = await chrome.tabs.get(saved.tab_id);
    const result = {
      active: tab.active,
      window: tab.windowId === original.windowId,
      ownerStillActive: (await chrome.tabs.get(original.id)).active,
      status: saved.status,
    };
    await chrome.tabs.remove(tab.id);
    return result;
  });
  assert.deepEqual(maintenance, {
    active: false,
    window: true,
    ownerStillActive: true,
    status: "opened",
  });
  evidence.push({
    name: "native_maintenance_creates_only_own_inactive_extensions_tab",
    result: "PASS",
    owner_tab_preserved: true,
  });
  assert.equal(unexpectedRequests, 0);
  assert.equal(chooserEvents, 0);
  const report = {
    fixture_only: true,
    browser: context.browser()?.version(),
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - started),
    live_naukri_requests: 0,
    dns_route_to_provider_blocked: true,
    fixtureRequests,
    unexpectedRequests,
    chooserEvents,
    evidence,
  };
  const args = process.argv.slice(2);
  if (args.length === 2 && args[0] === "--report")
    writeFileSync(args[1], JSON.stringify(report, null, 2) + "\n");
  else if (args.length)
    throw Error("usage: node tests/naukri-queue.browser.mjs [--report FILE]");
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
  child.kill();
  // Preserve this isolated temporary artifact; no workspace or release cleanup.
}
