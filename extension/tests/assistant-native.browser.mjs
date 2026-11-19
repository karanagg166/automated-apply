import {
  fixtureExecutable,
  copyNativeFixtureExtension,
  nativeFixtureRegistry,
} from "./browser-fixture-engine.mjs";
// Isolated real MV3 worker -> real Python native host -> fictional HTTP backend.
// Backend database/state contracts are tested separately; this does not claim DB E2E.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, writeFile, readFile, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const root = resolve(new URL("../../", import.meta.url).pathname);
const python = process.env.PYTHON;
if (!python?.startsWith("/"))
  throw Error("absolute_existing_test_python_required");
const extensionId = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const app = "11111111-1111-4111-8111-111111111111",
  taskId = "22222222-2222-4222-8222-222222222222";
const url = "https://jobs.lever.co/fictional-owner/fictional-posting/apply";
const requests = [],
  receipts = [];
let plan,
  task,
  browserContext,
  posts = 0;
const server = createServer(async (req, res) => {
  try {
    assert.equal(
      req.headers.authorization,
      "Bearer fictional-phase52-protocol-token",
    );
    assert.equal(req.headers["x-agent-client"], extensionId);
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const command = JSON.parse(raw);
    requests.push(command.command);
    let data = { submitted: false };
    if (
      ["connect_chrome_profile", "heartbeat_chrome_profile"].includes(
        command.command,
      )
    ) {
      data.profile = {
        id: command.profile_binding_id,
        label: "Fictional profile",
        version: 1,
        connected: true,
        selected: true,
        status: "CONNECTED",
        last_heartbeat: new Date().toISOString(),
        browser_session_id: command.browser_session_id,
        commands_enabled: false,
      };
    } else if (command.command === "get_agent_capabilities")
      data = { submissions: false };
    else if (command.command === "open_application_task") {
      task ||= {
        id: taskId,
        application_id: app,
        job_id: app,
        version: 1,
        company_name: "Fictional Employer",
        job_title: "Fictional Engineer",
        packet_revision: 1,
        profile_version: 1,
        profile_binding_id: command.profile_binding_id,
        target_url: url,
        current_url: url,
        browser_session_id: command.browser_session_id,
        tab_id: null,
        state: "PACKET_READY",
        challenge_state: "NONE",
      };
      if (task.browser_session_id !== command.browser_session_id)
        throw Error("extension_task_recovery_required");
      data.task = task;
    } else if (command.command === "get_application_task") data.task = task;
    else if (command.command === "update_application_task") {
      assert.equal(command.expected_task_version, task.version);
      task.version++;
      if (["guard_installed", "guard_released"].includes(command.task_event)) {
        task.network_guard_active = command.task_event === "guard_installed";
      } else if (command.task_event === "bind") {
        task.tab_id = command.tab_id;
        task.window_id = command.window_id;
        task.state = "PACKET_READY";
      } else if (command.task_event === "recover") {
        task.tab_id = null;
        task.browser_session_id = command.browser_session_id;
        task.state = "PAUSED";
      } else if (command.task_event === "tab_closed") {
        task.tab_id = null;
        task.state = "PAUSED";
      } else if (command.task_event === "resume") task.state = "PACKET_READY";
      else if (command.task_event === "cancel") task.state = "FAILED_FINAL";
      else task.state = "PAUSED";
      data.task = task;
    } else if (command.command === "inspect_form") {
      assert.equal(command.task_id, taskId);
      assert.equal(command.tab_id, task.tab_id);
      assert.equal(command.inspection.url, url);
      plan = {
        id: crypto.randomUUID(),
        application_id: app,
        job_id: app,
        target_url: url,
        mode: "manual_extension",
        packet_revision: 1,
        context_digest: "fixture",
        project_digest: "fixture",
        inspection: command.inspection,
        approved_fields: [],
        expires_at: "2099-01-01T00:00:00Z",
        state: "preview",
        actions: command.inspection.fields
          .filter((f) => f.label === "Email")
          .map((f) => ({
            field_id: f.field_id,
            kind: f.kind,
            value: "fictional@example.test",
            evidence: ["candidate_profile:fictional"],
            needs_input: false,
            preview_only: false,
            candidate_version: 1,
            job_id: app,
            application_id: app,
            target_url: url,
          })),
      };
      task.plan_id = plan.id;
      task.state = "FORM_INSPECTED";
      task.version++;
      data = { ...data, plan, task };
    } else if (command.command === "authorize_form") {
      assert.equal(command.expected_task_version, task.version);
      assert.equal(command.plan_id, plan.id);
      plan = { ...plan, approved_fields: command.field_ids, state: "consumed" };
      task.state = "FILLING";
      task.version++;
      data = { ...data, plan, task };
    } else if (command.command === "record_form_fill") {
      assert.equal(command.expected_task_version, task.version);
      assert.equal(command.receipt.plan_id, plan.id);
      receipts.push(command.receipt);
      task.state = "FILLED_VERIFIED";
      task.version++;
      data.task = task;
    } else throw Error("unexpected_command");
    res.writeHead(200, { "content-type": "application/json" });
    res.end(
      JSON.stringify({
        version: 1,
        request_id: command.request_id,
        ok: true,
        capability: "form_fill",
        data,
      }),
    );
  } catch (e) {
    res.writeHead(500);
    res.end(JSON.stringify({ error: e.message }));
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const temp = await mkdtemp(join(tmpdir(), "automated-apply-phase52-native-"));
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
try {
  const extension = join(temp, "extension");
  const nativeHost = copyNativeFixtureExtension(
    join(root, "extension/dist"),
    extension,
  );
  const manifest = JSON.parse(
    await readFile(join(extension, "manifest.json"), "utf8"),
  );
  // Test copy only; fictional origin requests are all intercepted, production manifest unchanged.
  manifest.host_permissions = ["https://jobs.lever.co/*"];
  await writeFile(join(extension, "manifest.json"), JSON.stringify(manifest));
  const config = join(temp, "test.private.env"),
    wrapper = join(temp, "native-host"),
    profile = join(temp, "profile");
  await writeFile(
    config,
    [
      "ENVIRONMENT=testing",
      "DATABASE_URL=sqlite+aiosqlite:///:memory:",
      "DATABASE_SCHEMA=job_agent",
      "SECRET_KEY=fictional-phase52-native-secret",
      "JOB_AGENT_API_TOKEN=fictional-phase52-protocol-token",
      `LOCAL_AGENT_ENDPOINT=http://127.0.0.1:${server.address().port}`,
      "CHROME_NATIVE_MESSAGING_ENABLED=true",
      `CHROME_EXTENSION_ID=${extensionId}`,
      "APPLICATION_SUBMISSION_ENABLED=false",
      "GMAIL_SENDING_ENABLED=false",
      "AUTOMATION_EXECUTION_ENABLED=false",
    ].join("\n") + "\n",
    { mode: 0o600 },
  );
  await writeFile(
    wrapper,
    `#!/bin/sh\ncd ${quote(root)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(config)} "$@"\n`,
    { mode: 0o700 },
  );
  const registry = nativeFixtureRegistry(profile);
  await mkdir(registry.directory, {
    recursive: true,
    mode: 0o700,
  });
  await writeFile(
    join(registry.directory, `${nativeHost}.json`),
    JSON.stringify({
      name: nativeHost,
      description: "Fictional Phase52 isolated native acceptance",
      type: "stdio",
      path: wrapper,
      allowed_origins: [`chrome-extension://${extensionId}/`],
    }),
    { mode: 0o600 },
  );
  async function launch() {
    browserContext = await chromium.launchPersistentContext(profile, {
      executablePath: fixtureExecutable(chromium),
      env: registry.env,
      headless: true,
      args: [
        `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`,
        "--host-resolver-rules=MAP jobs.lever.co ~NOTFOUND",
      ],
    });
    await browserContext.route("https://jobs.lever.co/**", (route) => {
      if (route.request().method() !== "GET") posts++;
      return route.fulfill({
        contentType: "text/html",
        body: `<!doctype html><title>Fictional Engineer</title><h1>Fictional Employer</h1><form onsubmit="event.preventDefault();window.submits++"><label>Email<input id="email" type="email" required></label><label>Portfolio<input value="owner-entered-preserved"></label><button type="submit">Submit</button></form><script>window.submits=0;window.retained='';document.querySelector('#email').addEventListener('input',e=>{window.retained=e.target.value;});</script>`,
      });
    });
    const settingsPage = await browserContext.newPage();
    await settingsPage.goto(`chrome-extension://${extensionId}/settings.html`);
    assert.equal(
      await settingsPage.locator("#version").innerText(),
      `Version: ${manifest.version}`,
    );
    await settingsPage.waitForFunction(() =>
      document
        .querySelector("#guard-permission")
        .textContent.includes("permission: granted"),
    );
    if (
      !(await settingsPage.evaluate(
        async () =>
          (await chrome.storage.local.get("connectedChromeProfileV1"))
            .connectedChromeProfileV1?.connected,
      ))
    ) {
      await settingsPage.locator("#profile-label").fill("Fictional profile");
      await settingsPage.locator("#profile-connect").click();
      await settingsPage.waitForFunction(() =>
        document
          .querySelector("#profile-status")
          .textContent.includes("selected"),
      );
    }
    await settingsPage.close();
    const popup = await browserContext.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    return popup;
  }
  let popup = await launch();
  const send = (action, extra = {}) =>
    popup.evaluate(
      async ({ action, extra }) =>
        await chrome.runtime.sendMessage({
          command: "application_assistant",
          action,
          ...extra,
        }),
      { action, extra },
    );
  const createdApplication = browserContext.waitForEvent("page");
  let opened = await send("open", { application_id: app });
  assert.equal(opened.ok, true, JSON.stringify(opened));
  let application = await createdApplication;
  await application.waitForLoadState().catch(() => {});
  // Extension-created tab initial navigation precedes Playwright target routing.
  // DNS is blocked above; navigate again once the fictional route is attached.
  try {
    await application.goto(url, { waitUntil: "domcontentloaded" });
  } catch (error) {
    // tabs.create can commit its initial navigation after Playwright attaches.
    // Retry fixture setup only for that exact competing navigation; all DOM,
    // authorization and receipt assertions below still have to pass.
    if (!/interrupted by another navigation/.test(error.message)) throw error;
    await application.waitForLoadState("domcontentloaded").catch(() => {});
    await application.goto(url, { waitUntil: "domcontentloaded" });
  }
  await application.locator("#email").waitFor();
  await send("resume", { task_id: taskId });
  const prepared = await send("prepare", {
    task_id: taskId,
    interactions_allowed: true,
  });
  assert.equal(prepared.ok, true, JSON.stringify(prepared));
  assert.equal(prepared.plan.actions.length, 1);
  const filled = await send("fill", {
    task_id: taskId,
    interaction_authorized: true,
    field_ids: prepared.plan.actions.map((action) => action.field_id),
  });
  assert.equal(filled.ok, true, JSON.stringify(filled));
  assert.equal(filled.result.results[0].status, "filled");
  assert.equal(filled.result.verification, "retained_after_blur");
  assert.equal(
    await application.locator("#email").inputValue(),
    "fictional@example.test",
  );
  assert.equal(
    await application.evaluate(() => window.retained),
    "fictional@example.test",
  );
  assert.equal(
    await application.locator("input").nth(1).inputValue(),
    "owner-entered-preserved",
  );
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].verification_method, "retained_after_blur");
  assert.equal(JSON.stringify(receipts).includes("fictional@example"), false);
  const duplicate = await send("fill", {
    task_id: taskId,
    interaction_authorized: true,
  });
  assert.equal(duplicate.ok, false);
  assert.equal(receipts.length, 1);
  const unrelated = await browserContext.newPage();
  await unrelated.goto("about:blank");
  await unrelated.bringToFront();
  const focusDeadline = Date.now() + 10000;
  while (task.state !== "PAUSED" && Date.now() < focusDeadline)
    await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(task.state, "PAUSED");
  await unrelated.close();
  await application.bringToFront();
  await send("resume", { task_id: taskId });
  // Persisted pending binding survives a genuine Chrome close/relaunch. No auto replay.
  await browserContext.close();
  popup = await launch();
  const listing = await send("list");
  assert.equal(listing.tasks.length, 1);
  const blocked = await send("fill", {
    task_id: taskId,
    interaction_authorized: true,
  });
  assert.equal(blocked.ok, false);
  assert.equal(receipts.length, 1);
  const reopened = await send("open", { application_id: app });
  assert.equal(reopened.ok, true, JSON.stringify(reopened));
  assert.notEqual(task.browser_session_id, prepared.task.browser_session_id);
  const cancelled = await send("cancel", { task_id: taskId });
  assert.equal(cancelled.ok, true);
  assert.equal(task.state, "FAILED_FINAL");
  assert.equal(posts, 0);
  console.log(
    JSON.stringify({
      cases: 7,
      scope:
        "real isolated Chromium/MV3/Python native host; fictional HTTP backend",
      receipt_count: receipts.length,
      employer_write_requests: posts,
      submissions: 0,
    }),
  );
} finally {
  await browserContext?.close();
  await new Promise((resolve) => server.close(resolve));
  await rm(temp, { recursive: true, force: true });
}
