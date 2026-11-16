import { fixtureExecutable } from "./browser-fixture-engine.mjs";
// Isolated actual Chromium, fictional pages/PDF only. No running Chrome profile.
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { chooserFreeUploadProbe } from "./support/chooser-free-upload.js";

const origin = "http://127.0.0.1:17351";
const started = performance.now();
const args = process.argv.slice(2);
if (args.length && (args.length !== 2 || args[0] !== "--report"))
  throw Error(
    "usage: node tests/naukri-upload-probe.browser.mjs [--report FILE]",
  );
const pdf = Buffer.from("%PDF-1.4\nFictional canonical resume only\n%%EOF");
const hash = createHash("sha256").update(pdf).digest("hex");
const resume = {
  type: "application/pdf",
  base64: pdf.toString("base64"),
  sha256: hash,
};
let browser;
let context;
let externalRequests = 0;
let chooserEvents = 0;
let cases = 0;
const evidence = [];
async function launch() {
  browser = await chromium.launch({
    executablePath: fixtureExecutable(chromium),
    headless: true,
  });
  context = await browser.newContext();
  await context.route("**/*", (route) => {
    if (new URL(route.request().url()).origin !== origin) {
      externalRequests++;
      return route.abort();
    }
    return route.fulfill({ contentType: "text/html", body: html });
  });
}
const html = `<!doctype html><meta name="fictional-upload-probe" content="true">
<main data-requisition="291026123456" data-employer="Fictional employer">
<div role="dialog" aria-label="Application questions"><button type="button">Upload Resume</button>
<input type="file" accept=".pdf" hidden><span role="status"></span><span role="alert"></span></div></main>
<script>
window.probe = {initializations:0, changes:0, retained:0, simulatedSubmissions:0, initialized:false, variant:'normal'};
const scope=document.querySelector('[role="dialog"]');
probe.variant=new URL(location.href).searchParams.get('variant') || 'normal';
if(probe.variant==='nested') {
 const wrapper=document.createElement('section');
 for(const child of [...scope.children]) wrapper.append(child);
 scope.append(wrapper);
}
if(probe.variant==='ambiguous') scope.append(scope.querySelector('input').cloneNode());
function listen(input) {
 input.addEventListener('change', (event) => {
  probe.changes++;
  if(!probe.initialized || probe.variant==='failure' ||
     (probe.variant==='trusted_event_required' && !event.isTrusted)) {
   scope.querySelector('[role="alert"]').textContent='File upload was unsuccessful. Please try again.';
   return;
  }
  if(probe.variant==='navigation_after_selection') {history.pushState({},'', '/other-job');return;}
  if(probe.variant==='unconfirmed') return;
  probe.retained++;
  if(probe.variant==='immediate_submission') probe.simulatedSubmissions++;
  scope.querySelector('[role="status"]').textContent='Resume retained';
 });
}
listen(scope.querySelector('input'));
if(probe.variant==='dynamic') scope.querySelector('input').remove();
scope.querySelector('button').addEventListener('click', () => {
 probe.initializations++;
 probe.initialized=true;
 if(probe.variant==='async_initialization') {
  probe.initialized=false;setTimeout(()=>probe.initialized=true,50);
 }
 if(probe.variant==='dynamic') {
  const input=document.createElement('input');input.type='file';input.hidden=true;scope.append(input);listen(input);
 }
 if(probe.variant==='navigation_after_init') {history.pushState({},'', '/other-job');return;}
 scope.querySelector('input').click();
});
</script>`;
async function fixture(variant = "normal") {
  const page = await context.newPage();
  page.on("filechooser", () => chooserEvents++);
  // Playwright page.evaluate grants user activation. Set up the page through
  // its ordinary initial script so the probe actually models an unattended tab.
  await page.goto(origin + "/job/291026123456?variant=" + variant);
  const cdp = await context.newCDPSession(page);
  const { frameTree } = await cdp.send("Page.getFrameTree");
  const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
    frameId: frameTree.frame.id,
    worldName: "fictional-chooser-free-upload",
  });
  const binding = {
    profile: randomUUID(),
    window: 1,
    tab: 1,
    session: randomUUID(),
    document: randomUUID(),
    requisition: "291026123456",
    employer: "Fictional employer",
    resumeRevision: "fixture-r1",
    resumeSha256: hash,
    url: page.url(),
  };
  await cdp.send("Runtime.callFunctionOn", {
    executionContextId,
    functionDeclaration:
      "function(binding){globalThis.__fictionalUploadBinding=binding}",
    arguments: [{ value: binding }],
    userGesture: false,
  });
  async function run(overrides = {}) {
    const reply = await cdp.send("Runtime.callFunctionOn", {
      executionContextId,
      functionDeclaration: chooserFreeUploadProbe.toString(),
      arguments: [{ value: { binding, resume, ...overrides } }],
      awaitPromise: true,
      returnByValue: true,
      userGesture: false,
    });
    assert.equal(reply.exceptionDetails, undefined);
    return reply.result.value;
  }
  return { page, run, binding };
}
async function checked(name, work) {
  await work();
  cases++;
  evidence.push(name);
}
try {
  await launch();
  await checked(
    "missing_initialization_reproduces_upload_failure",
    async () => {
      const f = await fixture();
      await f.page.evaluate(({ base64 }) => {
        const transfer = new DataTransfer();
        transfer.items.add(
          new File(
            [Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))],
            "resume.pdf",
            { type: "application/pdf" },
          ),
        );
        const input = document.querySelector("input");
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }, resume);
      assert.match(
        await f.page.locator('[role="alert"]').textContent(),
        /unsuccessful/,
      );
      assert.equal((await f.page.evaluate("probe")).retained, 0);
      await f.page.close();
    },
  );
  for (const variant of ["normal", "nested", "dynamic"]) {
    await checked(
      "initialization_then_chooser_free_selection_" + variant,
      async () => {
        const f = await fixture(variant);
        const result = await f.run();
        assert.equal(result.state, "VERIFYING");
        assert.equal(result.bytes, pdf.length);
        assert.equal(result.application_recorded, false);
        assert.equal((await f.page.evaluate("probe")).initializations, 1);
        const bytes = await f.page
          .locator('input[type="file"]')
          .evaluate(async (input) => [
            ...new Uint8Array(await input.files[0].arrayBuffer()),
          ]);
        assert.equal(
          createHash("sha256").update(Buffer.from(bytes)).digest("hex"),
          hash,
        );
        assert.equal((await f.run()).reason, "attempt_already_consumed");
        assert.equal((await f.page.evaluate("probe")).changes, 1);
        await f.page.close();
      },
    );
  }
  await checked(
    "active_user_gesture_cannot_open_a_native_chooser",
    async () => {
      const f = await fixture();
      await f.page.evaluate(() => true); // Deliberately model recent user activation.
      assert.equal(
        (await f.run()).reason,
        "native_chooser_risk_from_user_activation",
      );
      assert.equal(await f.page.evaluate("probe.initializations"), 0);
      await f.page.close();
    },
  );
  await checked("missing_fixture_marker_is_never_admitted", async () => {
    const f = await fixture();
    await f.page.evaluate(() =>
      document.querySelector('meta[name="fictional-upload-probe"]').remove(),
    );
    assert.equal((await f.run()).reason, "fixture_only");
    assert.equal(await f.page.evaluate("probe.initializations"), 0);
    await f.page.close();
  });
  await checked("existing_attachment_is_never_overwritten", async () => {
    const f = await fixture();
    await f.page.evaluate(() => {
      const files = new DataTransfer();
      files.items.add(new File(["owner fixture"], "existing.pdf"));
      document.querySelector("input").files = files.files;
    });
    assert.equal((await f.run()).reason, "existing_or_ambiguous_attachment");
    assert.equal(
      await f.page.locator("input").evaluate((el) => el.files[0].name),
      "existing.pdf",
    );
    assert.equal(await f.page.evaluate("probe.changes"), 0);
    await f.page.close();
  });
  await checked(
    "ambiguous_initialization_controls_are_never_clicked",
    async () => {
      const f = await fixture();
      await f.page.evaluate(() => {
        const scope = document.querySelector('[role="dialog"]');
        scope.append(scope.querySelector("button").cloneNode(true));
      });
      assert.equal((await f.run()).reason, "upload_control_ambiguous");
      assert.equal(await f.page.evaluate("probe.initializations"), 0);
      await f.page.close();
    },
  );
  await checked(
    "document_reload_invalidates_the_old_execution_context",
    async () => {
      const f = await fixture();
      await f.page.reload();
      await assert.rejects(f.run, /context|destroyed/i);
      assert.equal(await f.page.evaluate("probe.changes"), 0);
      await f.page.close();
    },
  );
  for (const [name, overrides, reason] of [
    [
      "wrong_revision",
      (f) => ({ binding: { ...f.binding, resumeRevision: "fixture-r2" } }),
      "binding_changed",
    ],
    [
      "wrong_employer",
      (f) => ({ binding: { ...f.binding, employer: "Different employer" } }),
      "binding_changed",
    ],
    [
      "wrong_tab",
      (f) => ({ binding: { ...f.binding, tab: 2 } }),
      "binding_changed",
    ],
    [
      "wrong_session",
      (f) => ({ binding: { ...f.binding, session: randomUUID() } }),
      "binding_changed",
    ],
    [
      "wrong_type",
      () => ({ resume: { ...resume, type: "text/plain" } }),
      "pdf_type_required",
    ],
    [
      "wrong_digest",
      () => ({ resume: { ...resume, sha256: "0".repeat(64) } }),
      "canonical_pdf_changed",
    ],
    [
      "wrong_header",
      () => ({
        resume: {
          ...resume,
          base64: Buffer.from("not a PDF").toString("base64"),
        },
      }),
      "pdf_header_invalid",
    ],
    [
      "too_large",
      () => ({
        resume: {
          ...resume,
          base64: Buffer.alloc(2 * 1024 * 1024 + 1).toString("base64"),
        },
      }),
      "pdf_size_invalid",
    ],
  ]) {
    await checked("reject_before_initialization_" + name, async () => {
      const f = await fixture();
      assert.equal((await f.run(overrides(f))).reason, reason);
      assert.equal((await f.page.evaluate("probe")).initializations, 0);
      await f.page.close();
    });
  }
  for (const [variant, state, reason] of [
    ["ambiguous", "NEEDS_INPUT", "existing_or_ambiguous_attachment"],
    ["failure", "NEEDS_INPUT", "upload_failed_no_automatic_retry"],
    ["async_initialization", "NEEDS_INPUT", "upload_failed_no_automatic_retry"],
    [
      "trusted_event_required",
      "NEEDS_INPUT",
      "upload_failed_no_automatic_retry",
    ],
    [
      "navigation_after_init",
      "SUBMISSION_UNKNOWN",
      "navigation_or_binding_changed_after_initialization",
    ],
    [
      "navigation_after_selection",
      "SUBMISSION_UNKNOWN",
      "navigation_or_binding_changed_after_selection",
    ],
    ["unconfirmed", "SUBMISSION_UNKNOWN", "attachment_outcome_unconfirmed"],
  ]) {
    await checked("safe_outcome_" + variant, async () => {
      const f = await fixture(variant);
      const result = await f.run();
      assert.equal(result.state, state);
      assert.equal(result.reason, reason);
      assert.equal(result.application_recorded, false);
      if (variant !== "ambiguous") {
        const prior = await f.page.evaluate("probe.changes");
        assert.notEqual((await f.run()).state, "VERIFYING");
        assert.equal(await f.page.evaluate("probe.changes"), prior);
      }
      await f.page.close();
    });
  }
  await checked(
    "file_change_can_submit_without_becoming_a_provider_receipt",
    async () => {
      const f = await fixture("immediate_submission");
      assert.equal((await f.run()).state, "VERIFYING");
      assert.equal(await f.page.evaluate("probe.simulatedSubmissions"), 1);
      assert.equal((await f.run()).reason, "attempt_already_consumed");
      assert.equal(await f.page.evaluate("probe.simulatedSubmissions"), 1);
      await f.page.close();
    },
  );
  await checked("fresh_browser_rejects_prior_session_binding", async () => {
    const old = await fixture();
    const oldBinding = old.binding;
    await browser.close();
    await launch();
    const fresh = await fixture();
    assert.equal(
      (await fresh.run({ binding: oldBinding })).reason,
      "binding_changed",
    );
    assert.equal(await fresh.page.evaluate("probe.changes"), 0);
    await fresh.page.close();
  });
  assert.equal(externalRequests, 0);
  assert.equal(chooserEvents, 0);
  const report = {
    cases,
    passed: cases,
    failed: 0,
    evidence,
    browser: await browser.version(),
    native_chooser_events: chooserEvents,
    external_requests: externalRequests,
    real_naukri_requests: 0,
    real_applications: 0,
    installed_worker_test: false,
    locked_desktop_test: "NOT_TESTED",
    conclusion: "standard_browser_candidate_only_not_Naukri_acceptance",
    seconds: Number(((performance.now() - started) / 1000).toFixed(3)),
    fictional_pdf_bytes: pdf.length,
    script_sha256: createHash("sha256")
      .update(readFileSync(new URL(import.meta.url)))
      .digest("hex"),
    helper_sha256: createHash("sha256")
      .update(
        readFileSync(
          new URL("./support/chooser-free-upload.js", import.meta.url),
        ),
      )
      .digest("hex"),
  };
  const output = JSON.stringify(report, null, 2) + "\n";
  if (args.length) writeFileSync(args[1], output, { flag: "wx", mode: 0o600 });
  console.log(output);
} finally {
  await browser?.close();
}
