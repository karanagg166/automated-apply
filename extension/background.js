const host = "com.automated_apply.agent";
export const menuId = "automated-apply-preview";
export function supportedUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch { return false; }
}
async function register() {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({ id: menuId, title: "Apply with Automated Apply", contexts: ["page", "link"] });
}
chrome.runtime.onInstalled.addListener(register);
chrome.runtime.onStartup.addListener(register);
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
  } catch {
    result = { ok: false, error_code: "native_host_unavailable", data: { status: "Check host installation and local backend; retry from this page." } };
  }
  clearTimeout(timer);
  // Session-only result, not exposed to pages or saved in synchronized storage.
  await chrome.storage.session.set({ lastResult: result });
  await chrome.action.setBadgeText({ text: result.ok ? "OK" : "!" });
  return result;
}
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== menuId) return;
  await preview(tab, info.linkUrl || tab?.url);
  // Chrome permits openPopup in modern MV3. Badge/storage still work if it declines.
  await chrome.action.openPopup().catch(() => {});
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.tab || message?.command !== "preview_active_tab") return false;
  chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => preview(tab)).then(reply);
  return true;
});
