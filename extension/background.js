const host = "com.automated_apply.agent";
export const menuId = "automated-apply-preview";
import { preview, supportedUrl, normalizePreviewUrl, nativeErrorCode, setNativeTimeoutForTesting } from "./preview.js";
import { sessionIndicator } from "./session-indicator.js";
export const answerMenuId = "automated-apply-answer-fields";
export { sessionIndicator } from "./session-indicator.js";
export { preview, supportedUrl, normalizePreviewUrl, nativeErrorCode, setNativeTimeoutForTesting } from "./preview.js";
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
let registering;
async function register() {
  if (registering) return registering;
  registering = (async () => {
    try {
      await chrome.contextMenus.removeAll();
      await new Promise((resolve, reject) => chrome.contextMenus.create({
        id: answerMenuId, title: "Answer unanswered fields with Automated Apply", contexts: ["page", "editable", "selection"],
        documentUrlPatterns: ["https://*/*"],
      }, () => chrome.runtime.lastError ? reject(new Error("context_menu_registration_failed")) : resolve()));
      await new Promise((resolve, reject) => chrome.contextMenus.create({
        id: menuId, title: "Preview with Automated Apply", contexts: ["page", "link", "editable", "selection"],
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
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === answerMenuId) {
    // Opening the popup preserves its trusted-click answer/review/fill flow.
    await chrome.storage.session.set({ answerRequested: { tabId: tab?.id, url: tab?.url } });
    try { await chrome.action.openPopup?.(); } catch { /* Toolbar opens the same workflow. */ }
    return;
  }
  if (info.menuItemId !== menuId) return;
  // Open while the actual context-menu user gesture is still active.
  const popup = Promise.resolve().then(() => chrome.action.openPopup?.()).catch(() => {});
  await preview(tab, info.linkUrl || tab?.url || info.pageUrl);
  await popup;
});
export function portalHost(value) {
  if (!supportedUrl(value)) return false;
  const hostname = new URL(value).hostname.toLowerCase();
  return ["naukri.com", "wellfound.com", "instahyre.com", "workatastartup.com", "internshala.com"].some(domain => hostname === domain || hostname === `www.${domain}`);
}
const activeObservations = new Map();
// Executes only after a popup button gesture, in the isolated world of the top frame.
// Return fixed indicators only: no page text, form values, cookies or account identity.
export async function observeSession(tab) {
  const key = `${tab?.id ?? "unknown"}:${tab?.url ?? ""}`;
  const inFlight = activeObservations.get(key);
  if (inFlight) return inFlight;
  const promise = performObserveSession(tab);
  activeObservations.set(key, promise);
  try {
    return await promise;
  } finally {
    if (activeObservations.get(key) === promise) activeObservations.delete(key);
  }
}
async function performObserveSession(tab) {
  let result;
  if (!portalHost(tab?.url) || !Number.isInteger(tab?.id)) {
    result = { ok: false, error_code: "unsupported_portal_page" };
  } else {
    try {
      const observations = await chrome.scripting.executeScript({ target: { tabId: tab.id, frameIds: [0] }, world: "ISOLATED", func: sessionIndicator });
      const [current] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (current?.id !== tab.id || current?.url !== tab.url) throw new Error("page changed");
      if (!Array.isArray(observations) || observations.length !== 1 || !["signed_in_indicator", "login_required", "unverifiable"].includes(observations[0]?.result)) {
        throw new Error("invalid observation");
      }
      const url = new URL(tab.url);
      const request = { version: 1, request_id: crypto.randomUUID(), command: "observe_platform_session", url: url.origin + url.pathname, observation: observations[0].result };
      let timer;
      try {
        result = await Promise.race([
          chrome.runtime.sendNativeMessage(host, request),
          new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 45000); }),
        ]);
      } catch (nativeErr) {
        const code = nativeErrorCode(nativeErr);
        result = { ok: false, error_code: code === "native_host_unavailable" ? "session_observation_unavailable" : code };
        await chrome.storage.session.set({ lastObservation: result });
        return result;
      } finally {
        clearTimeout(timer);
      }
      if (result?.version !== 1 || typeof result.ok !== "boolean") throw new Error("invalid result");
      if (result.ok) {
        if (result.request_id !== request.request_id || result.data?.api_connected !== false || result.data?.identity_verified === true) {
          throw new Error("invalid result");
        }
      } else {
        if ((result.request_id && result.request_id !== request.request_id) || typeof result.error_code !== "string" || !ERROR_CODE_PATTERN.test(result.error_code)) {
          throw new Error("invalid result");
        }
      }
    } catch {
      result = { ok: false, error_code: "session_observation_unavailable" };
    }
  }
  await chrome.storage.session.set({ lastObservation: result });
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  const isExtensionPage = typeof sender.url === "string" && sender.url.startsWith(`chrome-extension://${chrome.runtime.id}/`);
  if (sender.id !== chrome.runtime.id || (sender.tab && !isExtensionPage)) return false;
  if (message?.command === "repair_context_menu") {
    register().then(reply).catch(() => reply({ registered: false, error_code: "context_menu_registration_failed" }));
    return true;
  }
  if (message?.command === "observe_portal_session") {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => observeSession(tab))
      .then(reply)
      .catch(() => reply({ ok: false, error_code: "session_observation_unavailable" }));
    return true;
  }
  if (message?.command !== "preview_active_tab") return false;
  chrome.tabs.query({ active: true, currentWindow: true })
    .then(([tab]) => preview(tab))
    .then(reply)
    .catch(() => reply({ version: 1, ok: false, error_code: "native_host_unavailable", data: { status: "Check host installation and local backend; retry from this page." } }));
  return true;
});
