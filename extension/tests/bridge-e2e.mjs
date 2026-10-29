// Chrome events are simulated. Native Python, loopback API and PostgreSQL are real.
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
const [python, envFile, extensionId] = process.argv.slice(2);
let click, stored;
global.chrome = {
  alarms: { onAlarm: { addListener() {} } },
  runtime: {
    id: extensionId,
    onInstalled: { addListener() {} },
    onStartup: { addListener() {} },
    onMessage: { addListener() {} },
    sendNativeMessage: async (_host, command) =>
      new Promise((resolve, reject) => {
        const child = spawn(
          python,
          [
            "-m",
            "backend.app.local_agent.native_host",
            envFile,
            `chrome-extension://${extensionId}/`,
          ],
          { stdio: ["pipe", "pipe", "ignore"] },
        );
        const timer = setTimeout(() => {
          child.kill();
          reject(new Error("native bridge timeout"));
        }, 25000);
        const payload = Buffer.from(JSON.stringify(command));
        const header = Buffer.alloc(4);
        header.writeUInt32LE(payload.length);
        child.stdin.write(Buffer.concat([header, payload]));
        // Intentionally leave stdin open, matching Chrome's native messaging behavior.
        let output = Buffer.alloc(0);
        child.stdout.on("data", (chunk) => {
          output = Buffer.concat([output, chunk]);
          if (
            output.length >= 4 &&
            output.length >= output.readUInt32LE(0) + 4
          ) {
            clearTimeout(timer);
            child.stdin.end();
            resolve(JSON.parse(output.subarray(4, output.readUInt32LE(0) + 4)));
          }
        });
        child.on("error", reject);
        child.on("exit", (code) => {
          if (code) {
            clearTimeout(timer);
            reject(new Error("native exited"));
          }
        });
      }),
  },
  contextMenus: {
    removeAll: async () => {},
    create: (_value, callback) => callback?.(),
    onClicked: { addListener: (fn) => (click = fn) },
  },
  storage: {
    local: { get: async () => ({}) },
    session: {
      get: async () => ({}),
      set: async (value) => (stored = { ...stored, ...value }),
    },
  },
  action: { setBadgeText: async () => {}, openPopup: async () => {} },
};
const { menuId } = await import("../background.js");
await click(
  { menuItemId: menuId },
  {
    url: "https://docs.google.com/forms/d/fictional-phase1/viewform",
    title: "Fictional test form",
  },
);
assert.equal(stored.lastResult.ok, true);
assert.equal(stored.lastResult.data.submitted, false);
assert.equal(stored.lastResult.data.platform, "google_forms");
const health = await chrome.runtime.sendNativeMessage(
  "com.automated_apply.agent",
  { version: 1, request_id: crypto.randomUUID(), command: "health" },
);
assert.equal(health.ok, true);
assert.ok(health.data.endpoint.startsWith("http://127.0.0.1:"));
console.log(JSON.stringify(stored.lastResult));
