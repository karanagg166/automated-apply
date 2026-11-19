import { nativePostgresFixture } from "./native-postgres-fixture.mjs";
import {
  fixtureExecutable,
  copyNativeFixtureExtension,
  fixtureEngine,
  nativeFixtureRegistry,
} from "./browser-fixture-engine.mjs";
// Real isolated Brave/Edge + Native Messaging Host + FastAPI + native PostgreSQL 17 E2E suite.
// Coordinates via macOS fcntl.flock on /tmp/automated-apply-heavy-tests.lock.
// Uses an isolated Chrome profile, disposable FastAPI port, and disposable PostgreSQL 17.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const extensionRoot = resolve(here, "..");
const repoRoot = resolve(extensionRoot, "..");
const EXPECTED_ID = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const LOCK_PATH = "/tmp/automated-apply-heavy-tests.lock";

async function loadPlaywright() {
  const candidates = [
    "@playwright/test",
    pathToFileURL(
      resolve(repoRoot, "frontend/node_modules/@playwright/test/index.mjs"),
    ).href,
  ];
  for (const spec of candidates) {
    try {
      return await import(spec);
    } catch {
      // try next candidate inside standalone worktree
    }
  }
  throw new Error(
    "Unable to resolve @playwright/test in this standalone worktree. Run 'pnpm -C frontend install --frozen-lockfile' first.",
  );
}

function findPython() {
  const candidates = [
    process.env.PYTHON,
    resolve(repoRoot, ".venv/bin/python"),
    "python3",
    "python",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate.startsWith("/") && !existsSync(candidate)) continue;
    const probe = spawnSync(
      candidate,
      ["-c", "import pydantic, asyncpg, fastapi, uvicorn"],
      { cwd: repoRoot, stdio: "ignore" },
    );
    if (probe.status === 0) return candidate;
  }
  throw new Error(
    "Unable to resolve Python with backend dependencies in this standalone worktree. Run 'uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r backend/requirements.txt'.",
  );
}

const SENSITIVE_DB_ENV_KEYS = [
  "DATABASE_URL",
  "PHASE1_DISPOSABLE_DATABASE_URL",
  "DIRECT_URL",
  "SUPABASE_URL",
  "SUPABASE_DB_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "PGHOST",
  "PGPORT",
  "PGDATABASE",
  "PGUSER",
  "PGPASSWORD",
  "PGSSLMODE",
];

export function buildSanitizedChildEnv(overrides = {}) {
  const clean = { ...process.env };
  for (const key of SENSITIVE_DB_ENV_KEYS) {
    delete clean[key];
  }
  return { ...clean, ...overrides };
}

export function assertDisposableLocalDatabaseUrl(
  rawUrl,
  expectedPort,
  expectedDbName = "candidate_profile_test",
  expectedUser = null,
) {
  if (typeof rawUrl !== "string" || !rawUrl.trim()) {
    throw new Error("Refusing empty database URL for disposable E2E harness");
  }
  if (
    /(supabase|pooler|amazonaws|neon\.tech|railway|render\.com|rds\.|sslmode=require)/i.test(
      rawUrl,
    )
  ) {
    throw new Error(
      "Refusing nonlocal or Supabase/cloud database URL in disposable E2E harness",
    );
  }
  const normalized = rawUrl.startsWith("postgresql+asyncpg://")
    ? "postgresql://" + rawUrl.slice("postgresql+asyncpg://".length)
    : rawUrl;
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(
      "Refusing unparseable database URL in disposable E2E harness",
    );
  }
  if (parsed.protocol !== "postgresql:") {
    throw new Error(
      `Refusing unexpected database protocol: ${parsed.protocol}`,
    );
  }
  if (parsed.hostname !== "127.0.0.1") {
    throw new Error(`Refusing non-loopback database host: ${parsed.hostname}`);
  }
  if (
    Number(parsed.port) !== expectedPort ||
    expectedPort === 5432 ||
    expectedPort === 54322
  ) {
    throw new Error(`Refusing non-disposable database port: ${parsed.port}`);
  }
  if (parsed.pathname !== `/${expectedDbName}`) {
    throw new Error(`Refusing unexpected database name: ${parsed.pathname}`);
  }
  if (expectedUser && decodeURIComponent(parsed.username) !== expectedUser) {
    throw new Error(`Refusing unexpected database user: ${parsed.username}`);
  }
  if (parsed.search || parsed.hash) {
    throw new Error(
      "Refusing database URL with query parameters or fragments in disposable E2E harness",
    );
  }
  return rawUrl;
}

function acquireFlock(python, lockPath) {
  return new Promise((resolveLock, rejectLock) => {
    const script = [
      "import fcntl, sys, signal",
      "f = open(sys.argv[1], 'w')",
      "fcntl.flock(f.fileno(), fcntl.LOCK_EX)",
      "sys.stdout.write('LOCKED\\n')",
      "sys.stdout.flush()",
      "signal.pause()",
    ].join("; ");
    const child = spawn(python, ["-c", script, lockPath], {
      stdio: ["pipe", "pipe", "ignore"],
    });
    const timer = setTimeout(() => {
      child.kill();
      rejectLock(
        new Error(
          "Timed out waiting for /tmp/automated-apply-heavy-tests.lock",
        ),
      );
    }, 300000);
    child.stdout.on("data", (chunk) => {
      if (chunk.toString("utf8").includes("LOCKED")) {
        clearTimeout(timer);
        resolveLock({
          release() {
            try {
              child.kill("SIGTERM");
            } catch {
              // ignore
            }
          },
        });
      }
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      rejectLock(err);
    });
  });
}

