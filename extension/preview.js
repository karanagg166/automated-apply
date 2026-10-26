const host = "com.automated_apply.agent";
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
let nativeTimeoutMs = 45000;
export function setNativeTimeoutForTesting(ms) {
  nativeTimeoutMs = Number.isFinite(ms) && ms > 0 ? ms : 45000;
}
export function nativeErrorCode(error) {
  const message = String(error?.message || error).toLowerCase();
  if (message.includes("host not found")) return "native_host_not_found";
  if (message.includes("forbidden")) return "native_origin_not_authorized";
  if (message.includes("failed to start")) return "native_host_start_failed";
  if (message.includes("host has exited") || message.includes("communicating with the native messaging host")) return "native_host_exited";
  if (message.includes("timeout")) return "native_host_timeout";
  if (message.includes("schema") || message.includes("mismatch") || message.includes("invalid preview result")) return "native_protocol_error";
  return "native_host_unavailable";
}
function isPrivateOrReservedIpv4(hostname) {
  if (!/^\d+(?:\.\d+){3}$/.test(hostname)) return /^\d+$/.test(hostname);
  const parts = hostname.split(".").map(Number);
  if (parts.some(n => !Number.isInteger(n) || n < 0 || n > 255)) return true;
  const [a, b, c] = parts;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 0 && (c === 0 || c === 2)) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19)) ||
    (a === 198 && b === 51 && c === 100) ||
    (a === 203 && b === 0 && c === 113) ||
    a >= 224
  );
}
function isBasicPublicHttpsUrl(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 2048) return false;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return false;
    if (url.port !== "" && url.port !== "443") return false;
    if (url.hostname.startsWith("[") || url.hostname.endsWith("]")) return false;
    const hostname = url.hostname.toLowerCase();
    if (!hostname || !hostname.includes(".") || hostname.startsWith(".") || hostname.endsWith(".")) return false;
    if ([".localhost", ".local", ".internal", ".localdomain"].some(suffix => hostname.endsWith(suffix))) return false;
    if (isPrivateOrReservedIpv4(hostname)) return false;
    const decoded = decodeURIComponent(url.href);
    for (let i = 0; i < decoded.length; i += 1) {
      const code = decoded.charCodeAt(i);
      if (code < 32 || code === 127 || decoded[i] === "\\") return false;
    }
    return true;
  } catch {
    return false;
  }
}
export function normalizePreviewUrl(value) {
  if (!isBasicPublicHttpsUrl(value)) return null;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    if ((hostname === "www.google.com" || hostname === "google.com") && url.pathname === "/url") {
      const target = url.searchParams.get("q") || url.searchParams.get("url");
      if (!target || !isBasicPublicHttpsUrl(target)) return null;
      const targetUrl = new URL(target);
      const targetHost = targetUrl.hostname.toLowerCase();
      if ((targetHost === "www.google.com" || targetHost === "google.com") && targetUrl.pathname === "/url") return null;
      return targetUrl.href;
    }
    if (hostname === "accounts.google.com") {
      const target = url.searchParams.get("continue") || url.searchParams.get("followup");
      if (!target || !isBasicPublicHttpsUrl(target)) return null;
      const targetUrl = new URL(target);
      const targetHost = targetUrl.hostname.toLowerCase();
      if ((targetHost === "docs.google.com" && targetUrl.pathname.startsWith("/forms/")) || targetHost === "forms.gle") {
        return targetUrl.href;
      }
      return null;
    }
    return value;
  } catch {
    return null;
  }
}
export function supportedUrl(value) {
  return normalizePreviewUrl(value) !== null;
}
const previews = new Map();
export async function preview(tab, url = tab?.url) {
  const normalized = normalizePreviewUrl(url);
  const key = `${tab?.id ?? "unknown"}:${normalized || url}`;
  const previous = previews.get(key);
  if (previous && (!previous.settled || Date.now() - previous.settled < 250)) return previous.promise;
  const promise = performPreview(tab, url, normalized);
  const entry = { promise, settled: null };
  previews.set(key, entry);
  try {
    const result = await promise;
    if (!result.ok) previews.delete(key);
    return result;
  }
  finally {
    entry.settled = Date.now();
    setTimeout(() => { if (previews.get(key)?.promise === promise) previews.delete(key); }, 250);
  }
}
async function performPreview(tab, url, normalized = normalizePreviewUrl(url)) {
  if (!normalized) {
    const result = { version: 1, ok: false, error_code: "unsupported_page", data: { status: "Use a public HTTPS application page." } };
    await chrome.storage.session.set({ lastResult: result });
    await chrome.action.setBadgeText?.({ text: "!" });
    return result;
  }
  const request = { version: 1, request_id: crypto.randomUUID(), command: "preview_application_url", url: normalized, title: (tab?.title || "").slice(0, 250) };
  let result;
  let timer;
  try {
    result = await Promise.race([
      chrome.runtime.sendNativeMessage(host, request),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), nativeTimeoutMs); }),
    ]);
    if (result?.version !== 1 || typeof result?.ok !== "boolean") throw new Error("invalid native schema");
    if (result.ok && (result.request_id !== request.request_id || result.data?.submitted !== false)) throw new Error("invalid preview result");
    if (result.request_id && result.request_id !== request.request_id) throw new Error("mismatch");
    if (!result.ok) {
      if (typeof result.error_code !== "string" || !ERROR_CODE_PATTERN.test(result.error_code)) throw new Error("invalid native schema");
      if (!result.data || typeof result.data !== "object") {
        result = { ...result, data: { status: "Check host installation and local backend; retry from this page." } };
      }
    }
  } catch (error) {
    result = { version: 1, ok: false, error_code: nativeErrorCode(error), data: { status: "Check host installation and local backend; retry from this page." } };
  } finally {
    clearTimeout(timer);
  }
  // Session-only result, not exposed to pages or saved in synchronized storage.
  await chrome.storage.session.set({ lastResult: result });
  await chrome.action.setBadgeText?.({ text: result.ok ? "OK" : "!" });
  return result;
}
