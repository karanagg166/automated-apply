import assert from "node:assert/strict";
import test from "node:test";
const callbacks = {};
let stored;
global.chrome = {
  runtime: { id: "a".repeat(32), onInstalled: { addListener: (fn) => callbacks.install = fn }, onStartup: { addListener() {} },
    onMessage: { addListener: (fn) => callbacks.message = fn },
    sendNativeMessage: async (host, request) => {
      assert.equal(host, "com.automated_apply.agent");
      return { version: 1, request_id: request.request_id, ok: true, data: { url: request.url, submitted: false } };
    } },
  contextMenus: { removeAll: async () => {}, create: (value) => callbacks.menu = value, onClicked: { addListener: (fn) => callbacks.click = fn } },
  storage: { session: { set: async (value) => stored = value } },
  action: { setBadgeText: async () => {}, openPopup: async () => {} },
};
const { preview, menuId, supportedUrl } = await import("../background.js");
test("registers exact menu label with page/link user gesture contexts", async () => {
  await callbacks.install();
  assert.equal(callbacks.menu.title, "Apply with Automated Apply");
  assert.equal(callbacks.menu.id, menuId);
});
test("context click preserves selected URL and preview-only result", async () => {
  await callbacks.click({ menuItemId: menuId, linkUrl: "https://docs.google.com/forms/d/fictional/viewform" }, { title: "Fictional form" });
  assert.equal(stored.lastResult.data.url, "https://docs.google.com/forms/d/fictional/viewform");
  assert.equal(stored.lastResult.data.submitted, false);
});
test("unsupported chrome/file/http URLs never reach native host", async () => {
  for (const url of ["chrome://extensions", "file:///private", "http://example.org", "https://user:pass@example.org/"]) {
    assert.equal(supportedUrl(url), false);
    assert.equal((await preview({ url })).error_code, "unsupported_page");
  }
});
test("backend/host offline is explicit and recoverable", async () => {
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async () => { throw new Error("offline"); };
  assert.equal((await preview({ url: "https://example.org/apply" })).error_code, "native_host_unavailable");
  chrome.runtime.sendNativeMessage = original;
  assert.equal((await preview({ url: "https://example.org/apply" })).ok, true);
});
test("page sender cannot invoke extension entry point", () => {
  assert.equal(callbacks.message({ command: "preview_active_tab" }, { id: chrome.runtime.id, tab: { id: 1 } }, () => {}), false);
  assert.equal(callbacks.message({ command: "preview_active_tab" }, { id: "evil" }, () => {}), false);
});
