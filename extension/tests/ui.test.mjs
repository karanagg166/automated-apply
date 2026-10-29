import assert from "node:assert/strict";
import test from "node:test";

test("popup renders bounded error codes and coalesces rapid button clicks", async () => {
  const elements = {
    "#prepare-answers": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
    "#answer-status": { textContent: "" },
    "#inspect-form": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
    "#fill-form": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
    "#form-plan": { textContent: "" },
    "#application-id": { value: "" },
    "#status": { textContent: "", addEventListener() {} },
    "#result": { textContent: "", addEventListener() {} },
    "#menu-status": { textContent: "", addEventListener() {} },
    "#observation": { textContent: "", addEventListener() {} },
    "#repair": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
    "#preview": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
    "#observe": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
  };
  let sessionStore = {
    lastResult: {
      ok: false,
      error_code: "Hostile <script> text not a valid code",
    },
    menuStatus: { registered: true },
    lastObservation: { ok: false, error_code: "backend_offline" },
  };
  let messageCalls = 0;
  let resolvePreview;
  global.document = { querySelector: (sel) => elements[sel] };
  global.chrome = {
    storage: {
      session: { get: async () => sessionStore },
      onChanged: { addListener() {} },
    },
    runtime: {
      id: "gdjbmkffcpicbpiikcohlmokkmcpipgp",
      sendMessage: async (msg) => {
        messageCalls += 1;
        if (msg.command === "preview_active_tab") {
          await new Promise((r) => {
            resolvePreview = r;
          });
          sessionStore.lastResult = {
            ok: true,
            data: { url: "https://example.org/apply", submitted: false },
          };
          return sessionStore.lastResult;
        }
        if (msg.command === "observe_portal_session") {
          return {
            ok: true,
            data: {
              observation: "signed_in_indicator",
              state: "browser_session_observed",
              api_connected: false,
              identity_verified: false,
            },
          };
        }
        return { registered: true };
      },
    },
  };
  try {
    await import("../popup.js");
    // Arbitrary non-code strings are sanitized to native_protocol_error
    assert.equal(elements["#status"].textContent, "native_protocol_error");
    assert.match(elements["#observation"].textContent, /backend is offline/);
    assert.match(
      elements["#menu-status"].textContent,
      /Right-click menu registered/,
    );

    await elements["#inspect-form"].listeners.click({ isTrusted: false });
    await elements["#fill-form"].listeners.click({ isTrusted: false });
    assert.equal(messageCalls, 0);

    // Concurrent clicks on #preview while in-flight dispatch only once
    const firstClick = elements["#preview"].listeners.click();
    const secondClick = elements["#preview"].listeners.click();
    assert.equal(messageCalls, 1);
    resolvePreview();
    await Promise.all([firstClick, secondClick]);
    assert.match(elements["#status"].textContent, /URL preview saved/);

    await elements["#observe"].listeners.click();
    assert.match(
      elements["#observation"].textContent,
      /indicator was observed and saved/,
    );
  } finally {
    delete global.document;
  }
});

test("settings validates health response schema, endpoint format, and error code bounds", async () => {
  const elements = {
    "#identity": { textContent: "" },
    "#version": { textContent: "" },
    "#guard-permission": { textContent: "" },
    "#profile-label": { value: "Fictional profile" },
    "#profile-status": { textContent: "" },
    "#profile-connect": { addEventListener() {} },
    "#profile-disconnect": { addEventListener() {} },
    "#profile-commands": { checked: false, addEventListener() {} },
    "#endpoint": { textContent: "" },
    "#check": {
      listeners: {},
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
    },
  };
  let nativeHandler;
  global.document = { querySelector: (sel) => elements[sel] };
  global.chrome = {
    permissions: { contains: async () => true },
    runtime: {
      id: "gdjbmkffcpicbpiikcohlmokkmcpipgp",
      getManifest: () => ({ version: "1.3.1" }),
      sendMessage: async () => ({ ok: true, connected: false }),
      sendNativeMessage: async (_host, req) => nativeHandler(req),
    },
  };
  try {
    await import("../settings.js");
    assert.equal(
      elements["#identity"].textContent,
      "Extension ID: gdjbmkffcpicbpiikcohlmokkmcpipgp",
    );
    assert.equal(elements["#version"].textContent, "Version: 1.3.1");
    assert.match(
      elements["#guard-permission"].textContent,
      /permission: granted/,
    );

    // Valid loopback endpoint
    nativeHandler = (req) => ({
      version: 1,
      request_id: req.request_id,
      ok: true,
      data: { endpoint: "http://127.0.0.1:18091" },
    });
    await elements["#check"].listeners.click();
    assert.equal(
      elements["#endpoint"].textContent,
      "Active endpoint: http://127.0.0.1:18091",
    );

    // Non-loopback endpoint rejected
    nativeHandler = (req) => ({
      version: 1,
      request_id: req.request_id,
      ok: true,
      data: { endpoint: "https://evil.example:8000" },
    });
    await elements["#check"].listeners.click();
    assert.equal(
      elements["#endpoint"].textContent,
      "Connection pending: backend not ready",
    );

    // Valid error code
    nativeHandler = () => ({
      version: 1,
      ok: false,
      error_code: "backend_offline",
    });
    await elements["#check"].listeners.click();
    assert.equal(
      elements["#endpoint"].textContent,
      "Connection pending: backend_offline",
    );

    // Missing data / malformed schema
    nativeHandler = () => ({ version: 2, ok: true });
    await elements["#check"].listeners.click();
    assert.equal(
      elements["#endpoint"].textContent,
      "Connection pending: native_protocol_error",
    );
    global.chrome.permissions.contains = async () => false;
    await elements["#check"].listeners.click();
    assert.match(
      elements["#guard-permission"].textContent,
      /permission: missing/,
    );
    global.chrome.permissions.contains = async () => {
      throw Error("unavailable");
    };
    await elements["#check"].listeners.click();
    assert.match(
      elements["#guard-permission"].textContent,
      /permission: unverified/,
    );
  } finally {
    delete global.document;
  }
});
