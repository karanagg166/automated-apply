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
import { fixtureExecutable } from "./browser-fixture-engine.mjs";

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
import { executeNaukri } from './naukri-execution.js';
import { naukriChatbot } from './naukri-chatbot.js';
import { captureNaukriResumeDownload } from './naukri-resume-download.js';
globalThis.chat = async (tabId, request) => (await chrome.scripting.executeScript({
 target:{tabId,frameIds:[0]},world:'ISOLATED',func:naukriChatbot,args:[request]
}))[0].result;
globalThis.download = async (tabId, work) => (await chrome.scripting.executeScript({
 target:{tabId,frameIds:[0]},world:'MAIN',func:captureNaukriResumeDownload,args:[work]
}))[0].result;
globalThis.fixtureBinding = async (tabId) => ({profile_binding_id:'fixture-profile',profile_version:1,selection_version:1,browser_session_id:'fixture-browser-session',window_id:(await chrome.tabs.get(tabId)).windowId,tab_id:tabId});
globalThis.run = async (tabId, work) => (await chrome.scripting.executeScript({
 target:{tabId,frameIds:[0]},world:'ISOLATED',func:executeNaukri,args:[{...work,binding:await globalThis.fixtureBinding(tabId)}]
}))[0].result;
globalThis.navigate = async (tabId,url) => {await chrome.tabs.update(tabId,{url,active:false});await new Promise(r=>setTimeout(r,100));for(let i=0;i<100;i++){if((await chrome.tabs.get(tabId)).status==='complete')return;await new Promise(r=>setTimeout(r,50));}throw Error('fixture_navigation_timeout');};
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
    if (mode.startsWith("follow_") && u.pathname.startsWith("/job-listings-")) {
      const label =
        mode === "follow_unknown"
          ? "Subscribe to other messages"
          : "Follow Fictional Labs as you apply to stay updated";
      body = body
        .replace(
          "</button></div>",
          `</button><div class="styles_fb_ckb_container__fixture"><i role="checkbox" tabindex="0" aria-checked="${mode === "follow_unchecked" ? "false" : "true"}" aria-label="${label}" style="display:inline-block;width:14px;height:14px"></i><label>${label}</label></div></div>`,
        )
        .replace(
          "window.fixtureClicks=(window.fixtureClicks||0)+1",
          "window.followAtApply=document.querySelector('[role=checkbox]').getAttribute('aria-checked');window.fixtureClicks=(window.fixtureClicks||0)+1;this.textContent='Applied'",
        );
      body += `<script>document.querySelector('[role=checkbox]').onclick=e=>{window.followClicks=(window.followClicks||0)+1;${mode === "follow_stuck" ? "" : "e.target.setAttribute('aria-checked','false');"}${mode === "follow_injected_choice" ? "const c=document.createElement('input');c.type='checkbox';c.checked=true;document.body.append(c);" : ""}};</script>`;
    }
    if (mode === "questionnaire")
      body = body.replace(
        "window.fixtureClicks=(window.fixtureClicks||0)+1",
        "window.fixtureClicks=(window.fixtureClicks||0)+1;setTimeout(()=>{const d=document.createElement('div');d.className='chatbot_DrawerContentWrapper';d.innerHTML='<div class=chatbot_MessageContainer><div class=botItem><div class=botMsg>Which office can you start from?</div></div></div><div class=chipsContainer><div class=chatbot_Chip>Pune</div><div class=chatbot_Chip>Delhi</div></div>';d.querySelectorAll('.chatbot_Chip').forEach(c=>c.onclick=()=>{window.choiceSaves=(window.choiceSaves||0)+1;d.innerHTML='<div class=chatbot_MessageContainer><div class=botItem><div class=botMsg>What is your full name?</div></div></div><div class=textArea contenteditable=true></div><div class=chipsContainer><div class=chatbot_Chip>Skip this question</div></div><div class=send><span class=sendMsg>Save</span></div>';d.querySelector('.send').onclick=()=>{window.textSaves=(window.textSaves||0)+1;window.savedText=d.querySelector('.textArea').textContent;d.remove()}});document.body.append(d)},200)",
      );
    if (mode === "modern_profile_summary" && u.pathname === "/mnjuser/profile")
      body = `<section class="profile-details">${email}<a href="/download-fictional-resume.pdf">Download Resume</a></section><div class="award-details section profileSummary"><div class="heading-container ${savedSummary ? "" : "cursor"}"><div class="text-container"><h1 class="section-heading">Profile Summary ${savedSummary ? '<span class="new-pencil" style="display:inline-block;width:14px;height:14px" aria-label="Edit profile summary"></span>' : ""}</h1>${savedSummary ? "" : '<h2 class="section-sub-heading">Write a meaningful summary of more than 50 characters.</h2>'}</div>${savedSummary ? "" : '<div class="add-more">Add</div>'}</div>${savedSummary ? `<div class="card-container"><div class="card-details"><p class="card-sub-heading">${savedSummary}</p></div></div>` : ""}</div><script>document.querySelector('.profileSummary .new-pencil,.profileSummary .add-more').onclick=()=>{setTimeout(()=>{const editor=document.createElement('div');editor.setAttribute('role','dialog');editor.innerHTML='<h1>Profile summary</h1><form name="skillDetailsForm"><textarea id="summary" name="summary" minlength="50" maxlength="1000"></textarea><button id="submit-btn" type="button" disabled>Save</button></form>';document.body.append(editor);editor.querySelector('textarea').oninput=()=>queueMicrotask(()=>editor.querySelector('button').disabled=false);editor.querySelector('button').onclick=()=>fetch('/fixture-save-summary',{method:'POST',body:editor.querySelector('textarea').value});},75);};</script>`;
    if (mode === "professional_profile" && u.pathname === "/mnjuser/profile")
      body = `<div class="detail-list"><div class="with-cta"><em name="Email">mailOneTheme</em><span class="txt" name="Email">alex@example.com</span></div></div><input type="email" value="different-contact@example.org"><div class="dashboard-component"><div class="hdn"><span class="fullname">Alex Example</span></div><div class="detail-list"><span class="txt" name="Mobile">+91 (123) 456-7890</span><span class="txt" name="Location">Pune, India</span></div></div><div class="card"><div class="widgetHead"><span class="widgetTitle">Key skills</span></div><div class="widgetCont"><div class="prefill"><span class="chip">Python</span><span class="chip">SQL</span></div></div></div><div class="card"><div class="widgetHead"><span class="widgetTitle">Employment</span></div><div class="widgetCont"><div class="emp-list">Fictional role</div></div></div><div class="card"><div class="widgetHead"><span class="widgetTitle">Education</span></div><div class="widgetCont"><div class="edu-list">Fictional education</div></div></div><div class="card"><div class="widgetHead"><span class="widgetTitle">Projects</span></div><div class="widgetCont"><span class="empty">Add projects</span></div></div><div id="lazyAttachCV" class="card"><div class="attachCV"><div role="heading" aria-label="Resume">Resume</div><div class="cvPreview"><span role="button" aria-label="Download resume" data-title="download-resume">downloadOneTheme</span><span role="button" aria-label="Delete resume">deleteOneTheme</span></div></div></div><div class="card"><div class="widgetHead"><span class="widgetTitle">Profile summary</span><span role="button" aria-label="Edit profile summary">editOneTheme</span></div><div class="widgetCont"><div class="prefill">${savedSummary.slice(0, 12)}...<a class="morelink" aria-label="Read more of profile summary">Read More</a></div></div></div><script>window.professionalDownloadClicks=0;document.querySelector('[aria-label="Download resume"]').onclick=()=>{window.professionalDownloadClicks++;fetch('/download-fictional-resume.pdf').then(r=>r.blob()).then(blob=>{const url=URL.createObjectURL(blob);const a=document.createElement('a');a.target='_blank';a.download='fictional.pdf';a.href=url;a.click();setTimeout(()=>URL.revokeObjectURL(url),100);});};document.querySelector('[aria-label="Read more of profile summary"]').onclick=e=>{e.target.closest('.prefill').textContent=${JSON.stringify(savedSummary)}};</script>`;
    if (
      ["modern_download", "bad_download", "dispatch_download"].includes(mode) &&
      u.pathname === "/mnjuser/profile"
    )
      body = `<div class="chip-summary"><span class="email-verify">alex@example.com</span></div><div class="section resume"><div class="action-container"><div class="border-box download">Download</div></div><input type="file"><button>Update resume</button></div><script>
        window.originalCreateURL=URL.createObjectURL;window.originalAnchorClick=HTMLAnchorElement.prototype.click;window.originalClickOwn=Object.hasOwn(HTMLAnchorElement.prototype,'click');window.originalAnchorDispatch=HTMLAnchorElement.prototype.dispatchEvent;window.originalDispatchOwn=Object.hasOwn(HTMLAnchorElement.prototype,'dispatchEvent');
        document.querySelector('.download').onclick=async()=>{
          window.downloadClicks=(window.downloadClicks||0)+1;
          const response=await fetch('/download-fictional-resume.pdf');
          const bytes=${mode === "bad_download" ? "'fictional invalid PDF'" : "await response.arrayBuffer()"};
          const url=URL.createObjectURL(new Blob([bytes],{type:'${mode === "dispatch_download" ? "application/octet-stream" : "application/pdf"}'}));
          const a=document.createElement('a');a.href=url;a.download='fictional.pdf';${mode === "dispatch_download" ? "a.dispatchEvent(new MouseEvent('click'))" : "a.click()"};URL.revokeObjectURL(url);
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
    if (mode === "no_account_label" && u.pathname !== "/mnjuser/profile")
      body =
        body.replace(email, "") +
        '<input type="email" value="contact-alias@example.org">';
    return route.fulfill({ contentType: "text/html", body });
  });
  context.on("page", (p) => p.on("filechooser", () => chooserEvents++));
  const owner = context.pages()[0];
  await owner.goto("about:blank");
  await owner.bringToFront();
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (w) => w.url().endsWith("/fixture.js"),
    }));
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
      "verify_account",
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
  let tabId;
  if (!process.env.NAUKRI_PROFILE_ONLY) {
    tabId = await create(profileUrl);
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

    mode = "no_account_label";
    tabId = await create(profileUrl);
    const accountRead = await run(tabId, work("verify_account"));
    assert.equal(accountRead.execution?.state, "PROFILE_OBSERVED");
    assert.equal(accountRead.execution.account_sha256, accountHash);
    const binding = await worker.evaluate(
      (id) => globalThis.fixtureBinding(id),
      tabId,
    );
    const proof = {
      source: "profile_ui",
      work_id: "fictional",
      account_sha256: accountRead.execution.account_sha256,
      profile_document_id: accountRead.execution.document_id,
      observed_at: new Date().toISOString(),
      binding,
    };
    const navigate = (url) =>
      worker.evaluate(({ id, url }) => globalThis.navigate(id, url), {
        id: tabId,
        url,
      });
    await navigate(jobUrl);
    const absent = await run(tabId, work("inspect_application"));
    assert.equal(absent.reason, "provider_account_identity_unverified");
    const bound = await run(
      tabId,
      work("inspect_application", { account_observation: proof }),
    );
    assert.equal(bound.execution?.state, "NOT_APPLIED", JSON.stringify(bound));
    assert.equal(bound.execution.account_sha256, accountHash);
    record(
      "real_layout_without_email_uses_bound_profile_observation_not_contact_input",
    );
    for (const [name, changed] of [
      [
        "expired_profile_account",
        { ...proof, observed_at: new Date(Date.now() - 180000).toISOString() },
      ],
      [
        "future_profile_account",
        { ...proof, observed_at: new Date(Date.now() + 60000).toISOString() },
      ],
      ["different_work_account", { ...proof, work_id: "different" }],
      ["invalid_profile_document", { ...proof, profile_document_id: "bad" }],
      [
        "different_profile_account",
        { ...proof, binding: { ...binding, profile_binding_id: "different" } },
      ],
      [
        "different_tab_account",
        { ...proof, binding: { ...binding, tab_id: binding.tab_id + 1 } },
      ],
    ]) {
      const denied = await run(
        tabId,
        work("inspect_application", { account_observation: changed }),
      );
      assert.equal(denied.reason, "provider_account_identity_unverified", name);
      record(name);
    }
    const applied = await run(
      tabId,
      work("apply", {
        account_observation: proof,
        document_id: bound.execution.document_id,
        control_sha256: bound.execution.control_sha256,
        permit_expires_at: new Date(Date.now() + 1500).toISOString(),
      }),
    );
    assert.equal(applied.execution?.state, "CLICKED", JSON.stringify(applied));
    await navigate(historyUrl);
    const history = await run(
      tabId,
      work("reconcile_application", { account_observation: proof }),
    );
    assert.equal(history.execution?.state, "APPLICATION_SENT");
    record(
      "bound_profile_account_preserves_direct_apply_and_independent_history_checks",
    );
    mode = "wrong_account";
    await navigate(jobUrl);
    const mismatch = await run(
      tabId,
      work("inspect_application", { account_observation: proof }),
    );
    assert.equal(mismatch.reason, "provider_account_identity_unverified");
    record("visible_wrong_account_is_not_overridden_by_profile_observation");
    mode = "questionnaire";
    await navigate(jobUrl);
    const beforeQuestionnaire = await run(
      tabId,
      work("inspect_application", { account_observation: proof }),
    );
    const questionnaireApply = work("apply", {
      account_observation: proof,
      document_id: beforeQuestionnaire.execution.document_id,
      control_sha256: beforeQuestionnaire.execution.control_sha256,
      permit_expires_at: new Date(Date.now() + 1500).toISOString(),
    });
    const questionnaire = await run(tabId, questionnaireApply);
    assert.equal(
      questionnaire.execution?.state,
      "QUESTIONNAIRE",
      JSON.stringify(questionnaire),
    );
    assert.equal(
      (await run(tabId, questionnaireApply)).reason,
      "single_use_document_admission_required",
    );
    record(
      "asynchronous_real_structure_questionnaire_is_handed_off_without_a_second_apply",
    );
    const chat = (request) =>
      worker.evaluate(({ tabId, request }) => globalThis.chat(tabId, request), {
        tabId,
        request,
      });
    const chatRequest = { operation: "inspect", url: jobUrl, requisition: req };
    const choice = await chat(chatRequest);
    assert.deepEqual(choice.options, ["Pune", "Delhi"]);
    const answerRequest = {
      ...chatRequest,
      operation: "answer",
      document_id: choice.document_id,
      step_sha256: choice.step_sha256,
      answer: "Pune",
      permit_expires_at: new Date(Date.now() + 2000).toISOString(),
    };
    assert.equal(
      (await chat(answerRequest)).kind,
      "questionnaire_answer_attempted",
    );
    assert.equal(
      (await chat(answerRequest)).reason,
      "questionnaire_step_changed_or_consumed",
    );
    record("genuine_div_choices_are_clicked_once_in_an_inactive_renderer");
    const text = await chat(chatRequest);
    assert.equal(text.answer_kind, "text");
    assert.deepEqual(text.options, []);
    assert.equal(
      (
        await chat({
          ...answerRequest,
          document_id: text.document_id,
          step_sha256: text.step_sha256,
          answer: "Alex Fixture",
          permit_expires_at: new Date(Date.now() + 2000).toISOString(),
        })
      ).kind,
      "questionnaire_answer_attempted",
    );
    const counts = await worker.evaluate(
      async (tabId) =>
        (
          await chrome.scripting.executeScript({
            target: { tabId },
            world: "MAIN",
            func: () => ({
              apply: window.fixtureClicks,
              choice: window.choiceSaves,
              text: window.textSaves,
              value: window.savedText,
              hidden: document.visibilityState,
            }),
          })
        )[0].result,
      tabId,
    );
    assert.deepEqual(counts, {
      apply: 1,
      choice: 1,
      text: 1,
      value: "Alex Fixture",
      hidden: "hidden",
    });
    record(
      "contenteditable_with_optional_skip_saves_text_without_keyboard_focus_or_a_second_apply",
    );
    await close(tabId);
    mode = "normal";

    for (const downloadMode of [
      "modern_download",
      "bad_download",
      "dispatch_download",
    ]) {
      mode = downloadMode;
      tabId = await create(profileUrl);
      result = await run(tabId, work("inspect_profile"));
      assert.equal(result.reason, "profile_resume_download_capture_required");
      const captured = await worker.evaluate(
        ({ tabId, w }) => globalThis.download(tabId, w),
        { tabId, w: work("inspect_profile") },
      );
      if (downloadMode !== "bad_download") {
        assert.equal(captured.sha256, hash(pdf));
        assert.equal(
          captured.download_event,
          downloadMode === "dispatch_download"
            ? "anchor_dispatch"
            : "anchor_click",
        );
        const resumeCompare = await run(
          tabId,
          work("inspect_profile_sync", {
            verify_saved_resume: true,
          }),
        );
        assert.equal(
          resumeCompare.reason,
          "profile_resume_download_capture_required",
        );
        const comparedPDF = await run(
          tabId,
          work("inspect_profile_sync", {
            verify_saved_resume: true,
            provider_pdf_observation: captured,
          }),
        );
        assert.equal(comparedPDF.execution?.state, "PROFILE_OBSERVED");
        assert.equal(comparedPDF.execution.resume_sha256, hash(pdf));
        assert.equal(comparedPDF.execution.resume_bytes, pdf.length);
        const wrongCompare = await run(
          tabId,
          work("inspect_profile_sync", {
            verify_saved_resume: true,
            provider_pdf_observation: captured,
            expected_resume_sha256: "0".repeat(64),
          }),
        );
        assert.equal(
          wrongCompare.reason,
          "provider_saved_resume_differs_from_canonical_pdf",
        );
        record(
          "read_only_profile_comparison_verifies_downloaded_pdf_without_job_or_apply",
        );
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
                    window.originalAnchorClick &&
                  Object.hasOwn(HTMLAnchorElement.prototype, "click") ===
                    window.originalClickOwn,
                dispatch:
                  HTMLAnchorElement.prototype.dispatchEvent ===
                    window.originalAnchorDispatch &&
                  Object.hasOwn(
                    HTMLAnchorElement.prototype,
                    "dispatchEvent",
                  ) === window.originalDispatchOwn,
                count: window.downloadClicks,
              }),
            })
          )[0].result,
        tabId,
      );
      assert.deepEqual(restored, {
        url: true,
        click: true,
        dispatch: true,
        count: 1,
      });
      record(
        downloadMode === "bad_download"
          ? "invalid_download_pdf_refused_hooks_restored"
          : downloadMode === "dispatch_download"
            ? "dispatch_octet_stream_pdf_digest_exact_hooks_restored"
            : "genuine_layout_download_blob_digest_hooks_restored",
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
  }

  mode = "modern_profile_summary";
  savedSummary = "";
  tabId = await create(profileUrl);
  const missingModern = await run(tabId, work("inspect_profile_sync"));
  assert.equal(missingModern.execution?.profile_fields.summary, "");
  record("genuine_H1_profile_summary_placeholder_is_empty_not_saved_text");
  const modernSummary =
    "Verified fictional backend and full stack experience for the profile acceptance fixture.";
  const modernSaved = await run(
    tabId,
    work("sync_profile", {
      document_id: missingModern.execution.document_id,
      previous_summary_reference: null,
      approved_summary: modernSummary,
      permit_expires_at: new Date(Date.now() + 2000).toISOString(),
    }),
  );
  assert.equal(
    modernSaved.execution?.state,
    "PROFILE_SAVE_ATTEMPTED",
    JSON.stringify(modernSaved),
  );
  for (let i = 0; savedSummary !== modernSummary; i++) {
    if (i >= 50) throw Error("modern_summary_save_timeout");
    await new Promise((r) => setTimeout(r, 20));
  }
  await close(tabId);
  tabId = await create(profileUrl);
  const modernRead = await run(tabId, work("inspect_profile_sync"));
  assert.equal(modernRead.execution?.profile_fields.summary, modernSummary);
  assert.notEqual(
    modernRead.execution.document_id,
    missingModern.execution.document_id,
  );
  record(
    "genuine_unlabelled_summary_modal_saves_inside_unchanged_permit_and_persists_after_reload",
  );
  const revisedSummary = modernSummary + " Additional verified fixture facts.";
  const modernEdited = await run(
    tabId,
    work("sync_profile", {
      document_id: modernRead.execution.document_id,
      previous_summary_reference: hash(JSON.stringify(modernSummary)),
      approved_summary: revisedSummary,
      permit_expires_at: new Date(Date.now() + 2000).toISOString(),
    }),
  );
  assert.equal(
    modernEdited.execution?.state,
    "PROFILE_SAVE_ATTEMPTED",
    JSON.stringify(modernEdited),
  );
  record("genuine_pencil_control_uses_same_preimage_and_single_use_guards");
  await close(tabId);

  mode = "professional_profile";
  tabId = await create(profileUrl);
  const professional = await run(tabId, work("inspect_profile_sync"));
  assert.equal(
    professional.execution?.profile_fields.summary,
    savedSummary,
    JSON.stringify(professional),
  );
  assert.equal(professional.execution.account_sha256, accountHash);
  record(
    "professional_profile_account_and_expanded_summary_use_actual_widgets",
  );
  assert.deepEqual(professional.execution.profile_fields.skills, [
    "Python",
    "SQL",
  ]);
  assert.equal(professional.execution.profile_fields.full_name, "Alex Example");
  assert.equal(
    professional.execution.profile_fields.phone,
    "+91 (123) 456-7890",
  );
  assert.equal(professional.execution.profile_fields.location, "Pune, India");
  assert.deepEqual(professional.execution.profile_fields.projects, []);
  assert.deepEqual(professional.execution.profile_fields.experience, {
    presence_only: true,
  });
  assert.deepEqual(professional.execution.profile_fields.education, {
    presence_only: true,
  });
  record(
    "observed_profile_widgets_expose_skills_and_explicit_empty_projects_without_inventing_career_details",
  );
  await worker.evaluate(
    async (id) =>
      chrome.scripting.executeScript({
        target: { tabId: id },
        func: () => {
          document.querySelector('[name="Mobile"]').textContent =
            "+91 12*****890";
          const original = [...document.querySelectorAll(".widgetTitle")]
            .find((e) => e.textContent === "Key skills")
            .closest(".card");
          document.body.append(original.cloneNode(true));
        },
      }),
    tabId,
  );
  const ambiguousFields = await run(tabId, work("inspect_profile_sync"));
  assert.equal(ambiguousFields.execution.profile_fields.phone, undefined);
  assert.equal(ambiguousFields.execution.profile_fields.skills, undefined);
  assert.equal(ambiguousFields.execution.profile_fields.preferences, undefined);
  record(
    "duplicate_skill_widgets_masked_phone_and_unrecognized_preferences_remain_unknown",
  );
  assert.equal(
    (await run(tabId, work("inspect_profile"))).reason,
    "profile_resume_download_capture_required",
  );
  const professionalPdf = await worker.evaluate(
    ({ tabId, url }) => globalThis.download(tabId, { target_url: url }),
    { tabId, url: profileUrl },
  );
  assert.equal(
    professionalPdf.kind,
    "provider_pdf_digest",
    JSON.stringify(professionalPdf),
  );
  assert.equal(professionalPdf.sha256, hash(pdf));
  assert.equal(
    (
      await run(
        tabId,
        work("inspect_profile", { provider_pdf_observation: professionalPdf }),
      )
    ).execution?.state,
    "PROFILE_VERIFIED",
  );
  record(
    "professional_download_span_is_captured_in_MAIN_and_rechecked_in_ISOLATED",
  );
  const professionalCounts = await worker.evaluate(
    async (tabId) =>
      (
        await chrome.scripting.executeScript({
          target: { tabId },
          world: "MAIN",
          func: () => ({
            downloads: window.professionalDownloadClicks,
            hidden: document.visibilityState === "hidden",
          }),
        })
      )[0].result,
    tabId,
  );
  assert.deepEqual(professionalCounts, { downloads: 1, hidden: true });
  record("professional_pdf_capture_does_not_open_a_new_tab_or_click_delete");
  assert.equal(
    (
      await run(
        tabId,
        work("verify_account", { expected_account_sha256: "0".repeat(64) }),
      )
    ).reason,
    "provider_account_identity_unverified",
  );
  record("professional_wrong_account_never_uses_different_contact_input");
  await close(tabId);

  if (!process.env.NAUKRI_PROFILE_ONLY) {
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
    for (const variant of [
      "follow_checked",
      "follow_unchecked",
      "follow_unknown",
      "follow_stuck",
      "follow_changed",
      "follow_injected_choice",
    ]) {
      mode = variant;
      tabId = await create(jobUrl);
      const inspected = await run(tabId, work("inspect_application"));
      if (variant === "follow_unknown") {
        assert.equal(
          inspected.reason,
          "direct_apply_has_additional_side_effects_or_form",
        );
      } else {
        assert.equal(
          inspected.execution?.state,
          "NOT_APPLIED",
          JSON.stringify(inspected),
        );
        if (variant === "follow_changed")
          await worker.evaluate(
            async (id) =>
              chrome.scripting.executeScript({
                target: { tabId: id },
                func: () =>
                  document
                    .querySelector("[role=checkbox]")
                    .setAttribute("aria-checked", "false"),
              }),
            tabId,
          );
        const attempt = work("apply", {
          document_id: inspected.execution.document_id,
          control_sha256: inspected.execution.control_sha256,
          permit_expires_at: new Date(Date.now() + 1500).toISOString(),
        });
        const result = await run(tabId, attempt);
        if (variant === "follow_changed")
          assert.equal(result.reason, "provider_apply_control_changed");
        else if (variant === "follow_stuck")
          assert.equal(result.reason, "company_follow_opt_out_unconfirmed");
        else if (variant === "follow_injected_choice")
          assert.equal(
            result.reason,
            "direct_apply_has_additional_side_effects_or_form",
          );
        else
          assert.equal(
            result.execution?.state,
            "CLICKED",
            JSON.stringify(result),
          );
        if (variant !== "follow_changed")
          assert.equal(
            (await run(tabId, attempt)).reason,
            "single_use_document_admission_required",
          );
      }
      const counts = await worker.evaluate(
        async (id) =>
          (
            await chrome.scripting.executeScript({
              target: { tabId: id },
              world: "MAIN",
              func: () => ({
                apply: window.fixtureClicks || 0,
                follow: window.followClicks || 0,
                followAtApply: window.followAtApply,
              }),
            })
          )[0].result,
        tabId,
      );
      const successful = ["follow_checked", "follow_unchecked"].includes(
        variant,
      );
      assert.equal(counts.apply, successful ? 1 : 0, variant);
      assert.equal(
        counts.follow,
        ["follow_checked", "follow_stuck", "follow_injected_choice"].includes(
          variant,
        )
          ? 1
          : 0,
        variant,
      );
      if (successful) assert.equal(counts.followAtApply, "false", variant);
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
  }
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
    engine: process.env.AUTOMATED_APPLY_TEST_BROWSER || "brave",
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
