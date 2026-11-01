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
import { executeNaukriSkills } from './naukri-profile-skills.js';
globalThis.skills = async (tabId, work) => (await chrome.scripting.executeScript({target:{tabId,frameIds:[0]},world:'ISOLATED',func:executeNaukriSkills,args:[work]}))[0].result;
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
let capacity = 13,
  ignoreBlur = false,
  persisted = ["Python", "Existing skill"],
  saves = 0;
const evidence = [];
try {
  await context.route("**/*", async (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== "https://www.naukri.com") {
      unexpectedRequests++;
      return route.abort();
    }
    fixtureRequests++;
    if (u.pathname === "/fixture-skills-save") {
      saves++;
      persisted = JSON.parse(route.request().postData());
      return route.fulfill({ body: "fixture saved" });
    }
    return route.fulfill({
      contentType: "text/html",
      body: `
<header><span class="email">alex@example.com</span></header>
<div id="lazyKeySkills"><div class="card"><div class="widgetHead"><span class="widgetTitle">Key skills</span><span role="button" aria-label="Edit key skills">Edit</span></div><div class="widgetCont"><div class="prefill">${persisted.map((x) => `<span class="chip">${x}</span>`).join("")}</div></div></div></div>
<script>
window.keyboardEvents=0;window.inputFocusEvents=0;window.remaining=${capacity};window.before=${JSON.stringify(persisted)};
document.addEventListener('keydown',()=>window.keyboardEvents++);document.addEventListener('keyup',()=>window.keyboardEvents++);
document.querySelector('[aria-label="Edit key skills"]').onclick=()=>{
 history.pushState(null,'','?action=modalOpen');
 const modal=document.createElement('div');modal.className='keySkillsEdit lightbox model_open';
 modal.innerHTML='<form name="keySkillsForm"><div class="keySkillSuggCont"><div class="chipsContainer"></div><input id="keySkillSugg" type="text" role="combobox" aria-label="Add skills"></div><input id="chipsVal" type="hidden"><span id="chipsVal_err"></span><button type="button" id="saveKeySkills">Save</button></form>';
 document.body.append(modal);const form=modal.querySelector('form'),input=form.querySelector('#keySkillSugg'),hidden=form.querySelector('#chipsVal');input.maxLength=window.remaining;
 const chip=value=>{const div=document.createElement('div');div.className='chip';const label=document.createElement('span');label.className='tagTxt';label.textContent=value;div.append(label);form.querySelector('.chipsContainer').append(div);};window.before.forEach(chip);hidden.value=window.before.join(',');
 input.onfocus=()=>window.inputFocusEvents++;
 input.onblur=()=>{const value=input.value;if(!value||${ignoreBlur})return;input.value='';setTimeout(()=>{chip(value);window.remaining-=value.length+1;input.maxLength=Math.max(0,window.remaining);hidden.value+=" ,"+value;},300);};
 form.querySelector('#saveKeySkills').onclick=()=>{setTimeout(()=>{const final=[...form.querySelectorAll('.tagTxt')].map(x=>x.textContent);fetch('/fixture-skills-save',{method:'POST',body:JSON.stringify(final)});},400);};
};
</script>`,
    });
  });
  context.on("page", (p) => p.on("filechooser", () => chooserEvents++));
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker", {
      predicate: (w) => w.url().endsWith("/fixture.js"),
    }));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.create || !globalThis.skills; i++) {
      if (i >= 100) throw Error("fixture_module_startup_timeout");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const selected = await worker.evaluate(() =>
    chrome.tabs.query({ active: true }),
  );
  const create = () =>
    worker.evaluate((url) => globalThis.create(url), profileUrl);
  const close = (id) => worker.evaluate((id) => chrome.tabs.remove(id), id);
  const main = (id, work) =>
    worker.evaluate(({ id, work }) => globalThis.run(id, work), { id, work });
  const invoke = (id, work) =>
    worker.evaluate(({ id, work }) => globalThis.skills(id, work), {
      id,
      work,
    });
  const inspectWork = {
    id: "fixture-skill-work",
    operation: "inspect_profile_sync",
    target_url: profileUrl,
    url: profileUrl,
    requisition: null,
    lease_until: new Date(Date.now() + 180000).toISOString(),
    execution: { expected_account_sha256: accountHash },
  };
  const ready = async () => {
    const id = await create();
    const observed = await main(id, inspectWork);
    assert.equal(
      observed.execution?.state,
      "PROFILE_OBSERVED",
      JSON.stringify(observed),
    );
    const work = {
      ...inspectWork,
      operation: "sync_profile",
      execution: {
        ...inspectWork.execution,
        document_id: observed.execution.document_id,
        sync_field: "skills",
        sync_phase: "prepare",
        skills_before: [...persisted],
        skills_additions: ["FastAPI", "Very long unsupported addition", "RAG"],
      },
    };
    return { id, work };
  };
  const prepare = async (id, work) => {
    for (let tick = 0; tick < 60; tick++) {
      const r = await invoke(id, work);
      if (r.kind !== "profile_skills_prepare_pending") return r;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw Error("fixture_preparation_deadline");
  };
  const dom = async (id, fn) =>
    worker.evaluate(
      async ({ id, fn }) =>
        (
          await chrome.scripting.executeScript({
            target: { tabId: id },
            world: "MAIN",
            func: () => ({
              keys: window.keyboardEvents,
              focus: window.inputFocusEvents,
            }),
          })
        )[0].result,
      { id },
    );
  let { id, work } = await ready();
  const prepared = await prepare(id, work);
  assert.equal(
    prepared.execution?.state,
    "PROFILE_SKILLS_PREPARED",
    JSON.stringify(prepared),
  );
  assert.deepEqual(prepared.execution.profile_fields.skills, [
    "Python",
    "Existing skill",
    "FastAPI",
    "RAG",
  ]);
  assert.equal(saves, 0);
  assert.deepEqual(await dom(id), { keys: 0, focus: 0 });
  evidence.push(
    "actual_shape_blur_adds_only_fitting_verified_values_preserves_original_chips_no_save",
  );
  const saving = {
    ...work,
    execution: {
      ...work.execution,
      sync_phase: "save",
      prepared_skills: prepared.execution.profile_fields.skills,
      permit_expires_at: new Date(Date.now() - 1000).toISOString(),
    },
  };
  assert.equal(
    (await invoke(id, saving)).reason,
    "browser_action_permit_expired",
  );
  assert.equal(saves, 0);
  evidence.push("expired_permit_prevents_save");
  saving.execution.permit_expires_at = new Date(
    Date.now() + 2000,
  ).toISOString();
  assert.equal(
    (await invoke(id, saving)).execution?.state,
    "PROFILE_SAVE_ATTEMPTED",
  );
  assert.equal(
    (await invoke(id, saving)).reason,
    "profile_skills_prepared_value_changed",
  );
  for (let i = 0; saves === 0; i++) {
    assert.ok(i < 30);
    await new Promise((r) => setTimeout(r, 50));
  }
  assert.equal(saves, 1);
  await close(id);
  id = await create();
  const reread = await main(id, inspectWork);
  assert.deepEqual(reread.execution.profile_fields.skills, persisted);
  assert.notEqual(reread.execution.document_id, work.execution.document_id);
  assert.equal(
    (await invoke(id, saving)).reason,
    "profile_skills_document_or_owner_changed",
  );
  await close(id);
  evidence.push(
    "single_save_independent_fixture_reload_and_stale_document_refused",
  );
  persisted = ["Python", "Existing skill"];
  capacity = 0;
  ({ id, work } = await ready());
  assert.equal(
    (await prepare(id, work)).reason,
    "profile_skills_no_addition_within_provider_capacity",
  );
  assert.equal(saves, 1);
  await close(id);
  evidence.push("zero_capacity_preserves_existing_values_without_save");
  capacity = 13;
  ({ id, work } = await ready());
  work.execution.skills_before = ["Python"];
  assert.equal(
    (await invoke(id, work)).reason,
    "profile_skills_preimage_or_editor_changed",
  );
  await close(id);
  evidence.push("changed_preimage_refused_before_editor");
  ({ id, work } = await ready());
  work.execution.expected_account_sha256 = "0".repeat(64);
  assert.equal(
    (await invoke(id, work)).reason,
    "provider_account_identity_unverified",
  );
  await close(id);
  evidence.push("wrong_account_never_opens_or_saves");
  ignoreBlur = true;
  ({ id, work } = await ready());
  assert.equal(
    (await prepare(id, work)).reason,
    "profile_skills_addition_unconfirmed_no_save",
  );
  assert.equal(saves, 1);
  await close(id);
  evidence.push("unconfirmed_blur_is_not_repeated_and_cannot_save");
  const final = await worker.evaluate(() =>
    chrome.tabs.query({ active: true }),
  );
  assert.deepEqual(
    final.map((t) => [t.windowId, t.id]),
    selected.map((t) => [t.windowId, t.id]),
  );
  assert.equal(unexpectedRequests, 0);
  assert.equal(chooserEvents, 0);
  const result = {
    fixture_only: true,
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - started),
    fixtureRequests,
    unexpectedRequests,
    chooserEvents,
    owner_selection_unchanged: true,
    evidence,
  };
  if (process.argv[2] === "--report")
    writeFileSync(process.argv[3], JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
  child.kill();
}
