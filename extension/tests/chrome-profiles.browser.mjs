import { nativePostgresFixture } from "./native-postgres-fixture.mjs";
import {
  fixtureExecutable,
  fixtureNativeHost,
} from "./browser-fixture-engine.mjs";
// Explicit isolated test only: two real MV3 profiles, Python native host, FastAPI,
// disposable PostgreSQL 17. No installed Chrome profile or private env is touched.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtemp, mkdir, cp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createServer } from "node:net";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const root = resolve(new URL("../../", import.meta.url).pathname);
const python = process.env.PYTHON;
const prepareOnly = process.argv.includes("--prepare-only");
if (!python?.startsWith("/"))
  throw Error("absolute_existing_test_python_required");
const temp = await mkdtemp(join(tmpdir(), "automated-apply-profile-test-"));
const extensionId = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const url = "https://jobs.lever.co/fictional-profile/fictional-job/apply";
const token = "fictional-profile-command-test-token";
const contexts = [];
let apiProcess,
  apiLog = "",
  postgres,
  nonGet = 0;
const env = {
  PATH: process.env.PATH,
  HOME: process.env.HOME,
  TMPDIR: process.env.TMPDIR,
  LANG: "en_US.UTF-8",
  PYTHONUNBUFFERED: "1",
};
async function freePort() {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
try {
  postgres = await nativePostgresFixture(python);
  const apiPort = await freePort();
  const endpoint = `http://127.0.0.1:${apiPort}`;
  const config = join(temp, "fictional.private.env");
  const values = {
    ENVIRONMENT: "testing",
    DATABASE_URL: postgres.url.replace(
      "postgresql://",
      "postgresql+asyncpg://",
    ),
    DATABASE_SCHEMA: "job_agent",
    DB_REMOTE_ONLY: "false",
    DB_REQUIRE_TLS: "false",
    SECRET_KEY: "fictional-profile-acceptance-secret", // pragma: allowlist secret — disposable fixture only
    JOB_AGENT_API_TOKEN: token,
    LOCAL_AGENT_ENDPOINT: endpoint,
    CHROME_EXTENSION_ID: extensionId,
    CHROME_NATIVE_MESSAGING_ENABLED: "true",
    CHROME_PROFILE_COMMANDS_ENABLED: "true",
    BROWSER_FILL_ENABLED: prepareOnly ? "false" : "true",
    BROWSER_ASSISTANT_ENABLED: "true",
    BROWSER_AUTOMATION_ENABLED: "false",
    BROWSER_ALLOWED_ORIGINS: '["https://jobs.lever.co:443"]',
    TELEGRAM_OWNER_USER_ID: "11",
    TELEGRAM_OWNER_CHAT_ID: "22",
    APPLICATION_SUBMISSION_ENABLED: "false",
    BROWSER_SUBMIT_ENABLED: "false",
    GMAIL_SENDING_ENABLED: "false",
    AUTOMATION_EXECUTION_ENABLED: "false",
  };
  await writeFile(
    config,
    Object.entries(values)
      .map(([k, v]) => `${k}=${v}`)
      .join("\n") + "\n",
    { mode: 0o600 },
  );
  apiProcess = spawn(
    python,
    [
      "backend/scripts/phase52_extension_fixture.py",
      "--env-file",
      config,
      "--port",
      String(apiPort),
    ],
    { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  apiProcess.stdout.on("data", (chunk) => {
    apiLog += chunk;
  });
  apiProcess.stderr.on("data", (chunk) => {
    apiLog += chunk;
  });
  let apiReady = false;
  for (let i = 0; i < 100; i++) {
    try {
      if (
        (
          await fetch(endpoint + "/api/v1/browser/chrome-profiles", {
            headers: { Authorization: `Bearer ${token}` },
          })
        ).ok
      ) {
        apiReady = true;
        break;
      }
    } catch {}
    if (apiProcess.exitCode !== null) break;
    await delay(200);
  }
  assert.ok(apiReady, `fictional FastAPI ready: ${apiLog.slice(-3000)}`);
  async function api(path, body, expected = 200) {
    const response = await fetch(endpoint + "/api/v1/" + path, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    assert.equal(response.status, expected, JSON.stringify(result));
    return result;
  }
  assert.equal(
    (await fetch(endpoint + "/api/v1/browser/chrome-profiles")).status,
    401,
  );
  const extension = join(temp, "extension");
  await cp(join(root, "extension/dist"), extension, { recursive: true });
  const nativeHost = fixtureNativeHost(extension);
  const manifest = JSON.parse(
    await readFile(join(extension, "manifest.json"), "utf8"),
  );
  // Test copy only. Every fictional origin request is intercepted below.
  manifest.host_permissions = ["https://jobs.lever.co/*"];
  await writeFile(join(extension, "manifest.json"), JSON.stringify(manifest));
  const wrapper = join(temp, "host");
  await writeFile(
    wrapper,
    `#!/bin/sh\ncd ${quote(root)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(config)} "$@"\n`,
    { mode: 0o700 },
  );
  async function launch(name, reconnect = false) {
    const path = join(temp, name);
    await mkdir(join(path, "NativeMessagingHosts"), { recursive: true });
    await writeFile(
      join(path, `NativeMessagingHosts/${nativeHost}.json`),
      JSON.stringify({
        name: nativeHost,
        description: "Fictional isolated profile test",
        path: wrapper,
        type: "stdio",
        allowed_origins: [`chrome-extension://${extensionId}/`],
      }),
      { mode: 0o600 },
    );
    const context = await chromium.launchPersistentContext(path, {
      executablePath: fixtureExecutable(chromium),
      headless: true,
      env,
      args: [
        `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`,
        "--host-resolver-rules=MAP jobs.lever.co ~NOTFOUND",
      ],
    });
    contexts.push(context);
    await context.route("https://jobs.lever.co/**", (route) => {
      if (route.request().method() !== "GET") nonGet++;
      return route.fulfill({
        contentType: "text/html",
        body: '<!doctype html><title>Fictional profile job</title><h1>Fictional Employer</h1><form><label>Full name<input id="name" required></label><label>Email<input id="email" type="email" required></label><label>Portfolio<input id="manual" value="owner-manual"></label><button type="submit">Submit</button></form><script>window.submits=0;document.querySelector("form").addEventListener("submit",e=>{e.preventDefault();window.submits++});</script>',
      });
    });
    const page = await context.newPage();
    await page.goto(`chrome-extension://${extensionId}/settings.html`);
    if (!reconnect) {
      await page.locator("#profile-label").fill(name);
      await page.locator("#profile-connect").click();
      await page.waitForFunction(() =>
        document
          .querySelector("#profile-status")
          .textContent.includes("select in dashboard"),
      );
    }
    let worker =
      context.serviceWorkers()[0] ||
      (await context.waitForEvent("serviceworker"));
    const read = async () =>
      page.evaluate(async () => {
        const value = (
          await chrome.storage.local.get("connectedChromeProfileV1")
        ).connectedChromeProfileV1;
        return {
          id: value.id,
          sessionId: value.sessionId,
          connected: value.connected,
        };
      });
    const identity = await read();
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    return {
      popup,
      context,
      page,
      identity,
      getWorker: async () => {
        worker =
          context.serviceWorkers().find((value) => !value.isClosed?.()) ||
          (await context.waitForEvent("serviceworker"));
        return worker;
      },
    };
  }
  async function tick(profile) {
    const before = await api("browser/chrome-profiles");
    const last = before.profiles.find(
      (value) => value.id === profile.identity.id,
    )?.last_heartbeat;
    const worker = await profile.getWorker();
    await worker.evaluate(() =>
      chrome.alarms.create("connected-chrome-heartbeat", {
        when: Date.now() + 50,
        periodInMinutes: 0.5,
      }),
    );
    let observed;
    for (let i = 0; i < 240; i++) {
      observed = await api("browser/chrome-profiles");
      const current = observed.profiles.find(
        (value) => value.id === profile.identity.id,
      );
      const pending = observed.commands.some(
        (value) =>
          value.profile_binding_id === profile.identity.id &&
          ["queued", "leased", "executing"].includes(value.state),
      );
      if (current?.last_heartbeat !== last && (!current.selected || !pending))
        return;
      if (i % 10 === 9)
        await worker.evaluate(() =>
          chrome.alarms.create("connected-chrome-heartbeat", {
            when: Date.now() + 50,
            periodInMinutes: 0.5,
          }),
        );
      await delay(250);
    }
    throw Error(
      "profile_alarm_did_not_complete: " +
        JSON.stringify(observed) +
        apiLog.slice(-1500),
    );
  }
  const personal = await launch("Personal Chrome"),
    jobs = await launch("Job applications");
  assert.notEqual(personal.identity.id, jobs.identity.id);
  assert.notEqual(personal.identity.id, extensionId);
  let state = await api("browser/chrome-profiles");
  assert.equal(state.profiles.length, 2);
  assert.equal(state.selection.profile_binding_id, null);
  async function choose(profile) {
    const listing = await api("browser/chrome-profiles");
    await api("browser/chrome-profiles/select", {
      expected_version: listing.selection.version,
      profile_binding_id: profile.identity.id,
    });
  }
  await choose(prepareOnly ? jobs : personal);
  for (const profile of [personal, jobs]) {
    await profile.page.locator("#profile-commands").check();
    await profile.page.waitForFunction(async () => {
      const value = (await chrome.storage.local.get("connectedChromeProfileV1"))
        .connectedChromeProfileV1;
      return (
        value.commandsEnabled === true &&
        value.profile?.commands_enabled === true
      );
    });
  }
  for (const profile of [personal, jobs]) {
    const status = await profile.page.evaluate(
      async () =>
        await chrome.runtime.sendMessage({
          command: "chrome_profile",
          action: "status",
        }),
    );
    assert.equal(
      status.profile?.commands_enabled,
      true,
      JSON.stringify(status),
    );
  }
  const packet = await api("browser-applications", {
    application_url: url,
    company_name: "Fictional Employer",
    job_title: "Fictional Backend Engineer",
    idempotency_key: "profile-fixture-001",
  });
  async function enqueue(action, profile = personal) {
    state = await api("browser/chrome-profiles");
    const selected = state.profiles.find(
      (value) => value.id === profile.identity.id,
    );
    const task = await api(`browser/extension-tasks/application/${packet.id}`);
    const data = {
      request_id: randomUUID(),
      profile_binding_id: profile.identity.id,
      selection_version: state.selection.version,
      expected_profile_version: selected.version,
      application_id: packet.id,
      packet_revision: packet.revision,
      action,
      task_id: task?.id,
      expected_task_version: task?.version,
    };
    return {
      data,
      command: await api("browser/chrome-profiles/commands", data),
    };
  }
  state = await api("browser/chrome-profiles");
  assert.equal(state.channel_available, true, JSON.stringify(state));
  assert.equal(
    state.profiles.find((value) => value.selected).commands_enabled,
    true,
    JSON.stringify(state) + apiLog.slice(-3500),
  );
  console.log(
    "Profile fixture: authenticated connections and explicit selection passed",
  );
  if (prepareOnly) {
    const opened = await enqueue("open", jobs);
    await tick(personal);
    await tick(jobs);
    const application = jobs.context.pages().find((page) => page.url() === url);
    assert.ok(application, "selected job profile opened the exact application");
    await application.waitForLoadState("domcontentloaded");
    const bound = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.equal(bound.profile_binding_id, jobs.identity.id);
    assert.equal(bound.browser_session_id, jobs.identity.sessionId);
    assert.equal(bound.packet_revision, packet.revision);
    assert.equal(bound.current_url, url);
    assert.equal(bound.plan_id, null);
    const worker = await jobs.getWorker();
    await worker.evaluate(() => {
      globalThis.prepareScripts = [];
      const execute = chrome.scripting.executeScript.bind(chrome.scripting);
      chrome.scripting.executeScript = async (request) => {
        globalThis.prepareScripts.push({
          target: request.target,
          operation: request.args?.[0]?.operation,
        });
        return execute(request);
      };
    });
    for (const separateWindow of [false, true]) {
      const unrelatedUrl = `https://jobs.lever.co/unrelated-${separateWindow}`;
      let unrelated;
      if (separateWindow) {
        const waiting = jobs.context.waitForEvent("page");
        await jobs.page.evaluate(
          (url) =>
            chrome.windows.create({
              url,
              focused: true,
              type: "normal",
            }),
          unrelatedUrl,
        );
        unrelated = await waiting;
        await unrelated.waitForLoadState("domcontentloaded");
      } else {
        unrelated = await jobs.context.newPage();
        await unrelated.goto(unrelatedUrl);
      }
      await unrelated.bringToFront();
      // Drain focus-loss invalidation before snapshotting the command revision.
      // A command racing a control update must still fail its exact revision.
      const settled = await jobs.popup.evaluate(() =>
        chrome.runtime.sendMessage({
          command: "application_assistant",
          action: "list",
        }),
      );
      assert.ok(settled.ok, JSON.stringify(settled));
      const foreground = () =>
        jobs.page.evaluate(async () => {
          const window = await chrome.windows.getLastFocused();
          const [tab] = await chrome.tabs.query({
            active: true,
            windowId: window.id,
          });
          return { id: tab.id, windowId: tab.windowId, url: tab.url };
        });
      const before = await foreground();
      assert.equal(before.url, unrelatedUrl);
      assert.notEqual(before.id, bound.tab_id);
      assert.equal(before.windowId === bound.window_id, !separateWindow);
      const queued = await enqueue("prepare", jobs);
      await tick(personal);
      await tick(jobs);
      const listing = await api("browser/chrome-profiles");
      const completed = listing.commands.find(
        (value) => value.id === queued.command.id,
      );
      assert.equal(completed.state, "completed", JSON.stringify(completed));
      const task = await api(
        `browser/extension-tasks/application/${packet.id}`,
      );
      for (const key of [
        "profile_binding_id",
        "browser_session_id",
        "tab_id",
        "window_id",
        "packet_revision",
        "current_url",
      ])
        assert.equal(task[key], bound[key], key);
      assert.ok(
        task.plan_id && ["FORM_INSPECTED", "NEEDS_INPUT"].includes(task.state),
        JSON.stringify(task),
      );
      assert.deepEqual(task.verified_receipts, []);
      assert.deepEqual(
        await foreground(),
        before,
        "Prepare preserves the unrelated foreground tab/window",
      );
      for (const page of [application, unrelated]) {
        assert.equal(await page.locator("#name").inputValue(), "");
        assert.equal(await page.locator("#email").inputValue(), "");
        assert.equal(
          await page.locator("#manual").inputValue(),
          "owner-manual",
        );
        assert.equal(await page.evaluate(() => window.submits), 0);
      }
      const scripts = await worker.evaluate(() => globalThis.prepareScripts);
      assert.equal(scripts.length, separateWindow ? 2 : 1);
      assert.ok(
        scripts.every(
          (value) =>
            value.target.tabId === bound.tab_id &&
            value.operation === "inspect",
        ),
      );
      assert.equal(
        personal.context
          .pages()
          .some((page) => page.url().startsWith("https://jobs.lever.co/")),
        false,
      );
      assert.equal(listing.selection.profile_binding_id, jobs.identity.id);
    }
    assert.equal(
      (await api("browser/chrome-profiles")).commands.find(
        (value) => value.id === opened.command.id,
      ).state,
      "completed",
    );
    assert.equal(nonGet, 0);
    const audit = postgres.sql(
      "SELECT count(*) FROM job_agent.agent_operations WHERE command IN ('authorize_form','record_form_fill'); SELECT count(*) FROM job_agent.owner_preferences WHERE key LIKE 'ext_receipt:%'; SELECT count(*) FROM job_agent.application_packets WHERE lifecycle_state IN ('submitting','provider_confirmed_submitted','user_reported_submitted');",
    );
    assert.deepEqual(audit.split("\n"), ["0", "0", "0"]);
    console.log(
      "Bound Prepare PASS: personal + job profiles; job selected; remote Open; unrelated foreground tab then window; exact bound inspection through real MV3/native/FastAPI/PostgreSQL; unchanged focus/profile/manual values; zero fill authorizations, receipts, employer writes or submissions.",
    );
  } else {
    const first = await enqueue("open");
    const duplicate = await Promise.all(
      Array.from({ length: 6 }, () =>
        api("browser/chrome-profiles/commands", first.data),
      ),
    );
    assert.ok(duplicate.every((value) => value.id === first.command.id));
    await tick(jobs);
    assert.equal(
      jobs.context.pages().some((page) => page.url() === url),
      false,
    );
    await tick(personal);
    let application = personal.context
      .pages()
      .find((page) => page.url() === url);
    assert.ok(application, "only selected personal profile opened the job");
    await application.waitForLoadState("domcontentloaded");
    let task = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.equal(task.profile_binding_id, personal.identity.id);
    assert.equal(task.browser_session_id, personal.identity.sessionId);
    assert.ok(
      Number.isInteger(task.window_id) && Number.isInteger(task.tab_id),
    );
    await enqueue("open");
    await tick(personal);
    assert.equal(
      personal.context.pages().filter((page) => page.url() === url).length,
      1,
    );
    console.log(
      "Profile fixture: selected-only delivery and repeated tab reuse passed",
    );
    // Prepare reads the supported fixture; nothing fills without a separate toolbar approval.
    await enqueue("prepare");
    await tick(personal);
    task = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.ok(
      task.plan_id && ["FORM_INSPECTED", "NEEDS_INPUT"].includes(task.state),
      JSON.stringify(task),
    );
    assert.equal(await application.locator("#email").inputValue(), "");
    assert.equal(
      await application.locator("#manual").inputValue(),
      "owner-manual",
    );
    // Real fixture fill uses the same explicit popup field selection as production.
    const popup = personal.popup;
    await application.bringToFront();
    const send = (action, extra = {}) =>
      popup.evaluate(
        ({ action, extra }) =>
          chrome.runtime.sendMessage({
            command: "application_assistant",
            action,
            ...extra,
          }),
        { action, extra },
      );
    let reviewed = await send("prepare", {
      task_id: task.id,
      interactions_allowed: true,
    });
    assert.ok(reviewed.ok, JSON.stringify(reviewed));
    const fields = reviewed.plan.actions
      .filter(
        (value) =>
          !value.needs_input && !value.preview_only && value.kind !== "file",
      )
      .map((value) => value.field_id);
    const filled = await send("fill", {
      task_id: task.id,
      field_ids: fields,
      interaction_authorized: true,
    });
    assert.ok(filled.ok, JSON.stringify(filled));
    task = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.equal(
      task.verified_receipts.at(-1).verification_method,
      "retained_after_blur",
    );
    assert.equal(
      await application.locator("#email").inputValue(),
      "alex@example.com",
    );
    assert.equal(
      await application.locator("#manual").inputValue(),
      "owner-manual",
    );
    assert.equal(await application.evaluate(() => window.submits), 0);
    console.log("Profile fixture: retained fill persisted without submission");
    const takeover = await send("return_control", { task_id: task.id });
    assert.ok(takeover.ok);
    const resumed = await send("resume", { task_id: task.id });
    assert.ok(resumed.ok, JSON.stringify(resumed));
    // Profile switch revokes plans in A and routes the next explicit Open to B.
    await choose(jobs);
    await enqueue("open", jobs);
    await tick(personal);
    await tick(jobs);
    assert.equal(
      jobs.context.pages().filter((page) => page.url() === url).length,
      1,
      JSON.stringify(await api("browser/chrome-profiles")),
    );
    assert.equal(
      personal.context.pages().filter((page) => page.url() === url).length,
      1,
    );
    task = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.equal(task.profile_binding_id, jobs.identity.id);
    assert.equal(task.plan_id, null);
    // Terminate the actual MV3 worker; its next trusted message wakes a new worker.
    const cdp = await jobs.context.newCDPSession(jobs.page);
    const versions = [];
    cdp.on("ServiceWorker.workerVersionUpdated", (event) =>
      versions.push(...event.versions),
    );
    await cdp.send("ServiceWorker.enable");
    for (
      let i = 0;
      i < 30 &&
      !versions.some(
        (value) =>
          value.scriptURL === `chrome-extension://${extensionId}/background.js`,
      );
      i++
    )
      await delay(100);
    const version = versions.findLast(
      (value) =>
        value.scriptURL === `chrome-extension://${extensionId}/background.js` &&
        value.runningStatus === "running",
    );
    assert.ok(version, "actual MV3 service worker version available");
    await cdp.send("ServiceWorker.stopWorker", {
      versionId: version.versionId,
    });
    await jobs.page.evaluate(() =>
      chrome.runtime.sendMessage({
        command: "chrome_profile",
        action: "status",
      }),
    );
    for (let i = 0; i < 100; i++) {
      task = await api(`browser/extension-tasks/application/${packet.id}`);
      if (
        task.state === "PAUSED" &&
        task.reason === "worker_restart_fresh_inspection_required"
      )
        break;
      await delay(100);
    }
    assert.equal(task.state, "PAUSED");
    assert.equal(task.reason, "worker_restart_fresh_inspection_required");
    assert.equal(task.browser_session_id, jobs.identity.sessionId);
    await cdp.detach();
    // Browser restart preserves binding UUID, rotates browser session and clears plans.
    await jobs.context.close();
    const restarted = await launch("Job applications", true);
    await tick(restarted);
    assert.equal(restarted.identity.id, jobs.identity.id);
    assert.notEqual(restarted.identity.sessionId, jobs.identity.sessionId);
    task = await api(`browser/extension-tasks/application/${packet.id}`);
    assert.equal(task.state, "PAUSED");
    assert.equal(task.tab_id, null);
    assert.equal(task.plan_id, null);
    assert.equal(
      restarted.context.pages().some((page) => page.url() === url),
      false,
    );
    // Expire the heartbeat in the disposable DB to demonstrate honest offline handling.
    const pg =
      "UPDATE job_agent.owner_preferences SET value=jsonb_set(value::jsonb, '{last_heartbeat}', to_jsonb('2000-01-01T00:00:00+00:00'::text)) WHERE key='chr_prof:" +
      restarted.identity.id +
      "';";
    postgres.sql(pg);
    const listing = await api("browser/chrome-profiles");
    assert.equal(
      listing.profiles.find((value) => value.selected).status,
      "PROFILE_OFFLINE",
    );
    const off = {
      ...first.data,
      request_id: randomUUID(),
      profile_binding_id: restarted.identity.id,
      selection_version: listing.selection.version,
      expected_profile_version: listing.profiles.find((value) => value.selected)
        .version,
    };
    const denied = await api("browser/chrome-profiles/commands", off, 409);
    assert.equal(denied.detail, "PROFILE_OFFLINE");
    assert.equal(nonGet, 0);
    // Independent SQL verifies receipts, two distinct bindings, commands and no submission.
    const receipt = postgres.sql(
      "SELECT count(*) FROM job_agent.owner_preferences WHERE key LIKE 'chr_prof:%'; SELECT count(*) FROM job_agent.owner_preferences WHERE key LIKE 'ext_task:%' AND jsonb_array_length(value::jsonb->'verified_receipts') > 0; SELECT count(*) FROM job_agent.owner_preferences WHERE key LIKE 'ext_receipt:%'; SELECT count(*) FROM job_agent.application_packets WHERE lifecycle_state IN ('submitting','provider_confirmed_submitted','user_reported_submitted');",
    );
    assert.deepEqual(receipt.split("\n"), ["2", "1", "1", "0"]);
    console.log(
      "Chrome profiles PostgreSQL PASS: two simultaneous MV3 profiles; selected-only delivery; 6 concurrent duplicate requests; same-window/tab reuse; native/API retained receipt; switch, MV3 worker restart and browser restart; offline pause; zero employer writes/submissions. Fictional fixtures only.",
    );
  }
} finally {
  await Promise.allSettled(contexts.map((context) => context.close()));
  if (apiProcess && apiProcess.exitCode === null) {
    apiProcess.kill("SIGTERM");
    await new Promise((resolve) => apiProcess.once("exit", resolve));
  }
  await postgres?.close();
  await rm(temp, { recursive: true, force: true });
}
