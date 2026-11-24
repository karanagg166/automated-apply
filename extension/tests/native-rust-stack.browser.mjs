// Run only under the disposable Rust PostgreSQL harness.
import assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import {
  fixtureExecutable,
  copyNativeFixtureExtension,
  nativeFixtureRegistry,
} from "./browser-fixture-engine.mjs";

const [base, binary] = process.argv.slice(2);
const token = process.env.RUST_NATIVE_BROWSER_FIXTURE_TOKEN;
assert.match(base, /^http:\/\/127\.0\.0\.1:[1-9][0-9]{3,4}$/);
assert.ok(isAbsolute(binary) && binary.endsWith("/automated-apply-native"));
assert.equal(token, "0123456789abcdefghijklmnopqrstuvwxyzABCDEF");
const executablePath = fixtureExecutable(chromium);
const id = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const origin = `chrome-extension://${id}/`;
const portal = "https://www.naukri.com/fictional-fixture";
const directory = await mkdtemp(join(tmpdir(), "automated-apply-rust-brave-"));
let browser;
try {
  const profile = join(directory, "profile");
  const extension = join(directory, "extension");
  const host = copyNativeFixtureExtension(
    fileURLToPath(new URL("../dist", import.meta.url)),
    extension,
  );
  const manifestPath = join(extension, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.host_permissions = ["https://www.naukri.com/*"];
  await writeFile(manifestPath, JSON.stringify(manifest));
  await writeFile(
    join(directory, "automated-apply-native.private.env"),
    [
      `CHROME_EXTENSION_ID=${id}`,
      "CHROME_NATIVE_MESSAGING_ENABLED=true",
      `JOB_AGENT_API_TOKEN=${token}`,
      `LOCAL_AGENT_ENDPOINT=${base}`,
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
  const bridge = join(directory, "automated-apply-native");
  await cp(binary, bridge);
  const registry = nativeFixtureRegistry(profile);
  const hosts = registry.directory;
  await mkdir(hosts, { recursive: true, mode: 0o700 });
  await writeFile(
    join(hosts, `${host}.json`),
    JSON.stringify({
      name: host,
      description: "Disposable Rust browser fixture",
      type: "stdio",
      path: bridge,
      allowed_origins: [origin],
    }),
    { mode: 0o600 },
  );
  const launch = () =>
    chromium.launchPersistentContext(profile, {
      executablePath,
      env: registry.env,
      headless: true,
      timeout: 20_000,
      args: [
        `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`,
        "--disable-background-networking",
        "--host-resolver-rules=MAP * ~NOTFOUND",
      ],
    });
  browser = await launch();
  let portalReads = 0;
  await browser.route("https://**/*", async (route) => {
    const request = route.request();
    if (request.url() !== portal || request.method() !== "GET")
      return route.abort();
    portalReads++;
    await route.fulfill({
      contentType: "text/html",
      body: "<button>Sign out</button>",
    });
  });
  const owner = async (path, body) => {
    const response = await fetch(`${base}/api/v1/${path}`, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(3000),
    });
    assert.ok(response.ok, `fixture owner API returned ${response.status}`);
    return response.json();
  };
  const popup = await browser.newPage();
  await popup.goto(`${origin}popup.html`);
  const nativeHealth = await popup.evaluate(async (fixtureHost) => {
    try {
      return await chrome.runtime.sendNativeMessage(fixtureHost, {
        version: 1,
        request_id: crypto.randomUUID(),
        command: "health",
      });
    } catch (error) {
      return { ok: false, error_code: error.message };
    }
  }, host);
  assert.equal(nativeHealth.ok, true, nativeHealth.error_code);
  const send = (message) =>
    popup.evaluate((input) => chrome.runtime.sendMessage(input), message);
  const connect = await send({
    command: "chrome_profile",
    action: "connect",
    label: "Fictional Brave",
  });
  assert.equal(connect.ok, true, connect.error_code);
  assert.equal(connect.commandsEnabled, false);
  const attemptStatus = () =>
    send({ command: "naukri_queue", action: "status" });
  assert.equal((await attemptStatus()).error_code, "PROFILE_NOT_SELECTED");
  await owner("browser/chrome-profiles/select", {
    expected_version: 0,
    profile_binding_id: connect.id,
  });
  const status = await attemptStatus();
  assert.equal(status.ok, true, status.error_code);
  assert.equal(status.queue.state, "STOPPED");
  assert.equal(status.queue.revision, 162);
  const start = await send({
    command: "naukri_queue",
    action: "start",
    revision: 162,
  });
  assert.equal(start.error_code, "PROFILE_COMMANDS_DISABLED");
  assert.deepEqual((await attemptStatus()).queue, status.queue);
  const listing = await browser.newPage();
  await listing.goto(portal);
  await listing.bringToFront();
  const observed = await send({ command: "observe_portal_session" });
  assert.equal(observed.ok, true, observed.error_code);
  assert.equal(observed.data.selected_profile_observation, true);
  assert.equal(observed.data.identity_verified, false);
  const saved = (await owner("local-agent/platforms")).find(
    (row) => row.platform === "naukri",
  );
  assert.equal(saved.session_evidence, "current_selected_profile");
  assert.equal(saved.state, "browser_session_observed");
  assert.equal(saved.submission, "unsupported");
  assert.equal(portalReads, 1);

  const heartbeat = (page) =>
    page.evaluate(() =>
      chrome.runtime.sendMessage({
        command: "chrome_profile",
        action: "status",
      }),
    );
  const original = await heartbeat(popup);
  assert.equal(original.ok, true, original.error_code);
  assert.equal(original.profile.status, "CONNECTED");
  assert.equal(original.id, connect.id);
  await listing.close();
  await browser.close();

  browser = await launch();
  const reopened = await browser.newPage();
  await reopened.goto(`${origin}popup.html`);
  const restored = await heartbeat(reopened);
  assert.equal(restored.ok, true, restored.error_code);
  assert.equal(restored.id, original.id);
  assert.equal(restored.profile.selected, true);
  assert.equal(restored.profile.status, "CONNECTED");
  assert.equal(restored.commandsEnabled, false);
  assert.notEqual(
    restored.profile.browser_session_id,
    original.profile.browser_session_id,
  );
  assert.ok(restored.profile.browser_session_id);
  const afterRestart = await reopened.evaluate(() =>
    chrome.runtime.sendMessage({ command: "naukri_queue", action: "status" }),
  );
  assert.equal(afterRestart.ok, true, afterRestart.error_code);
  assert.deepEqual(afterRestart.queue, status.queue);
  console.log(
    JSON.stringify({
      fixture: "brave_rust_native_stack",
      status: "PASS",
      browser_restart_reconnected_under_stop: true,
      live_actions: false,
    }),
  );
} finally {
  if (browser) await browser.close();
  await rm(directory, { recursive: true, force: true });
}
