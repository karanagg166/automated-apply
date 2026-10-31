// Real isolated Chromium tabs + shipped queue/DOM code; fictional provider pages
// and native responses only. Never opens the owner's Chrome or a live vacancy.
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
import { executeNaukri } from './naukri-execution.js';
import { captureNaukriResumeDownload } from './naukri-resume-download.js';
globalThis.download = async (tabId, work) => (await chrome.scripting.executeScript({
 target:{tabId,frameIds:[0]},world:'MAIN',func:captureNaukriResumeDownload,args:[work]
}))[0].result;
globalThis.run = async (tabId, work) => (await chrome.scripting.executeScript({
 target:{tabId,frameIds:[0]},world:'ISOLATED',func:executeNaukri,args:[work]
}))[0].result;
globalThis.create = async (url) => {
 const [owner] = await chrome.tabs.query({active:true});
 const tab = await chrome.tabs.create({url:"about:blank",active:false,windowId:owner.windowId});
 await new Promise(r=>setTimeout(r,200));
 await chrome.tabs.update(tab.id,{url,active:false});
 await new Promise(r=>setTimeout(r,100));
 for(let i=0;i<100;i++) { if((await chrome.tabs.get(tab.id)).status==='complete')return tab.id; await new Promise(r=>setTimeout(r,50)); }
 throw Error('fixture_navigation_timeout');
};
`,
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

const hash = (v) => createHash("sha256").update(v).digest("hex");
const pdf = Buffer.from("%PDF-1.4\nFictional resume only\n%%EOF");
const accountHash = hash("alex@example.com");
const req = "291026123456";
const jobUrl = `https://www.naukri.com/job-listings-fictional-${req}`;
const profileUrl = "https://www.naukri.com/mnjuser/profile";
const historyUrl = "https://www.naukri.com/myapply/historypage";
let mode = "normal",
  savedSummary = "Old fictional summary";