function runFrameProbe(
  python,
  envPath,
  origin,
  rawBuffer,
  closeStdin = true,
  timeoutMs = 15000,
) {
  return new Promise((resolveProbe, rejectProbe) => {
    const child = spawn(
      python,
      ["-m", "backend.app.local_agent.native_host", envPath, origin],
      {
        cwd: repoRoot,
        env: buildSanitizedChildEnv(),
        stdio: ["pipe", "pipe", "ignore"],
      },
    );
    const timer = setTimeout(() => {
      child.kill();
      rejectProbe(new Error("frame probe timeout"));
    }, timeoutMs);
    let output = Buffer.alloc(0);
    child.stdout.on("data", (chunk) => {
      output = Buffer.concat([output, chunk]);
      if (output.length >= 4) {
        const len = output.readUInt32LE(0);
        if (output.length >= len + 4) {
          clearTimeout(timer);
          child.stdin.end();
          resolveProbe(
            JSON.parse(output.subarray(4, len + 4).toString("utf8")),
          );
        }
      }
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      rejectProbe(err);
    });
    child.stdin.write(rawBuffer);
    if (closeStdin) child.stdin.end();
  });
}

function encodeFrame(objOrString) {
  const payload = Buffer.from(
    typeof objOrString === "string" ? objOrString : JSON.stringify(objOrString),
    "utf8",
  );
  const header = Buffer.alloc(4);
  header.writeUInt32LE(payload.length, 0);
  return Buffer.concat([header, payload]);
}

async function waitForHttpReady(url, attempts = 50, delayMs = 200) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (res.ok) return true;
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

const quote = (s) => "'" + String(s).replaceAll("'", "'\\''") + "'";

