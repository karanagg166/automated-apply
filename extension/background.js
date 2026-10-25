const host = "com.automated_apply.agent";
export const menuId = "automated-apply-preview";
export function nativeErrorCode(error) {
  const message = String(error?.message || error).toLowerCase();
  if (message.includes("host not found")) return "native_host_not_found";
  if (message.includes("forbidden")) return "native_origin_not_authorized";
  if (message.includes("failed to start")) return "native_host_start_failed";
  if (message.includes("host has exited")) return "native_host_exited";
  if (message.includes("timeout")) return "native_host_timeout";
  if (message.includes("schema") || message.includes("mismatch")) return "native_protocol_error";
  return "native_host_unavailable";
}
export function supportedUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch { return false; }
}
let registering;
async function register() {
  if (registering) return registering;
  registering = (async () => {
    try {
      await chrome.contextMenus.removeAll();
      await new Promise((resolve, reject) => chrome.contextMenus.create({
        id: menuId, title: "Apply with Automated Apply", contexts: ["page", "link", "editable", "selection"],
        documentUrlPatterns: ["https://*/*"],
      }, () => chrome.runtime.lastError ? reject(new Error("context_menu_registration_failed")) : resolve()));
      const status = { registered: true, error_code: null };
      await chrome.storage.session.set({ menuStatus: status });
      return status;
    } catch {
      const status = { registered: false, error_code: "context_menu_registration_failed" };
      await chrome.storage.session.set({ menuStatus: status });
      return status;
    }
  })().finally(() => { registering = null; });
  return registering;
}
chrome.runtime.onInstalled.addListener(register);
chrome.runtime.onStartup.addListener(register);
// Unpacked reloads/worker restarts must recover a missing menu as well.
void register();
export async function preview(tab, url = tab?.url) {
  if (!supportedUrl(url)) {
    const result = { ok: false, error_code: "unsupported_page", data: { status: "Use a public HTTPS application page." } };
    await chrome.storage.session.set({ lastResult: result });
    return result;
  }
  const request = { version: 1, request_id: crypto.randomUUID(), command: "preview_application_url", url, title: (tab?.title || "").slice(0, 250) };
  let result;
  let timer;
  try {
    result = await Promise.race([
      chrome.runtime.sendNativeMessage(host, request),
      new Promise((_, reject) => timer = setTimeout(() => reject(new Error("timeout")), 25000)),
    ]);
    if (result?.version !== 1 || typeof result?.ok !== "boolean") throw new Error("invalid native schema");
    if (result.ok && (result.request_id !== request.request_id || result.data?.submitted !== false)) throw new Error("invalid preview result");
    if (result.request_id && result.request_id !== request.request_id) throw new Error("mismatch");
  } catch (error) {
    result = { version: 1, ok: false, error_code: nativeErrorCode(error), data: { status: "Check host installation and local backend; retry from this page." } };
  }
  clearTimeout(timer);
  // Session-only result, not exposed to pages or saved in synchronized storage.
  await chrome.storage.session.set({ lastResult: result });
  await chrome.action.setBadgeText({ text: result.ok ? "OK" : "!" });
  return result;
}
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== menuId) return;
  // Open while the actual context-menu user gesture is still active.
  const popup = chrome.action.openPopup().catch(() => {});
  await preview(tab, info.linkUrl || tab?.url);
  await popup;
});
export function portalHost(value) {
  if (!supportedUrl(value)) return false;
  const host = new URL(value).hostname;
  return ["naukri.com", "wellfound.com", "instahyre.com", "workatastartup.com", "internshala.com"].some(domain => host === domain || host === `www.${domain}`);
}
// Executes only after a popup button gesture, in the isolated world of the top frame.
// Return fixed indicators only: no page text, form values, cookies or account identity.
export function sessionIndicator() {
  const visible = element => !!element?.getClientRects().length;
  const signedIn = [...document.querySelectorAll('a[href*="logout"],a[href*="sign_out"],button[data-action="logout"]')].some(visible);
  const password = [...document.querySelectorAll('input[type="password"]')].some(visible);
  return signedIn && !password ? "signed_in_indicator" : password && !signedIn ? "login_required" : "unverifiable";
}
export async function observeSession(tab) {
  let result;
  if (!portalHost(tab?.url) || !Number.isInteger(tab?.id)) {
    result = { ok: false, error_code: "unsupported_portal_page" };
  } else {
    try {
      const observations = await chrome.scripting.executeScript({ target: { tabId: tab.id, frameIds: [0] }, world: "ISOLATED", func: sessionIndicator });
      const [current] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (current?.id !== tab.id || current?.url !== tab.url) throw new Error("page changed");
      if (observations.length !== 1 || !["signed_in_indicator", "login_required", "unverifiable"].includes(observations[0].result)) throw new Error("invalid observation");
      const url = new URL(tab.url);
      const request = { version: 1, request_id: crypto.randomUUID(), command: "observe_platform_session", url: url.origin + url.pathname, observation: observations[0].result };
      result = await chrome.runtime.sendNativeMessage(host, request);
      if (result?.version !== 1 || result.request_id !== request.request_id || typeof result.ok !== "boolean" || (result.ok && result.data?.api_connected !== false)) throw new Error("invalid result");
    } catch {
      result = { ok: false, error_code: "session_observation_unavailable" };
    }
  }
  await chrome.storage.session.set({ lastObservation: result });
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.tab) return false;
  if (message?.command === "repair_context_menu") {
    register().then(reply);
    return true;
  }
  if (message?.command === "observe_portal_session") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => observeSession(tab)).then(reply);
    return true;
  }
  if (message?.command !== "preview_active_tab") return false;
  chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => preview(tab)).then(reply);
  return true;
});
