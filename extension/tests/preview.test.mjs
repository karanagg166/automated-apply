import assert from "node:assert/strict";
import test from "node:test";
const callbacks = {};
let stored, lastBadge;
global.chrome = {
  alarms: { onAlarm: { addListener() {} } },
  runtime: {
    id: "a".repeat(32),
    onInstalled: { addListener: (fn) => (callbacks.install = fn) },
    onStartup: { addListener() {} },
    onMessage: { addListener: (fn) => (callbacks.message = fn) },
    sendNativeMessage: async (host, request) => {
      assert.equal(host, "com.automated_apply.agent");
      return {
        version: 1,
        request_id: request.request_id,
        ok: true,
        data: { url: request.url, submitted: false },
      };
    },
  },
  contextMenus: {
    removeAll: async () => {},
    create: (value, callback) => {
      callbacks.menu = value;
      callback?.();
    },
    onClicked: { addListener: (fn) => (callbacks.click = fn) },
  },
  storage: {
    local: { get: async () => ({}), set: async () => {} },
    session: {
      get: async () => ({}),
      set: async (value) => (stored = { ...stored, ...value }),
    },
  },
  tabs: {
    onUpdated: { addListener() {} },
    onCreated: { addListener() {} },
    onRemoved: { addListener() {} },
    onActivated: { addListener() {} },
  },
  action: {
    setBadgeText: async (val) => {
      lastBadge = val?.text;
    },
    openPopup: async () => {},
  },
};
const {
  preview,
  menuId,
  answerMenuId,
  supportedUrl,
  normalizePreviewUrl,
  nativeErrorCode,
  portalHost,
  observeSession,
  sessionIndicator,
  setNativeTimeoutForTesting,
} = await import("../background.js");
test("answer context-menu gesture opens review without filling or native dispatch", async () => {
  const previous = stored?.lastResult;
  await callbacks.click(
    { menuItemId: answerMenuId },
    { id: 7, url: "https://example.org/apply" },
  );
  assert.deepEqual(stored.answerRequested, {
    tabId: 7,
    url: "https://example.org/apply",
  });
  assert.equal(stored.lastResult, previous);
});
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
  const status = await new Promise((resolve) =>
    callbacks.message(
      { command: "repair_context_menu" },
      { id: chrome.runtime.id },
      resolve,
    ),
  );
  assert.equal(status.registered, true);
});
test("context click preserves selected URL and preview-only result", async () => {
  await callbacks.click(
    {
      menuItemId: menuId,
      linkUrl: "https://docs.google.com/forms/d/fictional/viewform",
    },
    { title: "Fictional form" },
  );
  assert.equal(
    stored.lastResult.data.url,
    "https://docs.google.com/forms/d/fictional/viewform",
  );
  assert.equal(stored.lastResult.data.submitted, false);
  assert.equal(lastBadge, "OK");
});
test("unsupported chrome/file/http/private/oversized URLs never reach native host", async () => {
  const badUrls = [
    "chrome://extensions",
    "file:///private",
    "http://example.org",
    "https://user:pass@example.org/",
    "https://localhost/apply",
    "https://127.0.0.1/apply",
    "https://10.0.0.1/apply",
    "https://192.168.1.1/apply",
    "https://172.16.0.1/apply",
    "https://169.254.169.254/apply",
    "https://[::1]/apply",
    "https://example.internal/apply",
    "https://example.local/apply",
    "https://example.localhost/apply",
    "https://example.localdomain/apply",
    "https://example.org:8443/apply",
    "https://example.org/%0aexecute",
    "https://example.org/%5cexecute",
    "https://example.org/%E0%A4%A",
    "https://example.org/" + "a".repeat(2040),
  ];
  for (const url of badUrls) {
    assert.equal(supportedUrl(url), false, `expected ${url} to be unsupported`);
    const res = await preview({ url });
    assert.equal(res.error_code, "unsupported_page");
    assert.equal(lastBadge, "!");
  }
});
test("context click falls back to pageUrl when tab.url is absent", async () => {
  await callbacks.click(
    { menuItemId: menuId, pageUrl: "https://example.org/fallback-page" },
    { id: 77, title: "Fallback" },
  );
  assert.equal(stored.lastResult.data.url, "https://example.org/fallback-page");
});
test("Google Forms redirect wrappers unwrap to target form URL and reject unsafe redirect targets", async () => {
  const formUrl =
    "https://docs.google.com/forms/d/e/1FAIpQLSf_fictional/viewform";
  const googleRedirect =
    "https://www.google.com/url?q=" + encodeURIComponent(formUrl) + "&sa=D";
  const shortRedirect =
    "https://google.com/url?url=" +
    encodeURIComponent("https://forms.gle/fictional123");
  const signInRedirect =
    "https://accounts.google.com/v3/signin/identifier?continue=" +
    encodeURIComponent(formUrl);
  assert.equal(normalizePreviewUrl(googleRedirect), formUrl);
  assert.equal(
    normalizePreviewUrl(shortRedirect),
    "https://forms.gle/fictional123",
  );
  assert.equal(normalizePreviewUrl(signInRedirect), formUrl);
  const res = await preview({
    id: 501,
    url: googleRedirect,
    title: "Redirected Form",
  });
  assert.equal(res.ok, true);
  assert.equal(res.data.url, formUrl);
  for (const unsafeRedirect of [
    "https://www.google.com/url?q=" +
      encodeURIComponent("http://127.0.0.1:8000/admin"),
    "https://www.google.com/url?q=" +
      encodeURIComponent("https://localhost/internal"),
    "https://www.google.com/url?q=" + encodeURIComponent(googleRedirect),
    "https://www.google.com/url",
    "https://accounts.google.com/ServiceLogin?continue=" +
      encodeURIComponent("https://example.org/not-a-form"),
  ]) {
    assert.equal(supportedUrl(unsafeRedirect), false);
    assert.equal(
      (await preview({ url: unsafeRedirect })).error_code,
      "unsupported_page",
    );
  }
});
test("duplicate simultaneous gestures perform one native preview", async () => {
  const original = chrome.runtime.sendNativeMessage;
  let calls = 0;
  chrome.runtime.sendNativeMessage = async (_host, request) => {
    calls += 1;
    await new Promise((resolve) => setTimeout(resolve, 10));
    return {
      version: 1,
      request_id: request.request_id,
      ok: true,
      data: { submitted: false },
    };
  };
  try {
    const tab = { id: 987, url: "https://example.org/duplicate-gesture" };
    const results = await Promise.all([preview(tab), preview(tab)]);
    assert.equal(calls, 1);
    assert.equal(results[0].request_id, results[1].request_id);
  } finally {
    chrome.runtime.sendNativeMessage = original;
  }
});
test("backend/host offline is explicit and recoverable", async () => {
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async () => {
    throw new Error("offline");
  };
  assert.equal(
    (await preview({ url: "https://example.org/apply" })).error_code,
    "native_host_unavailable",
  );
  chrome.runtime.sendNativeMessage = original;
  assert.equal((await preview({ url: "https://example.org/apply" })).ok, true);
});
test("native host timeout and malformed native responses fail closed", async () => {
  const original = chrome.runtime.sendNativeMessage;
  try {
    setNativeTimeoutForTesting(25);
    chrome.runtime.sendNativeMessage = async () => new Promise(() => {});
    const timedOut = await preview({
      id: 301,
      url: "https://example.org/timeout-test",
    });
    assert.equal(timedOut.ok, false);
    assert.equal(timedOut.error_code, "native_host_timeout");

    setNativeTimeoutForTesting(45000);
    for (const badReply of [
      null,
      { version: 2, ok: true },
      { version: 1, ok: false, error_code: "bad code with spaces!" },
      { version: 1, ok: false },
      { version: 1, request_id: "wrong", ok: true, data: { submitted: false } },
      { version: 1, ok: true, data: { submitted: true } },
    ]) {
      chrome.runtime.sendNativeMessage = async (_host, req) =>
        badReply && badReply.ok && !badReply.request_id
          ? { ...badReply, request_id: req.request_id }
          : badReply;
      const invalid = await preview({
        id: 302,
        url: "https://example.org/malformed",
      });
      assert.equal(invalid.ok, false);
      assert.equal(invalid.error_code, "native_protocol_error");
    }
  } finally {
    setNativeTimeoutForTesting(45000);
    chrome.runtime.sendNativeMessage = original;
  }
});
test("a slow native request remains coalesced after the debounce window", async () => {
  const original = chrome.runtime.sendNativeMessage;
  const originalNow = Date.now;
  let calls = 0,
    finish;
  chrome.runtime.sendNativeMessage = async (_host, request) => {
    calls += 1;
    await new Promise((resolve) => {
      finish = resolve;
    });
    return {
      version: 1,
      request_id: request.request_id,
      ok: true,
      data: { submitted: false },
    };
  };
  try {
    const tab = { id: 1234, url: "https://example.org/slow-preview" };
    Date.now = () => 1000;
    const first = preview(tab);
    Date.now = () => 6000;
    const second = preview(tab);
    assert.equal(calls, 1);
    finish();
    assert.equal((await first).request_id, (await second).request_id);
  } finally {
    Date.now = originalNow;
    chrome.runtime.sendNativeMessage = original;
  }
});
test("page sender cannot invoke extension entry point", () => {
  assert.equal(
    callbacks.message(
      { command: "preview_active_tab" },
      { id: chrome.runtime.id, tab: { id: 1 } },
      () => {},
    ),
    false,
  );
  assert.equal(
    callbacks.message(
      { command: "preview_active_tab" },
      { id: "evil" },
      () => {},
    ),
    false,
  );
});
test("reports native registration and origin errors without exposing arbitrary messages", () => {
  assert.equal(
    nativeErrorCode(new Error("Specified native messaging host not found.")),
    "native_host_not_found",
  );
  assert.equal(
    nativeErrorCode(
      new Error("Access to the specified native messaging host is forbidden."),
    ),
    "native_origin_not_authorized",
  );
  assert.equal(
    nativeErrorCode(new Error("Failed to start native messaging host.")),
    "native_host_start_failed",
  );
  assert.equal(
    nativeErrorCode(
      new Error("Error when communicating with the native messaging host."),
    ),
    "native_host_exited",
  );
});
test("portal observation is restricted to exact official hosts", () => {
  for (const url of [
    "https://www.naukri.com/mnjuser/profile",
    "https://wellfound.com/profile",
    "https://instahyre.com/",
  ])
    assert.equal(portalHost(url), true);
  const credentialPortal = [
    "https://",
    "user",
    ":",
    "password",
    "@wellfound.com/",
  ].join("");
  for (const url of [
    "https://naukri.com.evil.example/",
    "https://example.org/",
    credentialPortal,
    "http://wellfound.com/",
    "https://www.naukri.com:8443/profile",
  ])
    assert.equal(portalHost(url), false);
});
test("page senders cannot request portal observations", () => {
  assert.equal(
    callbacks.message(
      { command: "observe_portal_session" },
      { id: chrome.runtime.id, tab: { id: 1 } },
      () => {},
    ),
    false,
  );
});
test("observation sends only a fixed indicator and redacted page URL, and coalesces concurrent checks", async () => {
  const original = chrome.runtime.sendNativeMessage;
  let scriptCalls = 0;
  let nativeCalls = 0;
  chrome.scripting = {
    executeScript: async (options) => {
      scriptCalls += 1;
      assert.deepEqual(options.target, { tabId: 1, frameIds: [0] });
      assert.equal(options.world, "ISOLATED");
      assert.equal(options.func, sessionIndicator);
      await new Promise((r) => setTimeout(r, 10));
      return [{ result: "signed_in_indicator" }];
    },
  };
  const tab = {
    id: 1,
    url: "https://www.naukri.com/mnjuser/profile?token=fictional#fragment",
  };
  chrome.tabs = { query: async () => [tab] };
  chrome.runtime.sendNativeMessage = async (_host, command) => {
    nativeCalls += 1;
    assert.equal(command.url, "https://www.naukri.com/mnjuser/profile");
    assert.equal(command.command, "observe_platform_session");
    assert.equal(command.observation, "signed_in_indicator");
    assert.equal(command.title, undefined);
    return {
      version: 1,
      request_id: command.request_id,
      ok: true,
      data: { state: "browser_session_observed", api_connected: false },
    };
  };
  try {
    const [first, second] = await Promise.all([
      observeSession(tab),
      observeSession(tab),
    ]);
    assert.equal(first.data.api_connected, false);
    assert.equal(second.data.api_connected, false);
    assert.equal(scriptCalls, 1);
    assert.equal(nativeCalls, 1);
  } finally {
    chrome.runtime.sendNativeMessage = original;
  }
});
test("observation preserves backend_offline and native host error codes", async () => {
  const original = chrome.runtime.sendNativeMessage;
  const tab = { id: 2, url: "https://wellfound.com/jobs" };
  chrome.scripting = {
    executeScript: async () => [{ result: "unverifiable" }],
  };
  chrome.tabs = { query: async () => [tab] };
  try {
    chrome.runtime.sendNativeMessage = async () => ({
      version: 1,
      ok: false,
      error_code: "backend_offline",
    });
    const offline = await observeSession(tab);
    assert.equal(offline.ok, false);
    assert.equal(offline.error_code, "backend_offline");

    chrome.runtime.sendNativeMessage = async () => {
      throw new Error("Specified native messaging host not found.");
    };
    const missingHost = await observeSession(tab);
    assert.equal(missingHost.ok, false);
    assert.equal(missingHost.error_code, "native_host_not_found");

    chrome.runtime.sendNativeMessage = async () => {
      throw new Error(
        "Access to the specified native messaging host is forbidden.",
      );
    };
    const forbidden = await observeSession(tab);
    assert.equal(forbidden.ok, false);
    assert.equal(forbidden.error_code, "native_origin_not_authorized");
  } finally {
    chrome.runtime.sendNativeMessage = original;
  }
});
test("navigation during observation fails closed before native dispatch", async () => {
  chrome.tabs = {
    query: async () => [{ id: 1, url: "https://wellfound.com/login" }],
  };
  const result = await observeSession({
    id: 1,
    url: "https://naukri.com/profile",
  });
  assert.equal(result.ok, false);
});
test("session indicator never exports page text or form values", () => {
  global.document = {
    querySelectorAll: (selector) =>
      selector.includes("input") ? [] : [{ getClientRects: () => [1] }],
  };
  assert.equal(sessionIndicator(), "signed_in_indicator");
  global.document.querySelectorAll = () => [];
  assert.equal(sessionIndicator(), "unverifiable");
  global.document.querySelectorAll = (selector) =>
    selector.includes("input") ? [{ getClientRects: () => [1] }] : [];
  assert.equal(sessionIndicator(), "login_required");
  delete global.document;
});