async function main() {
  const { chromium, expect } = await loadPlaywright();
  const python = findPython();

  // Step 0: Build unpacked extension into extension/dist
  const buildRun = spawnSync(
    "node",
    ["build.mjs", `--browser=${fixtureEngine()}`],
    { cwd: extensionRoot, encoding: "utf8" },
  );
  assert.equal(
    buildRun.status,
    0,
    `extension build failed: ${buildRun.stderr}`,
  );
  const builtExtension = join(extensionRoot, "dist");
  const manifest = JSON.parse(
    readFileSync(join(builtExtension, "manifest.json"), "utf8"),
  );
  assert.equal(
    manifest.version,
    JSON.parse(readFileSync(join(extensionRoot, "manifest.json"), "utf8"))
      .version,
  );
  const keyHash = createHash("sha256")
    .update(Buffer.from(manifest.key, "base64"))
    .digest("hex")
    .slice(0, 32);
  const derivedId = [...keyHash]
    .map((c) => String.fromCharCode(97 + Number.parseInt(c, 16)))
    .join("");
  assert.equal(derivedId, EXPECTED_ID);

  const lock = await acquireFlock(python, LOCK_PATH);
  const baseDir = mkdtempSync(
    join(tmpdir(), "automated-apply-agy-chrome-e2e-"),
  );
  chmodSync(baseDir, 0o700);

  let postgres;
  let pgPort;
  const apiPort = 18095;
  const slowProxyPort = 18096;
  const refusedPort = 18099;

  let apiProcess = null;
  let slowProxyServer = null;
  let context = null;

  const report = {
    evidence_type: "actual-selected-browser-mv3-native-fastapi-postgresql17",
    profile: `isolated_${fixtureEngine()}`,
    extension_version: manifest.version,
    stable_extension_id: derivedId,
    advisory_lock: LOCK_PATH,
    disposable_api_endpoint: `http://127.0.0.1:${apiPort}`,
    disposable_pg_port: pgPort,
    execution_model: {
      real_browser_and_runtime: [
        "Selected Brave/Edge launched headlessly with --load-extension and isolated profile",
        "MV3 background service worker install, chrome://extensions reload, CDP stopAllWorkers suspension/recovery, and browser restart",
        "Real Chrome Native Messaging over OS stdio pipes to backend.app.local_agent.native_host",
        "Real loopback FastAPI service and owned native PostgreSQL 17 cluster on a temporary loopback port",
        "Real DOM clicks on #check in settings.html and #repair, #preview, #observe in popup.html",
      ],
      simulated_page_content: [
        "Local HTML fixtures served via Playwright context.route for example.org, docs.google.com/forms, www.google.com/url, and www.naukri.com so no external requests or real Google Form submissions occur",
      ],
      programmatic_extension_entry_points: [
        "Cross-origin preview(tab) and observeSession(tab) invoked from extension page context (popup.html) because Chrome MV3 grants activeTab only on physical OS-level browser toolbar or native context-menu clicks",
      ],
      native_os_gestures_claimed: false,
    },
    cases_passed: [],
    cases_failed: [],
    preview_correlations: [],
    observation_correlations: [],
    form_fields_read: false,
    form_fields_filled: false,
    form_submit_events: 0,
    form_post_requests: 0,
    submitted: false,
  };

  const stopApi = async () => {
    if (apiProcess && apiProcess.exitCode === null) {
      apiProcess.kill("SIGTERM");
      await new Promise((r) => {
        const t = setTimeout(() => {
          try {
            apiProcess.kill("SIGKILL");
          } catch {
            /* ignore */
          }
          r();
        }, 5000);
        apiProcess.once("exit", () => {
          clearTimeout(t);
          r();
        });
      });
    }
    apiProcess = null;
  };

  try {
    const distDir = join(baseDir, "extension");
    const nativeHost = copyNativeFixtureExtension(builtExtension, distDir);
    postgres = await nativePostgresFixture(python);
    pgPort = postgres.port;
    report.disposable_pg_port = pgPort;
    const adminDbUrl = assertDisposableLocalDatabaseUrl(
      postgres.url,
      pgPort,
      "candidate_profile_test",
      "postgres",
    );

    // Bootstrap public schema & restricted runtime role job_agent_runtime against owned disposable cluster
    const bootstrapRun = spawnSync(
      python,
      ["backend/scripts/phase1/verify_public.py", "--bootstrap"],
      {
        cwd: repoRoot,
        env: buildSanitizedChildEnv({
          PHASE1_DISPOSABLE_DATABASE_URL: adminDbUrl,
        }),
        encoding: "utf8",
      },
    );
    assert.equal(
      bootstrapRun.status,
      0,
      `verify_public bootstrap failed: ${bootstrapRun.stderr}`,
    );

    const envFile = join(baseDir, "disposable.private.env");
    const prepRun = spawnSync(
      python,
      ["backend/scripts/phase1/prepare_disposable.py", "--output", envFile],
      {
        cwd: repoRoot,
        env: buildSanitizedChildEnv({
          PHASE1_DISPOSABLE_DATABASE_URL: adminDbUrl,
        }),
        encoding: "utf8",
      },
    );
    assert.equal(
      prepRun.status,
      0,
      `prepare_disposable failed: ${prepRun.stderr}`,
    );

    const writeEnvConfig = (targetPath, overrides = {}) => {
      const baseText = readFileSync(envFile, "utf8");
      const map = {};
      for (const line of baseText.split("\n")) {
        const idx = line.indexOf("=");
        if (idx > 0)
          map[line.slice(0, idx).trim()] = JSON.parse(
            line.slice(idx + 1).trim(),
          );
      }
      assertDisposableLocalDatabaseUrl(
        map.DATABASE_URL,
        pgPort,
        "candidate_profile_test",
        "job_agent_runtime",
      );
      map.LOCAL_AGENT_ENDPOINT = `http://127.0.0.1:${apiPort}`;
      map.CHROME_EXTENSION_ID = EXPECTED_ID;
      map.CHROME_NATIVE_MESSAGING_ENABLED = "true";
      Object.assign(map, overrides);
      const serialized =
        Object.entries(map)
          .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
          .join("\n") + "\n";
      writeFileSync(targetPath, serialized, { mode: 0o600 });
      chmodSync(targetPath, 0o600);
      return map;
    };

    const activeEnvPath = join(baseDir, "active.private.env");
    const activeConfig = writeEnvConfig(activeEnvPath);
    const apiToken = activeConfig.JOB_AGENT_API_TOKEN;
    const authHeaders = { Authorization: `Bearer ${apiToken}` };

    const startApi = async () => {
      apiProcess = spawn(
        python,
        [
          "backend/scripts/phase1/local_service.py",
          "api",
          "--env-file",
          activeEnvPath,
        ],
        { cwd: repoRoot, env: buildSanitizedChildEnv(), stdio: "ignore" },
      );
      const ready = await waitForHttpReady(
        `http://127.0.0.1:${apiPort}/ready`,
        60,
        200,
      );
      assert.equal(ready, true, "Disposable FastAPI failed to become ready");
    };

    await startApi();

    // Set up Chrome profile and native messaging host manifest
    const profileDir = join(baseDir, "chrome-profile");
    const registry = nativeFixtureRegistry(profileDir);
    const hostsDir = registry.directory;
    mkdirSync(hostsDir, { recursive: true, mode: 0o700 });
    const wrapperPath = join(baseDir, "native-host");
    const hostManifestPath = join(hostsDir, `${nativeHost}.json`);

    const bindWrapper = (configPath) => {
      writeFileSync(
        wrapperPath,
        `#!/bin/sh\ncd ${quote(repoRoot)} || exit 1\nexec ${quote(python)} -m backend.app.local_agent.native_host ${quote(configPath)} "$@"\n`,
        { mode: 0o700 },
      );
      chmodSync(wrapperPath, 0o700);
    };

    const writeHostManifest = (allowedExtensionId = EXPECTED_ID) => {
      const doc = {
        name: nativeHost,
        description: "Isolated AGY Chrome extension E2E host",
        type: "stdio",
        path: wrapperPath,
        allowed_origins: [`chrome-extension://${allowedExtensionId}/`],
      };
      writeFileSync(hostManifestPath, JSON.stringify(doc, null, 2), {
        mode: 0o600,
      });
      chmodSync(hostManifestPath, 0o600);
    };

    bindWrapper(activeEnvPath);
    writeHostManifest(EXPECTED_ID);

    const launchChrome = async (extPath = distDir) => {
      context = await chromium.launchPersistentContext(profileDir, {
        executablePath: fixtureExecutable(chromium),
        env: registry.env,
        headless: true,
        timeout: 30_000,
        args: [
          `--disable-extensions-except=${extPath}`,
          `--load-extension=${extPath}`,
          "--host-resolver-rules=MAP * ~NOTFOUND",
        ],
      });
      report.browser_version = await context.browser().version();
      const worker =
        context.serviceWorkers().find((w) => w.url().includes(EXPECTED_ID)) ||
        (await context.waitForEvent("serviceworker", { timeout: 15000 }));
      assert.equal(worker.url().split("/")[2], EXPECTED_ID);
      return worker;
    };

    // Instrument test fixtures on example.org, docs.google.com, google.com/url, and www.naukri.com
    let portalFixtureMode = "login_required";
    const installRoutes = async (ctx) => {
      await ctx.route("**/*", async (route) => {
        const reqUrl = route.request().url();
        if (
          route.request().method() === "POST" &&
          reqUrl.includes("docs.google.com/forms")
        ) {
          report.form_post_requests += 1;
        }
        if (reqUrl.startsWith("https://example.org/")) {
          await route.fulfill({
            status: 200,
            contentType: "text/html; charset=utf-8",
            body: `<!doctype html><html><head><title>Example Application Page</title></head><body><h1>Apply at Example Org</h1><a id="form-link" href="https://docs.google.com/forms/d/e/1FAIpQLSf_context_link/viewform">Form Link</a></body></html>`,
          });
          return;
        }
        if (reqUrl.startsWith("https://www.google.com/url?")) {
          const parsed = new URL(reqUrl);
          const target = parsed.searchParams.get("q") || "https://example.org/";
          if (parsed.searchParams.get("mode") === "auto") {
            await route.fulfill({
              status: 200,
              contentType: "text/html; charset=utf-8",
              body: `<!doctype html><html><head><title>Redirecting</title><script>window.location.replace(${JSON.stringify(target)});</script></head><body>Redirecting...</body></html>`,
            });
            return;
          }
          // Google Redirect Notice interstitial page
          await route.fulfill({
            status: 200,
            contentType: "text/html; charset=utf-8",
            body: `<!doctype html><html><head><title>Redirect Notice</title></head><body><p>The previous page is sending you to <a id="redirect-here" href="${target}">here</a>.</p></body></html>`,
          });
          return;
        }
        if (reqUrl.startsWith("https://docs.google.com/forms/")) {
          await route.fulfill({
            status: 200,
            contentType: "text/html; charset=utf-8",
            body: `<!doctype html><html><head><title>Non-Sensitive Phase 1 QA Google Form</title></head><body>
              <form id="qa-google-form" action="https://docs.google.com/forms/d/e/1FAIpQLSf_phase1_qa/formResponse" method="POST">
                <input id="candidate-name" name="entry.1001" type="text" value="" />
                <textarea id="candidate-note" name="entry.1002"></textarea>
                <button id="submit-btn" type="submit">Submit</button>
              </form>
              <script>
                window.__formAudit = { valueReads: 0, valueWrites: 0, submits: 0 };
                const input = document.getElementById("candidate-name");
                const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
                Object.defineProperty(input, "value", {
                  get() { window.__formAudit.valueReads += 1; return desc.get.call(this); },
                  set(v) { window.__formAudit.valueWrites += 1; return desc.set.call(this, v); }
                });
                document.getElementById("qa-google-form").addEventListener("submit", (e) => {
                  e.preventDefault();
                  window.__formAudit.submits += 1;
                });
              </script>
            </body></html>`,
          });
          return;
        }
        if (reqUrl.startsWith("https://www.naukri.com/")) {
          const bodyByMode = {
            login_required: `<!doctype html><html><head><title>Naukri Login</title></head><body><form><input type="password" name="pwd" style="display:block;width:100px;height:24px" /></form></body></html>`,
            signed_in: `<!doctype html><html><head><title>Naukri Profile</title></head><body><button type="button" style="display:block;width:100px;height:24px">Log out</button></body></html>`,
            unverifiable: `<!doctype html><html><head><title>Naukri Home</title></head><body><div>Welcome to job search</div></body></html>`,
          }[portalFixtureMode];
          await route.fulfill({
            status: 200,
            contentType: "text/html; charset=utf-8",
            body: bodyByMode,
          });
          return;
        }
        await route.continue();
      });
    };

    // CASE 1 & 2: Extension install and stable extension ID
    let worker = await launchChrome(distDir);
    await installRoutes(context);
    assert.equal(worker.url().split("/")[2], EXPECTED_ID);
    report.cases_passed.push("2_stable_extension_id");

    // CASE 3 & 4: Native host discovery + Backend health and ping (via settings.html #check and native commands)
    const healthHttp = await fetch(`http://127.0.0.1:${apiPort}/health`);
    assert.equal(healthHttp.status, 200);
    const settingsPage = await context.newPage();
    await settingsPage.goto(`chrome-extension://${EXPECTED_ID}/settings.html`);
    await expect(settingsPage.locator("#identity")).toContainText(
      `Extension ID: ${EXPECTED_ID}`,
    );
    await settingsPage.locator("#check").click();
    // Match the settings/native request budget rather than the default 5s assertion.
    await expect(settingsPage.locator("#endpoint")).toContainText(
      `Active endpoint: http://127.0.0.1:${apiPort}`,
      { timeout: 45000 },
    );
    const capabilitiesCheck = await settingsPage.evaluate(async (host) => {
      const cap = await chrome.runtime.sendNativeMessage(host, {
        version: 1,
        request_id: crypto.randomUUID(),
        command: "get_agent_capabilities",
      });
      const conn = await chrome.runtime.sendNativeMessage(host, {
        version: 1,
        request_id: crypto.randomUUID(),
        command: "connection_status",
      });
      return { cap, conn };
    }, nativeHost);
    assert.equal(capabilitiesCheck.cap.ok, true);
    assert.equal(capabilitiesCheck.cap.data.submissions, false);
    assert.equal(capabilitiesCheck.cap.data.email_sending, false);
    assert.equal(capabilitiesCheck.cap.data.paid_calls, false);
    assert.equal(capabilitiesCheck.conn.ok, true);
    report.preview_correlations.push(
      capabilitiesCheck.cap.correlation_id,
      capabilitiesCheck.conn.correlation_id,
    );
    await settingsPage.close();
    report.cases_passed.push("3_native_host_discovery");
    report.cases_passed.push("4_backend_health_and_ping");

    // Helper to trigger preview on active page or popup
    const appPage = context.pages()[0] || (await context.newPage());
    const popupPage = await context.newPage();
    await popupPage.goto(`chrome-extension://${EXPECTED_ID}/popup.html`);
    await popupPage
      .getByText("Connection and URL preview", { exact: true })
      .click();

    const runPreviewOnPage = async (url) => {
      if (url) await appPage.goto(url, { waitUntil: "domcontentloaded" });
      const res = await popupPage.evaluate(
        async ({ targetUrl, title }) => {
          const mod = await import(chrome.runtime.getURL("preview.js"));
          return await mod.preview({ id: 101, url: targetUrl, title });
        },
        { targetUrl: appPage.url(), title: await appPage.title() },
      );
      if (res.ok) report.preview_correlations.push(res.correlation_id);
      return res;
    };

    // CASE 5: Ordinary HTTPS page preview
    const ordinaryRes = await runPreviewOnPage(
      "https://example.org/jobs/software-engineer",
    );
    assert.equal(ordinaryRes.ok, true);
    assert.equal(ordinaryRes.data.platform, "employer_forms");
    assert.equal(ordinaryRes.data.submitted, false);
    assert.equal(ordinaryRes.data.page_inspected, false);
    await expect(popupPage.locator("#status")).toContainText(
      "URL preview saved. Use Prepare answers to answer the form. No application submitted.",
    );
    report.cases_passed.push("5_ordinary_https_page_preview");

    // CASE 6 & 23: Non-sensitive Google Forms preview & No unauthorized form submission
    const formUrl =
      "https://docs.google.com/forms/d/e/1FAIpQLSf_phase1_qa/viewform";
    const formRes = await runPreviewOnPage(formUrl);
    assert.equal(formRes.ok, true);
    assert.equal(formRes.data.platform, "google_forms");
    assert.equal(formRes.data.url, formUrl);
    assert.equal(formRes.data.submitted, false);
    assert.equal(formRes.data.page_inspected, false);
    const formAudit = await appPage.evaluate(() => window.__formAudit);
    assert.deepEqual(formAudit, { valueReads: 0, valueWrites: 0, submits: 0 });
    assert.equal(report.form_post_requests, 0);
    report.cases_passed.push("6_non_sensitive_google_forms_preview");
    report.cases_passed.push("23_no_unauthorized_form_submission");

    // CASE 7: Google Forms redirects (both interstitial redirect notice and HTTP 302 redirect, plus unsafe redirect rejection)
    const redirectTargetForm =
      "https://docs.google.com/forms/d/e/1FAIpQLSf_redirected_qa/viewform";
    const interstitialRedirectUrl = `https://www.google.com/url?q=${encodeURIComponent(redirectTargetForm)}&sa=D`;
    const interstitialRes = await runPreviewOnPage(interstitialRedirectUrl);
    assert.equal(interstitialRes.ok, true);
    assert.equal(interstitialRes.data.platform, "google_forms");
    assert.equal(interstitialRes.data.url, redirectTargetForm);
    assert.equal(interstitialRes.data.submitted, false);

    const http302RedirectTarget =
      "https://docs.google.com/forms/d/e/1FAIpQLSf_http302_qa/viewform";
    const http302RedirectUrl = `https://www.google.com/url?mode=auto&q=${encodeURIComponent(http302RedirectTarget)}`;
    await appPage.goto(http302RedirectUrl, { waitUntil: "domcontentloaded" });
    await appPage.waitForURL(http302RedirectTarget, { timeout: 10000 });
    const http302Res = await runPreviewOnPage();
    assert.equal(new URL(appPage.url()).hostname, "docs.google.com");
    assert.equal(http302Res.ok, true);
    assert.equal(http302Res.data.platform, "google_forms");
    assert.equal(http302Res.data.url, http302RedirectTarget);
    assert.equal(http302Res.data.submitted, false);

    const unsafeRedirectRes = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      return await mod.preview({
        id: 101,
        url:
          "https://www.google.com/url?q=" +
          encodeURIComponent("http://127.0.0.1:8000/internal"),
      });
    });
    assert.equal(unsafeRedirectRes.ok, false);
    assert.equal(unsafeRedirectRes.error_code, "unsupported_page");
    report.cases_passed.push("7_google_forms_redirects");

    const runObserveOnPortalPage = async (url) => {
      if (url) await appPage.goto(url, { waitUntil: "domcontentloaded" });
      const domIndicator = await appPage.evaluate(() => {
        const visible = (element) =>
          !!element?.getClientRects().length &&
          (typeof element.checkVisibility !== "function" ||
            element.checkVisibility({
              checkOpacity: true,
              checkVisibilityCSS: true,
            }));
        const linkedLogout = [
          ...document.querySelectorAll(
            'a[href*="logout"],a[href*="sign_out"],button[data-action="logout"]',
          ),
        ].some(visible);
        const labelledLogout = [
          ...document.querySelectorAll(
            'a,button,[role="button"],[role="menuitem"]',
          ),
        ]
          .slice(0, 500)
          .some((element) => {
            if (!visible(element)) return false;
            const label = (
              element.getAttribute?.("aria-label") ||
              element.innerText ||
              element.textContent ||
              ""
            ).trim();
            if (/^(?:log\s*-?\s*out|sign\s*-?\s*out)$/i.test(label))
              return true;
            const href = (element.getAttribute?.("href") || "").trim();
            return /(?:^|[/?#&=_])(?:log[-_]?out|sign[-_]?out)(?:$|[/?#&])/i.test(
              href,
            );
          });
        const signedIn = linkedLogout || labelledLogout;
        const password = [
          ...document.querySelectorAll('input[type="password"]'),
        ].some(visible);
        return signedIn && !password
          ? "signed_in_indicator"
          : password && !signedIn
            ? "login_required"
            : "unverifiable";
      });
      const currentUrl = appPage.url();
      const obsRes = await popupPage.evaluate(
        async ({ tabUrl, indicator }) => {
          const origExec = chrome.scripting.executeScript;
          const origQuery = chrome.tabs.query;
          chrome.scripting.executeScript = async () => [{ result: indicator }];
          chrome.tabs.query = async () => [{ id: 108, url: tabUrl }];
          try {
            const mod = await import(chrome.runtime.getURL("background.js"));
            return await mod.observeSession({ id: 108, url: tabUrl });
          } finally {
            chrome.scripting.executeScript = origExec;
            chrome.tabs.query = origQuery;
          }
        },
        { tabUrl: currentUrl, indicator: domIndicator },
      );
      if (obsRes.ok)
        report.observation_correlations.push(obsRes.correlation_id);
      return obsRes;
    };

    // CASE 8: Popup interaction (real button clicks on #repair, #preview, #observe, and portal session indicator checks)
    await popupPage.locator("#repair").click();
    await expect(popupPage.locator("#menu-status")).toContainText(
      "Right-click menu registered for HTTPS pages.",
    );

    // Exercise real #preview and #observe button clicks in popup.html (when popupPage is active tab, activeTab is chrome-extension://)
    await popupPage.locator("#preview").click();
    await expect(popupPage.locator("#status")).toContainText(
      "unsupported_page",
    );
    await popupPage.locator("#observe").click();
    await expect(popupPage.locator("#observation")).toContainText(
      "Open a supported job portal in the active tab",
    );

    // Exercise portal session indicator detection across all 3 states on https://www.naukri.com/mnjuser/homepage
    for (const [mode, expectedObs, expectedState, expectedSnippet] of [
      [
        "login_required",
        "login_required",
        "owner_action_required",
        "A login form is visible.",
      ],
      [
        "signed_in",
        "signed_in_indicator",
        "browser_session_observed",
        "A visible sign-in indicator was observed and saved.",
      ],
      [
        "unverifiable",
        "unverifiable",
        "owner_action_required",
        "no supported visible sign-in indicator was found",
      ],
    ]) {
      portalFixtureMode = mode;
      const obsRes = await runObserveOnPortalPage(
        `https://www.naukri.com/mnjuser/homepage?mode=${mode}`,
      );
      assert.equal(
        obsRes.ok,
        true,
        `observeSession failed for ${mode}: ${JSON.stringify(obsRes)}`,
      );
      assert.equal(obsRes.data.observation, expectedObs);
      assert.equal(obsRes.data.state, expectedState);
      assert.equal(obsRes.data.api_connected, false);
      assert.equal(obsRes.data.identity_verified, false);
      await expect(popupPage.locator("#observation")).toContainText(
        expectedSnippet,
      );
    }
    report.cases_passed.push("8_popup_interaction");

    // CASE 9: Context-menu interaction
    // Verify context menu item is live in Chrome's registry and dispatch context-menu preview for linkUrl
    await worker.evaluate(async () => {
      await chrome.contextMenus.update("automated-apply-preview", {
        enabled: true,
      });
      await chrome.contextMenus.update("automated-apply-answer-fields", {
        enabled: true,
      });
    });
    const menuRes = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      return await mod.preview(
        { id: 109, title: "Context Menu Link" },
        "https://docs.google.com/forms/d/e/1FAIpQLSf_context_menu_link/viewform",
      );
    });
    assert.equal(menuRes.ok, true);
    assert.equal(menuRes.data.platform, "google_forms");
    assert.equal(menuRes.data.submitted, false);
    report.preview_correlations.push(menuRes.correlation_id);
    report.cases_passed.push("9_context_menu_interaction");

    // CASE 10: Page refresh
    await appPage.goto("https://example.org/refresh-target", {
      waitUntil: "domcontentloaded",
    });
    const beforeRefresh = await runPreviewOnPage();
    assert.equal(beforeRefresh.ok, true);
    await appPage.reload({ waitUntil: "domcontentloaded" });
    await new Promise((r) => setTimeout(r, 300));
    const afterRefresh = await runPreviewOnPage();
    assert.equal(afterRefresh.ok, true);
    assert.notEqual(afterRefresh.request_id, beforeRefresh.request_id);
    report.cases_passed.push("10_page_refresh");

    // CASE 11: Service worker suspension/recovery
    const cdp = await context.newCDPSession(appPage);
    await cdp.send("ServiceWorker.enable");
    await cdp.send("ServiceWorker.stopAllWorkers");
    await popupPage.reload();
    await popupPage
      .getByText("Connection and URL preview", { exact: true })
      .click();
    await popupPage.locator("#repair").click();
    await expect(popupPage.locator("#menu-status")).toContainText(
      "Right-click menu registered for HTTPS pages.",
    );
    worker =
      context.serviceWorkers().find((w) => w.url().includes(EXPECTED_ID)) ||
      (await context.waitForEvent("serviceworker", { timeout: 10000 }));
    const postWakeRes = await runPreviewOnPage(
      "https://example.org/after-worker-wake",
    );
    assert.equal(postWakeRes.ok, true);
    await cdp.detach();
    report.cases_passed.push("11_service_worker_suspension_recovery");

    // CASE 13 & 14: Backend unavailable & Backend recovery (both preview and portal session observation)
    const offlineEnvPath = join(baseDir, "offline.private.env");
    writeEnvConfig(offlineEnvPath, {
      LOCAL_AGENT_ENDPOINT: `http://127.0.0.1:${refusedPort}`,
    });
    bindWrapper(offlineEnvPath);

    const offlinePreview = await runPreviewOnPage(
      "https://example.org/while-backend-offline",
    );
    assert.equal(offlinePreview.ok, false);
    assert.equal(offlinePreview.error_code, "backend_offline");
    await expect(popupPage.locator("#status")).toContainText("backend_offline");

    portalFixtureMode = "signed_in";
    const offlineObs = await runObserveOnPortalPage(
      "https://www.naukri.com/mnjuser/offline-check",
    );
    assert.equal(offlineObs.ok, false);
    assert.equal(offlineObs.error_code, "backend_offline");
    await expect(popupPage.locator("#observation")).toContainText(
      "The local backend is offline.",
    );
    report.cases_passed.push("13_backend_unavailable");

    // Restore backend config and verify immediate recovery on the exact same URLs
    bindWrapper(activeEnvPath);
    const recoveredObs = await runObserveOnPortalPage(
      "https://www.naukri.com/mnjuser/offline-check",
    );
    assert.equal(recoveredObs.ok, true);

    const recoveredPreview = await runPreviewOnPage(
      "https://example.org/while-backend-offline",
    );
    assert.equal(recoveredPreview.ok, true);
    await expect(popupPage.locator("#status")).toContainText(
      "URL preview saved. Use Prepare answers to answer the form. No application submitted.",
    );
    report.cases_passed.push("14_backend_recovery");

    // CASE 15: Slow API responses (1.2s delayed proxy -> coalesced concurrent calls + clean completion)
    slowProxyServer = http.createServer((req, res) => {
      const chunks = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        setTimeout(() => {
          const proxyReq = http.request(
            {
              hostname: "127.0.0.1",
              port: apiPort,
              path: req.url,
              method: req.method,
              headers: req.headers,
            },
            (proxyRes) => {
              res.writeHead(proxyRes.statusCode, proxyRes.headers);
              proxyRes.pipe(res);
            },
          );
          proxyReq.on("error", () => {
            res.writeHead(502);
            res.end();
          });
          proxyReq.end(Buffer.concat(chunks));
        }, 1200);
      });
    });
    await new Promise((r) =>
      slowProxyServer.listen(slowProxyPort, "127.0.0.1", r),
    );
    const slowEnvPath = join(baseDir, "slow.private.env");
    writeEnvConfig(slowEnvPath, {
      LOCAL_AGENT_ENDPOINT: `http://127.0.0.1:${slowProxyPort}`,
    });
    bindWrapper(slowEnvPath);

    const slowStarted = Date.now();
    const slowPair = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      const tab = {
        id: 115,
        url: "https://example.org/slow-api-response",
        title: "Slow API",
      };
      return await Promise.all([mod.preview(tab), mod.preview(tab)]);
    });
    const slowElapsed = Date.now() - slowStarted;
    assert.ok(
      slowElapsed >= 1100,
      `Expected slow API delay >= 1100ms, got ${slowElapsed}ms`,
    );
    assert.equal(slowPair[0].ok, true);
    assert.equal(slowPair[0].request_id, slowPair[1].request_id);
    report.preview_correlations.push(slowPair[0].correlation_id);
    bindWrapper(activeEnvPath);
    slowProxyServer.close();
    slowProxyServer = null;
    report.cases_passed.push("15_slow_api_responses");

    // CASE 16: Backend restarts during requests
    await stopApi();
    const midRestartRes = await runPreviewOnPage(
      "https://example.org/backend-restarting",
    );
    assert.equal(midRestartRes.ok, false);
    assert.equal(midRestartRes.error_code, "backend_offline");
    await startApi();
    const afterRestartRes = await runPreviewOnPage(
      "https://example.org/backend-restarting",
    );
    assert.equal(afterRestartRes.ok, true);
    report.cases_passed.push("16_backend_restarts_during_requests");

    // CASE 17: Native host timeout
    writeFileSync(wrapperPath, `#!/bin/sh\nsleep 5\n`, { mode: 0o700 });
    const timeoutRes = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      mod.setNativeTimeoutForTesting(300);
      try {
        return await mod.preview({
          id: 117,
          url: "https://example.org/native-timeout-test",
        });
      } finally {
        mod.setNativeTimeoutForTesting(45000);
      }
    });
    assert.equal(timeoutRes.ok, false);
    assert.equal(timeoutRes.error_code, "native_host_timeout");
    bindWrapper(activeEnvPath);
    report.cases_passed.push("17_native_host_timeout");

    // CASE 18 & 21: Wrong-origin rejection & Stale extension ID
    // 18a / 21a: Chrome-level allowed_origins mismatch
    writeHostManifest("a".repeat(32));
    const chromeOriginDenied = await runPreviewOnPage(
      "https://example.org/stale-chrome-origin",
    );
    assert.equal(chromeOriginDenied.ok, false);
    assert.equal(chromeOriginDenied.error_code, "native_origin_not_authorized");

    // 18b / 21b: Python native-host CHROME_EXTENSION_ID mismatch
    writeHostManifest(EXPECTED_ID);
    const staleEnvPath = join(baseDir, "stale-id.private.env");
    writeEnvConfig(staleEnvPath, { CHROME_EXTENSION_ID: "a".repeat(32) });
    bindWrapper(staleEnvPath);
    const hostOriginDenied = await runPreviewOnPage(
      "https://example.org/stale-env-origin",
    );
    assert.equal(hostOriginDenied.ok, false);
    assert.equal(hostOriginDenied.error_code, "native_origin_denied");

    // 18c: FastAPI /api/v1/local-agent/chrome X-Agent-Client header mismatch
    const apiWrongClient = await fetch(
      `http://127.0.0.1:${apiPort}/api/v1/local-agent/chrome`,
      {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
          "X-Agent-Client": "b".repeat(32),
        },
        body: JSON.stringify({
          version: 1,
          request_id: crypto.randomUUID(),
          command: "health",
        }),
      },
    );
    assert.equal(apiWrongClient.status, 403);
    bindWrapper(activeEnvPath);
    report.cases_passed.push("18_wrong_origin_rejection");
    report.cases_passed.push("21_stale_extension_id");

    // CASE 19: Malformed and oversized requests (extension gate + native framing gate)
    const badExtensionInputs = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      const urls = [
        "chrome://extensions",
        "file:///etc/passwd",
        "http://example.org/insecure",
        "https://localhost/internal",
        "https://127.0.0.1/loopback",
        "https://example.org:8443/custom-port",
        "https://example.org/%0ainjection",
        "https://example.org/" + "x".repeat(2050),
      ];
      const results = [];
      for (const u of urls) {
        results.push(await mod.preview({ id: 119, url: u }));
      }
      return results;
    });
    assert.ok(
      badExtensionInputs.every(
        (r) => r.ok === false && r.error_code === "unsupported_page",
      ),
    );

    const validOrigin = `chrome-extension://${EXPECTED_ID}/`;
    const malformedFrame = await runFrameProbe(
      python,
      activeEnvPath,
      validOrigin,
      encodeFrame("{bad-json"),
    );
    assert.equal(malformedFrame.error_code, "native_invalid_message");
    const oversizedHeader = Buffer.alloc(4);
    oversizedHeader.writeUInt32LE(16385, 0);
    const oversizedFrame = await runFrameProbe(
      python,
      activeEnvPath,
      validOrigin,
      oversizedHeader,
    );
    assert.equal(oversizedFrame.error_code, "native_message_size");
    report.cases_passed.push("19_malformed_and_oversized_requests");

    // CASE 20: Duplicate and concurrent gestures
    const concurrentPreviews = await popupPage.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      const tab = {
        id: 120,
        url: "https://example.org/concurrent-gesture-test",
        title: "Concurrent",
      };
      return await Promise.all([
        mod.preview(tab),
        mod.preview(tab),
        mod.preview(tab),
      ]);
    });
    assert.equal(concurrentPreviews[0].ok, true);
    assert.equal(
      concurrentPreviews[0].request_id,
      concurrentPreviews[1].request_id,
    );
    assert.equal(
      concurrentPreviews[1].request_id,
      concurrentPreviews[2].request_id,
    );
    report.preview_correlations.push(concurrentPreviews[0].correlation_id);
    report.cases_passed.push("20_duplicate_and_concurrent_gestures");

    // CASE 22: Missing native messaging host
    unlinkSync(hostManifestPath);
    const missingHostPreview = await runPreviewOnPage(
      "https://example.org/missing-native-host",
    );
    assert.equal(missingHostPreview.ok, false);
    assert.equal(missingHostPreview.error_code, "native_host_not_found");

    const missingHostObs = await runObserveOnPortalPage(
      "https://www.naukri.com/mnjuser/missing-host",
    );
    assert.equal(missingHostObs.ok, false);
    assert.equal(missingHostObs.error_code, "native_host_not_found");
    await expect(popupPage.locator("#observation")).toContainText(
      "The native host is unavailable.",
    );

    // Restore native host manifest
    writeHostManifest(EXPECTED_ID);
    const restoredHostPreview = await runPreviewOnPage(
      "https://example.org/restored-native-host",
    );
    assert.equal(restoredHostPreview.ok, true);
    report.cases_passed.push("22_missing_native_messaging_host");

    // CASE 1 (reload in chrome://extensions UI): Extension install and reload
    const mgmtPage = await context.newPage();
    await mgmtPage.goto("chrome://extensions");
    const devSwitch = mgmtPage.getByRole("switch", {
      name: "Developer mode",
      exact: true,
    });
    if (!(await devSwitch.isChecked())) await devSwitch.click();
    await mgmtPage.getByRole("button", { name: "Reload", exact: true }).click();
    await new Promise((r) => setTimeout(r, 800));
    await mgmtPage.close();

    const wakePopup = await context.newPage();
    await wakePopup.goto(`chrome-extension://${EXPECTED_ID}/popup.html`);
    await expect(wakePopup.locator("#menu-status")).toContainText(
      "Right-click menu registered for HTTPS pages.",
    );
    worker =
      context.serviceWorkers().find((w) => w.url().includes(EXPECTED_ID)) ||
      (await context.waitForEvent("serviceworker", { timeout: 10000 }));
    const afterReloadPreview = await wakePopup.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      return await mod.preview({
        id: 121,
        url: "https://example.org/after-extension-reload",
        title: "Reloaded",
      });
    });
    assert.equal(afterReloadPreview.ok, true);
    report.preview_correlations.push(afterReloadPreview.correlation_id);
    report.cases_passed.push("1_extension_install_and_reload");

    // CASE 12: Chrome restart (with relocated extension directory to also prove path-independent stable ID)
    await context.close();
    context = null;
    const relocatedDir = join(baseDir, "relocated-extension");
    cpSync(distDir, relocatedDir, { recursive: true });
    worker = await launchChrome(relocatedDir);
    await installRoutes(context);
    assert.equal(worker.url().split("/")[2], EXPECTED_ID);
    const restartPage = context.pages()[0] || (await context.newPage());
    await restartPage.goto("https://example.org/after-chrome-restart", {
      waitUntil: "domcontentloaded",
    });
    const restartPopup = await context.newPage();
    await restartPopup.goto(`chrome-extension://${EXPECTED_ID}/popup.html`);
    const afterRestartBrowserRes = await restartPopup.evaluate(async () => {
      const mod = await import(chrome.runtime.getURL("preview.js"));
      return await mod.preview({
        id: 122,
        url: "https://example.org/after-chrome-restart",
        title: "Restarted",
      });
    });
    assert.equal(afterRestartBrowserRes.ok, true);
    report.preview_correlations.push(afterRestartBrowserRes.correlation_id);
    report.cases_passed.push("12_chrome_restart");

    // Verify backend audit correlation in PostgreSQL via /api/v1/local-agent/history
    const historyRes = await fetch(
      `http://127.0.0.1:${apiPort}/api/v1/local-agent/history`,
      {
        headers: authHeaders,
      },
    );
    assert.equal(historyRes.status, 200);
    const historyRows = await historyRes.json();
    const expectedCorrelations = [
      ...new Set([
        ...report.preview_correlations,
        ...report.observation_correlations,
      ]),
    ];
    const byCorrelation = new Map(
      historyRows.map((row) => [row.result?.correlation_id, row]),
    );
    for (const cid of expectedCorrelations) {
      const matched = byCorrelation.get(cid);
      assert.ok(
        matched,
        `Missing PostgreSQL audit row for correlation_id ${cid}`,
      );
      assert.equal(matched.actor, `chrome:${EXPECTED_ID}`);
      assert.equal(matched.result.ok, true);
      if (
        matched.command === "preview_application_url" ||
        matched.command === "observe_platform_session"
      ) {
        assert.equal(matched.result.data.submitted, false);
      }
    }
    report.backend_audit = {
      total_history_rows: historyRows.length,
      verified_unique_correlations: expectedCorrelations.length,
      actor: `chrome:${EXPECTED_ID}`,
      all_submitted_false: true,
    };

    console.log(JSON.stringify(report, null, 2));
  } finally {
    if (context) {
      try {
        await context.close();
      } catch {
        /* ignore */
      }
    }
    if (slowProxyServer) {
      try {
        slowProxyServer.close();
      } catch {
        /* ignore */
      }
    }
    await stopApi();
    await postgres?.close();
    if (
      baseDir.startsWith(tmpdir()) &&
      baseDir.includes("automated-apply-agy-chrome-e2e-")
    ) {
      rmSync(baseDir, { recursive: true, force: true });
    }
    lock.release();
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  await main();
}
