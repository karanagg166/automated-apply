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
globalThis.prepare = async (operation, url, stop=false, freezeTimers=false, drainCount=1) => {
  const [owner] = await chrome.tabs.query({active:true});
  await chrome.storage.local.set({connectedChromeProfileV1:{id:'fictional', secret:'f'.repeat(64),connected:true,windowId:owner.windowId}});
  await chrome.storage.session.set({applicationBrowserSessionV1:'fictional-session'});
  globalThis.calls=[];
  let work={id:'fictional',revision:1,lease_token:'fictional-token',operation,url,binding:{tab_id:null,window_id:owner.windowId}};
  let completed=0;
  const send=async (_, name, input) => {
    calls.push({name,input});
    if(name==='poll_naukri_work') {
      if(completed>=drainCount)return {work:null};
      if(completed>0)work={...work,id:'fictional-'+completed,url:url.replace(/([0-9]+)$/,v=>String(Number(v)+completed)),revision:1,binding:{tab_id:null,window_id:owner.windowId}};
      return {work};
    }
    if(name==='bind_naukri_work') await new Promise((r)=>setTimeout(r,200));
    if(name==='admit_naukri_work' && stop) throw Error('queue_lease_lost');
    if(name==='finish_naukri_work') completed++;
    work={...work,revision:work.revision+1,binding:{...work.binding,tab_id:input.tab_id}};
    return {work};
  };
  const originalScript=chrome.scripting.executeScript.bind(chrome.scripting);
  const api={...chrome,scripting:{...chrome.scripting,executeScript:async(input)=>{
    if(freezeTimers && input.func.name==='sortNaukriSearchDate')
      await originalScript({target:input.target,world:'ISOLATED',func:()=>{globalThis.setTimeout=()=>{throw Error('fixture_provider_page_timer_forbidden')};}});
    return originalScript(input);
  }}};
  globalThis.queue = new NaukriQueue(api,send);
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
const filteredUrl =
  searchUrl +
  "?k=backend%20developer&experience=0&nignbevent_src=jobsearchDeskGNB";
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
    const fixtureRequisition = url.pathname.match(/([0-9]+)$/)?.[1] || req;
    let body = /-jobs(?:-[2-3])?$/.test(url.pathname)
      ? `<button id="filter-sort" type="button" aria-controls="filter-sort-menu" onclick="document.querySelector('#filter-sort-menu').style.visibility='visible'">Recommended</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a onclick="document.querySelector('#filter-sort').textContent='Date';document.querySelector('#old-result').href='${jobUrl}'">Date</a></li></ul><a id="old-result" href="https://www.naukri.com/job-listings-older-291026123457">Fictional job</a>`
      : `<div class="styles_jd-header"><h1>Backend Developer</h1><span class="styles_comp-name">Fictional Labs</span><span class="styles_loc-wrap">India</span><span class="styles_exp-wrap">0 - 3 Yrs</span><span>120 Applicants</span><button onclick="window.accidentalClicks=(window.accidentalClicks||0)+1">Apply</button></div><div class="styles_job-desc">Build Python services</div><div class="styles_key-skill"><span class="chip">Python</span></div><script type="application/ld+json">${JSON.stringify({ "@type": "JobPosting", title: "Backend Developer", datePosted: new Date().toISOString(), identifier: { value: fixtureRequisition } })}</script>`;
    if (scenario === "read_drain_challenge" && fixtureRequisition !== req)
      body = "<p>Access denied</p>" + body;
    if (scenario.startsWith("fresher_keyword_")) {
      // Genuine behavior: initial relevant cards differ from the Date result
      // set. A Date click must not leak that unrelated set into discovery.
      body = `<button id="filter-sort" type="button" aria-controls="filter-sort-menu">Recommended</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a>Date</a></li></ul><a id="old-result" href="${jobUrl}">Fictional junior job</a><script>
const control=document.querySelector('#filter-sort'), menu=document.querySelector('#filter-sort-menu');
control.onclick=()=>menu.style.visibility='visible';menu.querySelector('a').onclick=()=>{control.textContent='Date';document.querySelector('#old-result').href='https://www.naukri.com/job-listings-unrelated-senior-291026654321';};
</script>`;
      if (scenario === "fresher_keyword_page_two")
        body += `<nav aria-label="Pagination"><a aria-current="page" href="${url.href}">2</a></nav>`;
      if (scenario === "fresher_keyword_wrong_order")
        body = body.replace(
          'aria-controls="filter-sort-menu">Recommended</button>',
          'aria-controls="filter-sort-menu">Date</button>',
        );
      if (scenario.startsWith("fresher_keyword_freshness")) {
        body = body.replace(
          `id="old-result" href="${jobUrl}"`,
          'id="old-result" href="https://www.naukri.com/job-listings-older-291026123457"',
        );
        body += `<button id="filter-freshness" type="button" aria-haspopup="listbox" aria-controls="filter-freshness-menu">Select</button><ul id="filter-freshness-menu" style="visibility:hidden"><li role="option" title="Last 1 day"><a data-id="filter-freshness-1" ${scenario.endsWith("external") ? 'href="https://example.org/elsewhere"' : ""}>Last 1 day</a></li></ul><script>
const fresh=document.querySelector('#filter-freshness'), options=document.querySelector('#filter-freshness-menu');fresh.onclick=()=>options.style.visibility='visible';options.querySelector('a').onclick=e=>{e.preventDefault();fresh.textContent='Last 1 day';options.style.visibility='hidden';document.querySelector('#old-result').href='${jobUrl}';window.freshnessSelections=(window.freshnessSelections||0)+1;};
</script>`;
      }
    }
    if (
      [
        "background_paginated_search_links",
        "paginated_sort_without_page_timers",
      ].includes(scenario)
    ) {
      body = `<button id="filter-sort" type="button" aria-controls="filter-sort-menu">Recommended</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a>Date</a></li></ul><nav aria-label="Pagination"></nav><a id="old-result" href="https://www.naukri.com/job-listings-older-291026123457">Fictional job</a><script>
const base=${JSON.stringify(searchUrl)}, job=${JSON.stringify(jobUrl)};
const nav=document.querySelector('nav'), control=document.querySelector('#filter-sort'), menu=document.querySelector('#filter-sort-menu');
function page(n){nav.innerHTML='<a aria-current="page" href="'+base+(n>1?'-'+n:'')+'">'+n+'</a><a href="'+base+'-'+(n+1)+'">Next</a>';nav.lastElementChild.onclick=e=>{e.preventDefault();history.replaceState(null,'',base+'-'+(n+1));page(n+1);document.querySelector('#old-result').href=job;};}
page(2);control.onclick=()=>menu.style.visibility='visible';menu.querySelector('a').onclick=()=>{control.textContent='Date';history.replaceState(null,'',base);page(1);};
</script>`;
    }
    if (scenario === "unconfirmed_search_sort")
      body = body.replace(
        "document.querySelector('#filter-sort').textContent='Date';",
        "",
      );
    if (scenario === "search_access_restriction")
      body = "<p>Access denied</p>" + body;
    if (scenario.startsWith("filtered_fresher_")) {
      const any = scenario === "filtered_fresher_any";
      body =
        `<input id="experienceDD" value="${any ? "" : "Fresher"}"><section class="experiencecontainer"><div class="rc-slider${any ? " not-selected" : ""}"><div role="slider" aria-label="Experience" aria-valuenow="0">${any ? "Any" : "0"}</div></div></section>` +
        body;
      if (scenario === "filtered_fresher_duplicate")
        body += '<input id="experienceDD" value="Fresher">';
      if (scenario === "filtered_fresher_lost_query")
        body +=
          '<script>history.replaceState(null,"",location.pathname)</script>';
      if (scenario === "filtered_fresher_lost_after_date")
        body = body.replace(
          "document.querySelector('#filter-sort').textContent='Date';",
          "document.querySelector('#filter-sort').textContent='Date';history.replaceState(null,'',location.pathname);",
        );
    }
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
    if (scenario.startsWith("current_details_")) {
      body = body.replace(
        '<div class="styles_job-desc">Build Python services</div>',
        '<section class="styles_job-desc-container__txpYf"><div class="styles_JDC__match-score__VnjLL">Platform match score</div><div class="styles_JDC__dang-inner-html__h0K4t"><p>Build Python services.</p><ul><li>Maintain SQL data.</li></ul></div><div class="styles_other-details__oEN4O"><div class="styles_details__Y424J"><label>Employment Type: </label><span><span>Full Time, Permanent</span></span></div></div><div>Share this job</div></section>',
      );
      if (scenario === "current_details_conflict")
        body = body.replace(
          '"datePosted":',
          '"employmentType":"internship","datePosted":',
        );
      if (scenario === "current_details_ambiguous")
        body = body.replace(
          "<div>Share this job</div>",
          '<div class="styles_JDC__dang-inner-html__different">A different description</div>',
        );
    }
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
    ["current_details_visible", "inspect_job", jobUrl, false],
    ["current_details_conflict", "inspect_job", jobUrl, false],
    ["current_details_ambiguous", "inspect_job", jobUrl, false],
    ["background_search_links", "search_jobs", searchUrl, false],
    ...["success", "any", "duplicate", "lost_query", "lost_after_date"].map(
      (suffix) => [
        "filtered_fresher_" + suffix,
        "search_jobs",
        filteredUrl,
        false,
      ],
    ),
    [
      "fresher_keyword_relevance",
      "search_jobs",
      searchUrl.replace("-jobs", "-fresher-jobs"),
      false,
    ],
    [
      "fresher_keyword_page_two",
      "search_jobs",
      searchUrl.replace("-jobs", "-fresher-jobs-2"),
      false,
    ],
    [
      "fresher_keyword_wrong_order",
      "search_jobs",
      searchUrl.replace("-jobs", "-fresher-jobs"),
      false,
    ],
    [
      "fresher_keyword_freshness",
      "search_jobs",
      searchUrl.replace("-jobs", "-fresher-jobs"),
      false,
    ],
    [
      "fresher_keyword_freshness_external",
      "search_jobs",
      searchUrl.replace("-jobs", "-fresher-jobs"),
      false,
    ],
    [
      "background_paginated_search_links",
      "search_jobs",
      searchUrl + "-2",
      false,
    ],
    ["unconfirmed_search_sort", "search_jobs", searchUrl, false],
    [
      "paginated_sort_without_page_timers",
      "search_jobs",
      searchUrl + "-2",
      false,
    ],
    ["search_access_restriction", "search_jobs", searchUrl, false],
    ["stop_before_search_sort", "search_jobs", searchUrl, true],
    ["stop_before_dom", "inspect_job", jobUrl, true],
  ]) {
    modern = ["current_header_layout", "single_years_employment"].includes(
      name,
    );
    scenario = name;
    const result = await worker.evaluate(
      ({ operation, url, stop, freezeTimers }) =>
        globalThis.prepare(operation, url, stop, freezeTimers),
      {
        operation,
        url,
        stop,
        freezeTimers: name === "paginated_sort_without_page_timers",
      },
    );
    const finished = result.calls.find((c) => c.name === "finish_naukri_work");
    if (
      name.startsWith("filtered_fresher_") &&
      name !== "filtered_fresher_success"
    ) {
      assert.equal(finished, undefined);
      assert.equal(
        result.calls.find((c) => c.name === "abandon_naukri_work")?.input
          .work_report.reason,
        name === "filtered_fresher_any"
          ? "search_date_sort_not_confirmed"
          : name === "filtered_fresher_duplicate"
            ? "search_experience_filter_ambiguous"
            : "search_experience_filter_changed",
      );
    } else if (
      name === "unconfirmed_search_sort" ||
      name === "search_access_restriction" ||
      name === "fresher_keyword_wrong_order" ||
      name === "fresher_keyword_freshness_external"
    ) {
      assert.equal(finished, undefined);
      assert.equal(
        result.calls.find((c) => c.name === "abandon_naukri_work")?.input
          .work_report.reason,
        name === "unconfirmed_search_sort"
          ? "search_date_sort_not_confirmed"
          : name === "fresher_keyword_freshness_external"
            ? "search_freshness_option_unsupported"
            : name === "fresher_keyword_wrong_order"
              ? "search_keyword_order_unrecognized"
              : "provider_challenge_requires_owner",
      );
    } else if (name === "current_details_ambiguous") {
      assert.equal(
        finished.input.work_report.reason,
        "job_description_ambiguous",
      );
      assert.equal(finished.input.work_report.job, undefined);
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
        assert.equal(finished.input.work_report.job.experience_max, null);
        assert.equal(
          finished.input.work_report.job.employment_type,
          "full_time",
        );
        assert.equal(finished.input.work_report.job.remote_type, "hybrid");
      }
      if (name.startsWith("current_details_")) {
        assert.equal(
          finished.input.work_report.job.description,
          "Build Python services. Maintain SQL data.",
        );
        assert.equal(
          finished.input.work_report.job.employment_type,
          name === "current_details_conflict" ? null : "full_time",
        );
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
  for (const challenge of [false, true]) {
    modern = false;
    scenario = challenge ? "read_drain_challenge" : "read_drain_success";
    const result = await worker.evaluate(
      (url) => globalThis.prepare("inspect_job", url, false, false, 4),
      jobUrl,
    );
    assert.equal(
      result.calls.filter((c) => c.name === "finish_naukri_work").length,
      challenge ? 2 : 3,
    );
    assert.equal(result.calls.filter((c) => c.name === "create").length, 0); // Native call log excludes tab API operations.
    assert.equal(result.tabs.length, 1);
    assert.equal(result.tabs[0].id, result.ownerId);
    assert.equal(result.tabs[0].active, true);
    if (challenge) {
      assert.equal(
        result.calls.filter((c) => c.name === "finish_naukri_work").at(-1).input
          .work_report.reason,
        "provider_challenge_requires_owner",
      );
    } else {
      assert.equal(
        new Set(
          result.calls
            .filter((c) => c.name === "finish_naukri_work")
            .map((c) => c.input.work_id),
        ).size,
        3,
      );
      const resumed = await worker.evaluate(async () => {
        await queue.tick();
        return { calls, tabs: await chrome.tabs.query({}) };
      });
      assert.equal(
        resumed.calls.filter((c) => c.name === "finish_naukri_work").length,
        4,
      );
      assert.equal(resumed.tabs.length, 1);
    }
    evidence.push({
      name: scenario,
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