test("exact visible logout labels work without logout URLs and never accept page prose", () => {
  const element = (label, visible = true, extra = {}) => ({
    getClientRects: () => (visible ? [1] : []),
    getAttribute: (attr) => extra[attr] ?? null,
    innerText: label,
    ...extra,
  });
  try {
    for (const label of [
      "Logout",
      "Log out",
      "Log-out",
      "Sign out",
      "Sign-out",
      "SIGN OUT",
    ]) {
      global.document = {
        querySelectorAll: (selector) =>
          selector === 'a,button,[role="button"],[role="menuitem"]'
            ? [element(label)]
            : [],
      };
      assert.equal(sessionIndicator(), "signed_in_indicator");
    }
    global.document = {
      querySelectorAll: (selector) =>
        selector === 'a,button,[role="button"],[role="menuitem"]'
          ? [element("", true, { href: "/users/signout" })]
          : [],
    };
    assert.equal(sessionIndicator(), "signed_in_indicator");
    for (const candidate of [
      element("Logout", false),
      element("How to log out of your account"),
      { ...element("Logout"), checkVisibility: () => false },
    ]) {
      global.document = {
        querySelectorAll: (selector) =>
          selector === 'a,button,[role="button"],[role="menuitem"]'
            ? [candidate]
            : [],
      };
      assert.equal(sessionIndicator(), "unverifiable");
    }
    global.document = {
      querySelectorAll: (selector) =>
        selector.includes("input")
          ? [element("")]
          : selector === 'a,button,[role="button"],[role="menuitem"]'
            ? [element("Logout")]
            : [],
    };
    assert.equal(sessionIndicator(), "unverifiable");
  } finally {
    delete global.document;
  }
});
