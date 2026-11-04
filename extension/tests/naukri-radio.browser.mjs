// Focused isolated Chromium radio interactions. Every provider response is a
// fictional fixture; no owner browser, live vacancy, keyboard or chooser.
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
const root = mkdtempSync(join(tmpdir(), "automated-apply-radio-fixture-"));
cpSync(
  new URL("../naukri-chatbot.js", import.meta.url),
  join(root, "naukri-chatbot.js"),
);
writeFileSync(
  join(root, "manifest.json"),
  JSON.stringify({
    manifest_version: 3,
    version: "0.0.1",
    name: "Fictional radio acceptance",
    permissions: ["scripting"],
    host_permissions: ["https://www.naukri.com/*"],
    background: { service_worker: "fixture.js", type: "module" },
  }),
);
writeFileSync(
  join(root, "fixture.js"),
  `import {naukriChatbot} from './naukri-chatbot.js';globalThis.chat=async(id,request)=>(await chrome.scripting.executeScript({target:{tabId:id,frameIds:[0]},world:'ISOLATED',func:naukriChatbot,args:[request]}))[0].result;`,
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
let browser;
let unexpected = 0,
  choosers = 0;
const evidence = [];
try {
  const endpoint = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(endpoint); i++) {
    if (i >= 100 || child.exitCode !== null)
      throw Error("isolated_browser_start_timeout");
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.connectOverCDP(
    `http://127.0.0.1:${readFileSync(endpoint, "utf8").split("\n")[0]}`,
    { noDefaults: true },
  );
  const context = browser.contexts()[0];
  let mode = "";
  await context.route("**/*", (route) => {
    if (new URL(route.request().url()).origin !== "https://www.naukri.com") {
      unexpected++;
      return route.abort();
    }
    const body = `<button id="outside-save" onclick="window.outsideSaves++">Save</button><div class="chatbot_DrawerContentWrapper"><div class="chatbot_MessageContainer"><div class="botItem"><div class="botMsg">Are you willing to attend in-person interview?</div></div><div class="singleselect-radiobutton"><div class="singleselect-radiobutton-container">${["Yes", "No"].map((v, i) => `<div class="ssrc__radio-btn-container"><input type="radio" id="${v}" name="radio-button" value="${v}" class="ssrc__radio" data-val="pb" data-index="${i}" ${mode === "selected" && i === 0 ? "checked" : ""}><label for="${v}" class="ssrc__label">${v}</label></div>`).join("")}</div></div></div><div class="send disabled"><span class="sendMsg">Save</span></div></div><script>
 window.radioChanges=0;window.saves=0;window.outsideSaves=0;const drawer=document.querySelector('.chatbot_DrawerContentWrapper'),send=drawer.querySelector('.send');
 drawer.querySelectorAll('input').forEach(e=>e.onchange=()=>{window.radioChanges++;const mode=${JSON.stringify(mode)};if(mode==='advance')drawer.querySelector('.botMsg').textContent='Next question?';else if(mode==='remove')drawer.remove();else if(mode==='save')send.classList.remove('disabled');else if(mode==='slow-save'){const until=performance.now()+2700;while(performance.now()<until){};send.classList.remove('disabled');}});send.onclick=()=>{window.saves++;drawer.remove()};
 ${mode === "duplicate" ? "drawer.querySelector('.chatbot_MessageContainer').append(drawer.querySelector('.singleselect-radiobutton').cloneNode(true));" : ""}
 </script>`;
    return route.fulfill({ contentType: "text/html", body });
  });
  context.on("page", (p) => p.on("filechooser", () => choosers++));
  const owner = context.pages()[0];
  await owner.bringToFront();
  const worker =
    context.serviceWorkers().find((w) => w.url().endsWith("/fixture.js")) ||
    (await context.waitForEvent("serviceworker"));
  await worker.evaluate(async () => {
    for (let i = 0; !globalThis.chat; i++) {
      if (i >= 100) throw Error("fixture_start_timeout");
      await new Promise((r) => setTimeout(r, 20));
    }
  });
  const ownerId = await worker.evaluate(
    async () => (await chrome.tabs.query({ active: true }))[0].id,
  );
  for (mode of [
    "save",
    "advance",
    "remove",
    "selected",
    "duplicate",
    "no-save",
    "slow-save",
    "active",
  ]) {
    const url =
      "https://www.naukri.com/job-listings-fictional-radio-291026123456";
    const tab = await worker.evaluate(async (url) => {
      // Attach routing before navigation, as in the shipped queue harness.
      const tab = await chrome.tabs.create({
        url: "about:blank",
        active: false,
      });
      await new Promise((r) => setTimeout(r, 200));
      await chrome.tabs.update(tab.id, { url, active: false });
      await new Promise((r) => setTimeout(r, 100));
      return tab;
    }, url);
    try {
      for (let i = 0; i < 60; i++) {
        if (
          await worker.evaluate(
            async (id) => (await chrome.tabs.get(id)).status === "complete",
            tab.id,
          )
        )
          break;
        if (i === 59) throw Error("fixture_document_timeout");
        await new Promise((r) => setTimeout(r, 50));
      }
      if (mode === "active")
        await worker.evaluate(
          (id) => chrome.tabs.update(id, { active: true }),
          tab.id,
        );
      const request = {
        operation: "inspect",
        url,
        requisition: "291026123456",
      };
      const step = await worker.evaluate(({ id, r }) => chat(id, r), {
        id: tab.id,
        r: request,
      });
      if (["active", "duplicate"].includes(mode)) {
        assert.equal(
          step.reason,
          mode === "active"
            ? "owner_tab_active"
            : "questionnaire_radio_controls_unrecognized",
        );
      } else {
        assert.equal(step.kind, "questionnaire");
        assert.deepEqual(step.options, ["Yes", "No"]);
        const answer = {
          ...request,
          operation: "answer",
          document_id: step.document_id,
          step_sha256: step.step_sha256,
          answer: "No",
          permit_expires_at: new Date(Date.now() + 2400).toISOString(),
        };
        const result = await worker.evaluate(({ id, r }) => chat(id, r), {
          id: tab.id,
          r: answer,
        });
        if (mode === "selected")
          assert.equal(result.reason, "questionnaire_existing_value_preserved");
        else if (mode === "slow-save")
          assert.equal(result.reason, "questionnaire_action_permit_expired");
        else if (mode === "no-save")
          assert.equal(
            result.reason,
            "questionnaire_send_control_not_confirmed",
          );
        else assert.equal(result.kind, "questionnaire_answer_attempted");
        const duplicate = await worker.evaluate(({ id, r }) => chat(id, r), {
          id: tab.id,
          r: answer,
        });
        assert.notEqual(duplicate.kind, "questionnaire_answer_attempted");
      }
      const counts = await worker.evaluate(
        async (id) =>
          (
            await chrome.scripting.executeScript({
              target: { tabId: id },
              world: "MAIN",
              func: () => ({
                radio: window.radioChanges,
                save: window.saves,
                outside: window.outsideSaves,
              }),
            })
          )[0].result,
        tab.id,
      );
      assert.deepEqual(counts, {
        radio: ["active", "duplicate", "selected"].includes(mode) ? 0 : 1,
        save: mode === "save" ? 1 : 0,
        outside: 0,
      });
      evidence.push({ name: mode, result: "PASS", ...counts });
    } finally {
      await worker.evaluate((id) => chrome.tabs.remove(id), tab.id);
      await worker.evaluate(
        (id) => chrome.tabs.update(id, { active: true }),
        ownerId,
      );
    }
    assert.equal(owner.url(), "about:blank");
  }
  assert.equal(unexpected, 0);
  assert.equal(choosers, 0);
  const report = {
    fixture_only: true,
    cases: evidence.length,
    duration_ms: Math.round(performance.now() - started),
    live_naukri_requests: 0,
    unexpected_requests: unexpected,
    chooser_events: choosers,
    evidence,
  };
  if (process.argv[2] === "--report")
    writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close();
  child.kill();
}
