// Owner-enabled, bounded audit. No URL, title, content or persistent tab ID is saved.
// Chrome does not disclose which user/extension caused a general tabs event.
let queue = Promise.resolve();
export function auditTab(api, event, tab = {}, source = "unattributed") {
  const run = queue.then(async () => {
    if (!api.storage?.session) return;
    const { tabLifecycleAudit: audit } = await api.storage.session.get("tabLifecycleAudit");
    if (!audit || !Number.isFinite(audit.until) || audit.until <= Date.now() ||
        audit.until > Date.now() + 10 * 60 * 1000 || typeof audit.salt !== "string") return;
    async function hash(value) {
      if (value === undefined || value === null) return null;
      const bytes = new TextEncoder().encode(audit.salt + ":" + value);
      return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map(x => x.toString(16).padStart(2, "0")).join("");
    }
    let origin;
    try { origin = new URL(tab.url).origin; } catch { /* unavailable without host grant */ }
    const entry = { at: Date.now(), event, source,
      tab: await hash(tab.id), window: await hash(tab.windowId),
      origin: await hash(origin), restored: tab.sessionId ? true : null };
    await api.storage.session.set({ tabLifecycleAudit: {
      until: audit.until, salt: audit.salt,
      events: [...(audit.events || []), entry].slice(-512),
      truncated: Boolean(audit.truncated || audit.events?.length >= 512),
    }});
  });
  queue = run.catch(() => {});
  return queue;
}