const evidence = [];
try {
  await context.route("**/*", async (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== "https://www.naukri.com") {
      unexpectedRequests++;
      return route.abort();
    }
    fixtureRequests++;
    if (u.pathname === "/download-fictional-resume.pdf")
      return route.fulfill({ contentType: "application/pdf", body: pdf });
    if (u.pathname === "/fixture-save-summary") {
      savedSummary = route.request().postData();
      return route.fulfill({
        contentType: "text/plain",
        body: "saved in fixture",
      });
    }
    const email = `<span class="email">alex@example.com</span>`;
    let body;
    if (u.pathname === "/mnjuser/profile")
      body = `<section class="profile-details">${email}<a href="/download-fictional-resume.pdf">Download Resume</a></section><section><h2>Profile summary</h2><p>${savedSummary}</p><button id="edit-summary">Edit</button></section><script>document.getElementById('edit-summary').onclick=()=>{ const editor=document.createElement('section'); editor.setAttribute('role','dialog');editor.innerHTML='<label>Profile summary<textarea maxlength="4000"></textarea></label><button>Save</button>';document.body.append(editor);editor.querySelector('button').onclick=()=>fetch('/fixture-save-summary',{method:'POST',body:editor.querySelector('textarea').value});};</script>`;
    else if (u.pathname === "/myapply/historypage")
      body = `<header>${email}</header><article><a href="${jobUrl}">Backend Developer</a><span class="company">Fictional Labs</span><span>${mode === "missing_receipt" ? "Viewed" : "Application Sent"}</span></article>`;
    else
      body = `<header>${mode === "wrong_account" ? '<span class="email">other@example.com</span>' : email}</header><div class="styles_jd-header"><h1>Backend Developer</h1><span class="styles_comp-name">Fictional Labs</span><button onclick="window.fixtureClicks=(window.fixtureClicks||0)+1">Apply</button></div>${mode === "challenge" ? "<p>Verify you are human</p>" : ""}`;
    if (
      ["modern_download", "bad_download"].includes(mode) &&
      u.pathname === "/mnjuser/profile"
    )
      body = `<div class="chip-summary"><span class="email-verify">alex@example.com</span></div><div class="section resume"><div class="action-container"><div class="border-box download">Download</div></div><input type="file"><button>Update resume</button></div><script>
        window.originalCreateURL=URL.createObjectURL;window.originalAnchorClick=HTMLAnchorElement.prototype.click;
        document.querySelector('.download').onclick=async()=>{
          window.downloadClicks=(window.downloadClicks||0)+1;
          const response=await fetch('/download-fictional-resume.pdf');
          const bytes=${mode === "bad_download" ? "'fictional invalid PDF'" : "await response.arrayBuffer()"};
          const url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
          const a=document.createElement('a');a.href=url;a.download='fictional.pdf';a.click();URL.revokeObjectURL(url);
        };</script>`;
    if (mode === "modern")
      body =
        body
          .replace(
            '<div class="styles_jd-header">',
            '<section id="job_header" class="styles_job-header-container">',
          )
          .replace("<h1>", '<h1 class="styles_jd-header-title">')
          .replace(
            '<span class="styles_comp-name">Fictional Labs</span>',
            '<div class="styles_jd-header-comp-name"><a>Fictional Labs</a><span>3.9 95 Reviews</span></div>',
          )
          .replace("</button></div>", "</button></section>") +
        '<div class="styles_jd-header-sticky-background" style="display:none"><h1 class="styles_jd-header-title">Backend Developer</h1></div>';
    return route.fulfill({ contentType: "text/html", body });
  });
  context.on("page", (p) => p.on("filechooser", () => chooserEvents++));
  const owner = context.pages()[0];
  await owner.goto("about:blank");
  await owner.bringToFront();
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker"));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.run; i++) {
      if (i === 100) throw Error("module_timeout");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const descriptor = {
    expected_account_sha256: accountHash,
    expected_resume_sha256: hash(pdf),
    expected_title: "Backend Developer",
    expected_company: "Fictional Labs",
  };
  const work = (operation, extra = {}) => ({
    id: "fictional",
    requisition: req,
    url: jobUrl,
    target_url: [
      "inspect_profile",
      "inspect_profile_sync",
      "sync_profile",
    ].includes(operation)
      ? profileUrl
      : operation === "reconcile_application"
        ? historyUrl
        : jobUrl,
    operation,
    execution: { ...descriptor, ...extra },
  });
  const run = (tabId, w) =>
    worker.evaluate(({ tabId, w }) => globalThis.run(tabId, w), { tabId, w });
  const create = (url) => worker.evaluate((url) => globalThis.create(url), url);
  const close = (tabId) =>
    worker.evaluate((tabId) => chrome.tabs.remove(tabId), tabId);
  const record = (name) =>
    evidence.push({
      name,
      result: "PASS",
      fictional_page: true,
      actual_inactive_chromium_tab: true,
    });
  let tabId = await create(profileUrl);
  let result = await run(tabId, work("inspect_profile"));
  assert.equal(
    result.execution?.state,
    "PROFILE_VERIFIED",
    JSON.stringify(result),
  );
  assert.equal(result.execution.resume_sha256, hash(pdf));
  assert.equal(result.execution.resume_bytes, pdf.length);
  record("canonical_provider_pdf_bytes");
  result = await run(
    tabId,
    work("inspect_profile", { expected_resume_sha256: "0".repeat(64) }),
  );
  assert.equal(
    result.reason,
    "provider_saved_resume_differs_from_canonical_pdf",
  );
  record("wrong_saved_resume_refused");
  await close(tabId);

  for (const downloadMode of ["modern_download", "bad_download"]) {
    mode = downloadMode;
    tabId = await create(profileUrl);
    result = await run(tabId, work("inspect_profile"));
    assert.equal(result.reason, "profile_resume_download_capture_required");
    const captured = await worker.evaluate(
      ({ tabId, w }) => globalThis.download(tabId, w),
      { tabId, w: work("inspect_profile") },
    );
    if (downloadMode === "modern_download") {
      assert.equal(captured.sha256, hash(pdf));
      result = await run(
        tabId,
        work("inspect_profile", { provider_pdf_observation: captured }),
      );
      assert.equal(result.execution?.state, "PROFILE_VERIFIED");
      assert.equal(result.execution.resume_bytes, pdf.length);
      const wrong = await run(
        tabId,
        work("inspect_profile", {
          provider_pdf_observation: captured,
          expected_resume_sha256: "0".repeat(64),
        }),
      );
      assert.equal(
        wrong.reason,
        "provider_saved_resume_differs_from_canonical_pdf",
      );
    } else {
      assert.equal(captured.reason, "provider_saved_resume_not_pdf");
    }
    const restored = await worker.evaluate(
      async (tabId) =>
        (
          await chrome.scripting.executeScript({
            target: { tabId },
            world: "MAIN",
            func: () => ({
              url: URL.createObjectURL === window.originalCreateURL,
              click:
                HTMLAnchorElement.prototype.click ===
                window.originalAnchorClick,
              count: window.downloadClicks,
            }),
          })
        )[0].result,
      tabId,
    );
    assert.deepEqual(restored, { url: true, click: true, count: 1 });
    record(
      downloadMode === "modern_download"
        ? "genuine_layout_download_blob_digest_hooks_restored"
        : "invalid_download_pdf_refused_hooks_restored",
    );
    await close(tabId);
  }
  mode = "normal";

  tabId = await create(profileUrl);
  const compared = await run(tabId, work("inspect_profile_sync"));
  assert.equal(
    compared.execution?.profile_fields.summary,
    savedSummary,
    JSON.stringify(compared),
  );
  const canonicalSummary = "Verified fictional summary";
  const written = await run(
    tabId,
    work("sync_profile", {
      document_id: compared.execution.document_id,
      previous_summary_reference: hash(JSON.stringify(savedSummary)),
      approved_summary: canonicalSummary,
      permit_expires_at: new Date(Date.now() + 2000).toISOString(),
    }),
  );
  assert.equal(
    written.execution?.state,
    "PROFILE_SAVE_ATTEMPTED",
    JSON.stringify(written),
  );
  for (let i = 0; savedSummary !== canonicalSummary; i++) {
    if (i >= 50) throw Error("fixture_save_timeout");
    await new Promise((r) => setTimeout(r, 20));
  }
  await close(tabId);
  tabId = await create(profileUrl);
  const verified = await run(tabId, work("inspect_profile_sync"));
  assert.equal(verified.execution.profile_fields.summary, canonicalSummary);
  assert.notEqual(
    verified.execution.document_id,
    compared.execution.document_id,
  );
  record("profile_summary_save_and_independent_reload");
  await close(tabId);

  for (const variant of [
    "normal",
    "modern",
    "expired",
    "changed",
    "double",
    "wrong_account",
    "challenge",
  ]) {
    mode = ["wrong_account", "challenge", "modern"].includes(variant)
      ? variant
      : "normal";
    tabId = await create(jobUrl);
    const observed = await run(tabId, work("inspect_application"));
    if (["wrong_account", "challenge"].includes(variant)) {
      assert.equal(observed.kind, "needs_input");
      assert.match(
        observed.reason,
        /account_identity_unverified|challenge_requires_owner/,
      );
    } else {
      assert.equal(
        observed.execution?.state,
        "NOT_APPLIED",
        JSON.stringify(observed),
      );
      if (variant === "changed")
        await worker.evaluate(
          (tabId) =>
            chrome.scripting.executeScript({
              target: { tabId },
              func: () =>
                (document.querySelector("button").textContent = "Apply Now"),
            }),
          tabId,
        );
      const apply = work("apply", {
        document_id: observed.execution.document_id,
        control_sha256: observed.execution.control_sha256,
        permit_expires_at: new Date(
          Date.now() + (variant === "expired" ? -100 : 2000),
        ).toISOString(),
      });
      const clicked = await run(tabId, apply);
      if (["expired", "changed"].includes(variant))
        assert.equal(clicked.kind, "needs_input");
      else
        assert.equal(
          clicked.execution?.state,
          "CLICKED",
          JSON.stringify(clicked),
        );
      if (variant === "double")
        assert.equal(
          (await run(tabId, apply)).reason,
          "single_use_document_admission_required",
        );
      const count = await worker.evaluate(
        async (tabId) =>
          (
            await chrome.scripting.executeScript({
              target: { tabId },
              world: "MAIN",
              func: () => window.fixtureClicks || 0,
            })
          )[0].result,
        tabId,
      );
      assert.equal(count, ["expired", "changed"].includes(variant) ? 0 : 1);
    }
    record(variant);
    await close(tabId);
  }
  mode = "normal";
  tabId = await create(historyUrl);
  const first = await run(tabId, work("reconcile_application"));
  assert.equal(
    first.execution?.state,
    "APPLICATION_SENT",
    JSON.stringify(first),
  );
  await close(tabId);
  tabId = await create(historyUrl);
  const second = await run(tabId, work("reconcile_application"));
  assert.notEqual(first.execution.document_id, second.execution.document_id);
  record("independent_persistent_history_documents");
  await close(tabId);
  mode = "missing_receipt";
  tabId = await create(historyUrl);
  assert.equal(
    (await run(tabId, work("reconcile_application"))).reason,
    "provider_application_sent_receipt_missing",
  );
  record("generic_status_is_not_receipt");
  await close(tabId);
  const tabs = await worker.evaluate(() => chrome.tabs.query({}));
  assert.equal(tabs.length, 1);
  assert.equal(tabs[0].active, true);
  assert.equal(owner.url(), "about:blank");
  assert.equal(unexpectedRequests, 0);
  assert.equal(chooserEvents, 0);
  const report = {
    fixture_only: true,
    cases: evidence.length,
    browser: browser.version(),
    duration_ms: Math.round(performance.now() - started),
    live_naukri_requests: 0,
    unexpectedRequests,
    chooserEvents,
    fixtureRequests,
    evidence,
  };
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
  child.kill();
}
