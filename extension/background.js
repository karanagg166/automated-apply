const host = "com.automated_apply.agent";
export const menuId = "automated-apply-preview";
import { preview, supportedUrl } from "./preview.js";
import { sessionIndicator } from "./session-indicator.js";
export { sessionIndicator } from "./session-indicator.js";
export { preview, supportedUrl, nativeErrorCode } from "./preview.js";
let registering;
async function register() {
  if (registering) return registering;
  registering = (async () => {
    try {
      await chrome.contextMenus.removeAll();
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
