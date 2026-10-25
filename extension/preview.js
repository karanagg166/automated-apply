const host = "com.automated_apply.agent";
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
const previews = new Map();
export async function preview(tab, url = tab?.url) {
  const key = `${tab?.id ?? "unknown"}:${url}`;
  const previous = previews.get(key);
  if (previous && Date.now() - previous.started < 1500) return previous.promise;
  const promise = performPreview(tab, url);
  previews.set(key, { started: Date.now(), promise });
  try {
    const result = await promise;
    if (!result.ok) previews.delete(key);
    return result;
  }
  finally { setTimeout(() => { if (previews.get(key)?.promise === promise) previews.delete(key); }, 1500); }
}
async function performPreview(tab, url) {
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
      new Promise((_, reject) => timer = setTimeout(() => reject(new Error("timeout")), 45000)),
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
