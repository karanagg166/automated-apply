// Real Chrome/MV3/native/FastAPI/SQL stack. All employer data and DB are fictional.
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, mkdir, writeFile, readFile, cp, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const root = resolve(new URL("../../", import.meta.url).pathname),
  python = process.env.PYTHON;
if (!python?.startsWith("/"))
  throw Error("existing_absolute_test_python_required");
const id = "gdjbmkffcpicbpiikcohlmokkmcpipgp",
  url = "https://jobs.lever.co/fictional-owner/fictional-application/apply";
const temporary = await mkdtemp(
  join(tmpdir(), "automated-apply-phase52-stack-"),
);
let context,
  apiProcess,
  nonGet = 0,
  logs = "",
  postgresContainer;
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
try {
  // Never use an owner DSN. This journey owns a fresh, loopback-only container.
  const containerName = `phase52-stack-${crypto.randomUUID()}`;
  postgresContainer = execFileSync(
    "docker",
    [
      "run",
      "--detach",
      "--rm",
      "--pull=never",
      "--name",
      containerName,
      "-p",
      "127.0.0.1::5432",
      "-e",
      "POSTGRES_PASSWORD=fictional_stack_only",
      "-e",
      "POSTGRES_DB=candidate_profile_test",
      "postgres:17-alpine",
    ],
    { encoding: "utf8" },
  ).trim();
  const databasePort = execFileSync(
    "docker",
    ["port", postgresContainer, "5432/tcp"],
    { encoding: "utf8" },
  )
    .trim()
    .split(":")
    .at(-1);
  let databaseReady = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      execFileSync(
        "docker",
        [
          "exec",
          postgresContainer,
          "pg_isready",
          "-U",
          "postgres",
          "-d",
          "candidate_profile_test",
        ],
        { stdio: "ignore" },
      );
      databaseReady = true;
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  assert.equal(
    databaseReady,
    true,
    "disposable PostgreSQL did not become ready",
  );
  const socket = createServer();
  await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const config = join(temporary, "fixture.private.env"),
    profile = join(temporary, "chrome-profile"),
    extension = join(temporary, "extension"),
    wrapper = join(temporary, "native-host");
  await writeFile(
    config,
    [
      "ENVIRONMENT=testing",
      `DATABASE_URL=postgresql+asyncpg://postgres:fictional_stack_only@127.0.0.1:${databasePort}/candidate_profile_test`,
      "DATABASE_SCHEMA=job_agent",
      "SECRET_KEY=fictional-stack-test-secret-key-0000",
      "JOB_AGENT_API_TOKEN=fictional-stack-owner-token",
      `LOCAL_AGENT_ENDPOINT=http://127.0.0.1:${port}`,
      "CHROME_NATIVE_MESSAGING_ENABLED=true",
      `CHROME_EXTENSION_ID=${id}`,
      "BROWSER_FILL_ENABLED=true",
      "BROWSER_AUTOMATION_ENABLED=false",
      "BROWSER_SUBMIT_ENABLED=false",
      "GMAIL_SENDING_ENABLED=false",
      "GMAIL_RETENTION_ENABLED=false",
      "AUTOMATION_EXECUTION_ENABLED=false",
      "AGY_ENABLED=false",
      "COHERE_ENABLED=false",
      "GEMINI_ENABLED=false",
      "OLLAMA_ENABLED=false",
    ].join("\n") + "\n",
    { mode: 0o600 },
  );
  apiProcess = spawn(
    python,
    [
      "backend/scripts/phase52_extension_fixture.py",
      "--env-file",
      config,
      "--port",
      String(port),
    ],
    {
      cwd: root,
      env: { PATH: process.env.PATH },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  apiProcess.stdout.on("data", (chunk) => {
    logs = (logs + chunk.toString()).slice(-5000);
  });
  apiProcess.stderr.on("data", (chunk) => {
    logs = (logs + chunk.toString()).slice(-5000);
  });
  const deadline = Date.now() + 30000;
  let ready = false;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`);
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {}
    if (apiProcess.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(ready, true, logs);
  await cp(join(root, "extension/dist"), extension, { recursive: true });
  const manifest = JSON.parse(
    await readFile(join(extension, "manifest.json"), "utf8"),
  );
  manifest.host_permissions = ["https://jobs.lever.co/*"];
  await writeFile(join(extension, "manifest.json"), JSON.stringify(manifest));
  await writeFile(
    wrapper,
    `#!/bin/sh\ncd ${quote(root)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(config)} "$@"\n`,
    { mode: 0o700 },
  );
  await mkdir(join(profile, "NativeMessagingHosts"), {
    recursive: true,
    mode: 0o700,
  });
  await writeFile(
    join(profile, "NativeMessagingHosts/com.automated_apply.agent.json"),
    JSON.stringify({
      name: "com.automated_apply.agent",
      description: "Fictional complete stack",
      type: "stdio",
      path: wrapper,
      allowed_origins: [`chrome-extension://${id}/`],
    }),
    { mode: 0o600 },
  );
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "--host-resolver-rules=MAP jobs.lever.co ~NOTFOUND",
    ],
  });
  await context.route("https://jobs.lever.co/**", (route) => {
    if (route.request().method() !== "GET") nonGet++;
    return route.fulfill({
      contentType: "text/html",
      body: '<title>Fictional Engineer</title><h1>Fictional Employer</h1><form onsubmit="event.preventDefault();window.submissions++"><label>Email<input type=email id=email required></label><label>Phone<input id=phone value="owner-entered-preserved"></label><button type=submit>Submit</button></form><script>window.submissions=0;window.retained="";document.querySelector("#email").addEventListener("input",e=>{window.retained=e.target.value;});</script>',
    });
  });
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  const employer = await context.newPage();
  await employer.goto(url);
  await employer.bringToFront();
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
  const prepared = await send("prepare", { interactions_allowed: true });
  assert.equal(prepared.ok, true, JSON.stringify(prepared));
  assert.equal(prepared.plan.actions.length, 1);
  assert.equal(prepared.plan.actions[0].value, "alex@example.com");
  const taskId = prepared.task.id;
  const filled = await send("fill", {
    task_id: taskId,
    interaction_authorized: true,
    field_ids: [prepared.plan.actions[0].field_id],
  });
  assert.equal(filled.ok, true, JSON.stringify(filled));
  assert.equal(filled.result.results[0].status, "filled");
  assert.equal(filled.task.state, "READY_FOR_SUBMISSION");
  assert.equal(
    await employer.evaluate(() => window.retained),
    "alex@example.com",
  );
  assert.equal(
    await employer.locator("#phone").inputValue(),
    "owner-entered-preserved",
  );
  const response = await fetch(
    `http://127.0.0.1:${port}/api/v1/browser/extension-tasks/application/${prepared.task.application_id}`,
    { headers: { Authorization: "Bearer fictional-stack-owner-token" } },
  );
  assert.equal(response.status, 200);
  const stored = await response.json();
  assert.equal(stored.id, taskId);
  assert.equal(stored.verified_receipts.length, 1);
  assert.equal(
    stored.verified_receipts[0].verification_method,
    "retained_after_blur",
  );
  assert.equal(stored.network_guard_active, true);
  assert.equal(stored.verified_receipts[0].network_guard_active, true);
  assert.equal(stored.counts.completed, 1);
  assert.equal(stored.counts.existing, 1);
  // Independently inspect PostgreSQL rather than relying only on an API echo.
  const persisted = JSON.parse(
    execFileSync(
      "docker",
      [
        "exec",
        postgresContainer,
        "psql",
        "-U",
        "postgres",
        "-d",
        "candidate_profile_test",
        "-Atc",
        `SELECT value FROM job_agent.owner_preferences WHERE key='ext_task:${taskId}'`,
      ],
      { encoding: "utf8" },
    ).trim(),
  );
  assert.equal(persisted.verified_receipts.length, 1);
  assert.equal(
    persisted.verified_receipts[0].verification_method,
    "retained_after_blur",
  );
  assert.equal(persisted.verified_receipts[0].submitted, false);
  assert.equal(stored.capabilities.unattended_approved, false);
  const duplicate = await send("fill", {
    task_id: taskId,
    interaction_authorized: true,
  });
  assert.equal(duplicate.ok, false);
  const cancelled = await send("cancel", { task_id: taskId });
  assert.equal(cancelled.ok, true);
  assert.equal(cancelled.task.state, "FAILED_FINAL");
  const returned = await send("return_control", { task_id: taskId });
  assert.equal(returned.ok, true, JSON.stringify(returned));
  assert.equal(returned.task.state, "FAILED_FINAL");
  assert.equal(returned.task.network_guard_active, false);
  assert.equal(await employer.evaluate(() => window.submissions), 0);
  assert.equal(nonGet, 0);
  console.log(
    JSON.stringify({
      cases: 1,
      stack: "Chromium/MV3/Python native/FastAPI/disposable PostgreSQL17",
      verified_fields: 1,
      stored_receipts: 1,
      existing_values_preserved: 1,
      employer_write_requests: 0,
      submissions: 0,
      real_data_used: false,
    }),
  );
} finally {
  await context?.close();
  if (apiProcess && apiProcess.exitCode === null) {
    apiProcess.kill();
    await new Promise((resolve) => apiProcess.once("exit", resolve));
  }
  await rm(temporary, { recursive: true, force: true });
  if (postgresContainer)
    execFileSync("docker", ["rm", "--force", postgresContainer], {
      stdio: "ignore",
    });
}
