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
  contextMenus: { removeAll: async () => {}, create: (value, callback) => { callbacks.menu = value; callback?.(); }, onClicked: { addListener: (fn) => callbacks.click = fn } },
  storage: { session: { set: async (value) => stored = { ...stored, ...value } } },
  action: { setBadgeText: async () => {}, openPopup: async () => {} },
};
const { preview, menuId, supportedUrl, nativeErrorCode, portalHost, observeSession, sessionIndicator } = await import("../background.js");
test("registers exact menu label with page/link user gesture contexts", async () => {
  await callbacks.install();
  assert.equal(callbacks.menu.title, "Preview with Automated Apply");
  assert.equal(callbacks.menu.id, menuId);
  assert.ok(callbacks.menu.contexts.includes("editable"));
  assert.ok(callbacks.menu.contexts.includes("selection"));
  assert.deepEqual(callbacks.menu.documentUrlPatterns, ["https://*/*"]);
  assert.equal(stored.menuStatus.registered, true);
});
test("owner popup can repair the menu without backend commands", async () => {
  const status = await new Promise((resolve) => callbacks.message({ command: "repair_context_menu" }, { id: chrome.runtime.id }, resolve));
  assert.equal(status.registered, true);
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
test("duplicate simultaneous gestures perform one native preview", async () => {
  const original = chrome.runtime.sendNativeMessage;
  let calls = 0;
  chrome.runtime.sendNativeMessage = async (_host, request) => {
    calls += 1;
    await new Promise(resolve => setTimeout(resolve, 10));
    return { version: 1, request_id: request.request_id, ok: true, data: { submitted: false } };
  };
  try {
    const tab = { id: 987, url: "https://example.org/duplicate-gesture" };
    const results = await Promise.all([preview(tab), preview(tab)]);
    assert.equal(calls, 1);
    assert.equal(results[0].request_id, results[1].request_id);
  } finally { chrome.runtime.sendNativeMessage = original; }
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
test("reports native registration and origin errors without exposing arbitrary messages", () => {
  assert.equal(nativeErrorCode(new Error("Specified native messaging host not found.")), "native_host_not_found");
  assert.equal(nativeErrorCode(new Error("Access to the specified native messaging host is forbidden.")), "native_origin_not_authorized");
  assert.equal(nativeErrorCode(new Error("Failed to start native messaging host.")), "native_host_start_failed");
});
test("portal observation is restricted to exact official hosts", () => {
  for (const url of ["https://www.naukri.com/mnjuser/profile", "https://wellfound.com/profile", "https://instahyre.com/"]) assert.equal(portalHost(url), true);
  for (const url of ["https://naukri.com.evil.example/", "https://example.org/", "https://user:password@wellfound.com/", "http://wellfound.com/"]) assert.equal(portalHost(url), false); // pragma: allowlist secret -- rejected fictional credential URL
});
test("page senders cannot request portal observations", () => {
  assert.equal(callbacks.message({ command: "observe_portal_session" }, { id: chrome.runtime.id, tab: { id: 1 } }, () => {}), false);
});
test("observation sends only a fixed indicator and redacted page URL", async () => {
  const original = chrome.runtime.sendNativeMessage;
  chrome.scripting = { executeScript: async options => {
    assert.deepEqual(options.target, { tabId: 1, frameIds: [0] });
    assert.equal(options.world, "ISOLATED");
    assert.equal(options.func, sessionIndicator);
    return [{ result: "signed_in_indicator" }];
  } };
  const tab = { id: 1, url: "https://www.naukri.com/mnjuser/profile?token=fictional#fragment" };
  chrome.tabs = { query: async () => [tab] };
  chrome.runtime.sendNativeMessage = async (_host, command) => {
    assert.equal(command.url, "https://www.naukri.com/mnjuser/profile");
    assert.equal(command.command, "observe_platform_session");
    assert.equal(command.observation, "signed_in_indicator");
    assert.equal(command.title, undefined);
    return { version: 1, request_id: command.request_id, ok: true, data: { state: "browser_session_observed", api_connected: false } };
  };
  assert.equal((await observeSession(tab)).data.api_connected, false);
  chrome.runtime.sendNativeMessage = original;
});
test("navigation during observation fails closed before native dispatch", async () => {
  chrome.tabs = { query: async () => [{ id: 1, url: "https://wellfound.com/login" }] };
  const result = await observeSession({ id: 1, url: "https://naukri.com/profile" });
  assert.equal(result.ok, false);
});
test("session indicator never exports page text or form values", () => {
  global.document = { querySelectorAll: selector => selector.includes('input') ? [] : [{ getClientRects: () => [1] }] };
  assert.equal(sessionIndicator(), "signed_in_indicator");
  global.document.querySelectorAll = () => [];
  assert.equal(sessionIndicator(), "unverifiable");
  global.document.querySelectorAll = selector => selector.includes('input') ? [{ getClientRects: () => [1] }] : [];
  assert.equal(sessionIndicator(), "login_required");
  delete global.document;
});
