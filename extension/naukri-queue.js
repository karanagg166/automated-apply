import { profileContext, profileNative } from "./chrome-profile.js";
import { observeNaukri } from "./naukri-observation.js";

const key = "naukriReadInFlightV1";
// Only this trusted service-worker module creates these inactive tabs. It never
// adopts an existing owner tab, activates a window or opens a native chooser.
export class NaukriQueue {
  constructor(
    api = chrome,
    send = profileNative,
    delay = (ms) => new Promise((r) => setTimeout(r, ms)),
  ) {
    this.api = api;
    this.send = send;
    this.delay = delay;
    this.adopted = new Set();
    this.api.tabs.onActivated?.addListener(({ tabId }) => {
      if (this.ownedTabId !== tabId) return;
      this.adopted.add(tabId);
      void this.api.storage.session.get(key).then(async (saved) => {
        if (saved[key]?.ownedTabId === tabId)
          await this.api.storage.session.set({
            [key]: { ...saved[key], ownerAdopted: true },
          });
      });
    });
  }
  async command(name, work, extra = {}) {
    return this.send(this.api, name, {
      ...(await profileContext(this.api)),
      work_id: work.id,
      expected_work_revision: work.revision,
      work_lease_token: work.lease_token,
      tab_id: work.binding.tab_id,
      ...extra,
    });
  }
  async tick() {
    if (this.ticking) return;
    this.ticking = true;
    try {
      await this.run();
    } finally {
      this.ticking = false;
    }
  }
  async run() {
    let work = (await this.api.storage.session.get(key))[key];
    try {
      if (work) {
        // Recovery reconciles local observation only. No submitting operation
        // exists in this consumer and no old browser action is repeated here.
        try {
          await this.command("abandon_naukri_work", work, {
            work_report: {
              kind: "needs_input",
              reason: "browser_worker_restarted",
            },
          });
        } catch {
          /* The old lease/profile may already be fenced. */
        }
        await this.closeOwned(work);
        await this.api.storage.session.remove(key);
      }
      if (
        !(await this.api.permissions.contains({
          origins: ["https://www.naukri.com/*"],
        }))
      )
        return;
      const context = await profileContext(this.api);
      // Existing owner activity on Naukri takes priority; don't add a second
      // concurrent authenticated journey while that platform is being used.
      const ownerTabs = await this.api.tabs.query({
        active: true,
        windowId: context.window_id,
      });
      if (
        ownerTabs.some((t) =>
          /^https:\/\/(?:www\.)?naukri\.com\//.test(t.url || ""),
        )
      )
        return;
      const polled = await this.send(this.api, "poll_naukri_work", context);
      work = polled.work;
      if (!work) return;
      if (!["inspect_job", "search_jobs"].includes(work.operation))
        throw Error("background_operation_not_supported");
      const tab = await this.api.tabs.create({
        url: "about:blank",
        active: false,
        windowId: context.window_id,
      });
      // Save the created tab before any native round-trip so recovery can close
      // only this owned inactive tab even if bind's response is lost.
      this.ownedTabId = tab.id;
      work = { ...work, ownedTabId: tab.id };
      await this.api.storage.session.set({ [key]: work });
      const bound = await this.command("bind_naukri_work", work, {
        tab_id: tab.id,
      });
      work = { ...bound.work, ownedTabId: tab.id };
      await this.api.storage.session.set({ [key]: work });
      if ((await this.api.tabs.get(tab.id)).active || this.adopted.has(tab.id))
        throw Error("owner_tab_active");
      await this.api.tabs.update(tab.id, { url: work.url, active: false });
      for (let i = 0; i < 50; i++) {
        const current = await this.api.tabs.get(tab.id);
        if (current.active || current.windowId !== context.window_id)
          throw Error("owner_tab_active");
        if (current.status === "complete") break;
        if (i === 49) throw Error("background_page_timeout");
        await this.delay(500);
      }
      const current = await this.api.tabs.get(tab.id);
      const actual = new URL(current.url),
        expected = new URL(work.url);
      if (
        current.active ||
        current.windowId !== context.window_id ||
        actual.origin !== expected.origin ||
        actual.pathname !== expected.pathname
      )
        throw Error("provider_context_changed");
      const admitted = await this.command("admit_naukri_work", work);
      work = { ...admitted.work, ownedTabId: tab.id };
      await this.api.storage.session.set({ [key]: work });
      const result = await this.api.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [0] },
        world: "ISOLATED",
        func: observeNaukri,
        args: [work.url, work.operation],
      });
      const report = result.length === 1 && result[0].result;
      if (!report || (await this.api.tabs.get(tab.id)).active)
        throw Error("owner_tab_active");
      await this.command("finish_naukri_work", work, { work_report: report });
      await this.closeOwned(work);
      await this.api.storage.session.remove(key);
    } catch (error) {
      if (work) {
        try {
          await this.command("abandon_naukri_work", work, {
            work_report: {
              kind: "needs_input",
              reason: /^[a-zA-Z][a-zA-Z0-9_]{1,63}$/.test(error.message)
                ? error.message
                : "background_observation_failed",
            },
          });
        } catch {
          /* Expiration/Stop is authoritative; do not retry actions. */
        }
        await this.closeOwned(work);
      }
      await this.api.storage.session.remove(key);
    }
  }
  async closeOwned(work) {
    if (
      !Number.isInteger(work?.ownedTabId) ||
      work.ownerAdopted ||
      this.adopted.has(work.ownedTabId)
    )
      return;
    try {
      const tab = await this.api.tabs.get(work.ownedTabId);
      if (!tab.active && tab.windowId === work.binding.window_id)
        await this.api.tabs.remove(tab.id);
    } catch {
      /* Closed or moved tabs are never replaced. */
    }
  }
}
