// Real MV3 DNR against a real loopback fictional employer HTTP server.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, cp, readFile, writeFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
const root = resolve(new URL("../../", import.meta.url).pathname),
  id = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const requests = [];
let context;
const server = createServer((req, res) => {
  requests.push({ method: req.method, path: req.url });
  res.writeHead(200, { "content-type": "text/html" });
  res.end(
    '<title>Fictional guarded employer</title><form action="/submitted" method="post"><input name="answer" value="fictional"><button type="submit">Submit</button></form>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const temp = await mkdtemp(join(tmpdir(), "automated-apply-phase52-guard-"));
try {
  const extension = join(temp, "extension");
  await cp(join(root, "extension/dist"), extension, { recursive: true });
  const manifest = JSON.parse(
    await readFile(join(extension, "manifest.json"), "utf8"),
  );
  assert.equal(manifest.optional_permissions, undefined);
  assert.ok(manifest.permissions.includes("declarativeNetRequest"));
  assert.equal(manifest.host_permissions, undefined);
  // Minimal test driver does not load the popup or make any native-host request.
  await writeFile(
    join(extension, "guard-driver.html"),
    "<!doctype html><title>Fictional guard driver</title>",
  );
  context = await chromium.launchPersistentContext(join(temp, "profile"), {
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const driver = await context.newPage();
  await driver.goto(`chrome-extension://${id}/guard-driver.html`);
  const page = await context.newPage();
  await page.goto(origin);
  await page.bringToFront();
  const tabId = await driver.evaluate(
    async () =>
      (await chrome.tabs.query({ active: true, currentWindow: true }))[0].id,
  );
  await driver.evaluate(async (tabId) => {
    const mod = await import(chrome.runtime.getURL("network-guard.js"));
    await mod.installGuard(chrome, tabId);
  }, tabId);
  const blocked = await page.evaluate(async () => {
    const outcomes = [];
    for (const method of ["GET", "POST"]) {
      try {
        await fetch("/attempt-" + method, { method });
        outcomes.push(false);
      } catch {
        outcomes.push(true);
      }
    }
    return outcomes;
  });
  assert.deepEqual(blocked, [true, true]);
  assert.equal(
    requests.some((request) => request.path.startsWith("/attempt")),
    false,
  );
  // A different application tab keeps ordinary networking, even at the same origin.
  const peer = await context.newPage();
  await peer.goto(origin + "/peer");
  await peer.evaluate(
    async () => await fetch("/peer-write", { method: "POST" }),
  );
  assert.ok(requests.some((request) => request.path === "/peer-write"));
  const session = await context.browser().newBrowserCDPSession();
  const targets = await session.send("Target.getTargets");
  const worker = targets.targetInfos.find(
    (target) => target.type === "service_worker" && target.url.includes(id),
  );
  if (worker)
    await session.send("Target.closeTarget", { targetId: worker.targetId });
  assert.equal(
    await driver.evaluate(
      async (tabId) =>
        await (
          await import(chrome.runtime.getURL("network-guard.js"))
        ).guardActive(chrome, tabId),
      tabId,
    ),
    true,
  );
  await page.evaluate(() => document.querySelector("form").submit());
  await page.waitForTimeout(300);
  assert.equal(
    requests.some((request) => request.path === "/submitted"),
    false,
  );
  await driver.evaluate(
    async (tabId) =>
      await (
        await import(chrome.runtime.getURL("network-guard.js"))
      ).releaseGuard(chrome, tabId),
    tabId,
  );
  await page.goto(origin + "/manual-control");
  await page.evaluate(
    async () => await fetch("/manual-write", { method: "POST" }),
  );
  assert.ok(requests.some((request) => request.path === "/manual-write"));
  assert.equal(
    await driver.evaluate(
      async (tabId) =>
        await (
          await import(chrome.runtime.getURL("network-guard.js"))
        ).guardActive(chrome, tabId),
      tabId,
    ),
    false,
  );
  console.log(
    JSON.stringify({
      cases: 5,
      scope: "production MV3 manifest/DNR and controlled loopback HTTP server",
      blocked_get: true,
      blocked_post: true,
      blocked_direct_form_submit: true,
      worker_restart_keeps_guard: true,
      unrelated_tab_unaffected: true,
      explicit_release_restores_network: true,
      genuine_submissions: 0,
    }),
  );
} finally {
  await context?.close();
  await new Promise((resolve) => server.close(resolve));
  await rm(temp, { recursive: true, force: true });
}
