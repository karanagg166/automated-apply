import { profileContext, profileNative } from "./chrome-profile.js";
import { observeNaukri } from "./naukri-observation.js";
import { executeNaukri } from "./naukri-execution.js";
import { captureNaukriResumeDownload } from "./naukri-resume-download.js";

// Injected only into this consumer's inactive search tab, after read admission.
// Use the observed ordinary Sort menu; never guess a provider query parameter.
export async function sortNaukriSearchDate(expectedUrl) {
  const failure = (reason) => ({ kind: "needs_input", reason });
  let adopted = false;
  const visibilityChanged = () => {
    if (document.visibilityState !== "hidden") adopted = true;
  };
  const safe = () => {
    const actual = new URL(location.href),
      expected = new URL(expectedUrl);
    if (adopted || document.visibilityState !== "hidden")
      return "owner_tab_active";
    if (
      actual.origin !== "https://www.naukri.com" ||
      actual.origin !== expected.origin ||
      actual.pathname !== expected.pathname
    )
      return "provider_context_changed";
    if (
      /captcha|verify (?:that )?you are human|unusual traffic|access denied|too many requests/i.test(
        document.body?.innerText || "",
      ) ||
      [...document.querySelectorAll('iframe[src*="captcha"]')].some(
        (e) => e.getClientRects().length,
      )
    )
      return "provider_challenge_requires_owner";
    return null;
  };
  const visible = (e) =>
    e?.isConnected &&
    e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== "hidden";
  let opened = false,
    selected = false,
    settled = 0;
  document.addEventListener("visibilitychange", visibilityChanged);
  try {
    for (let attempt = 0; attempt < 40; attempt++) {
      const refused = safe();
      if (refused) return failure(refused);
      const controls = [...document.querySelectorAll("#filter-sort")].filter(
        visible,
      );
      if (controls.length > 1) return failure("search_sort_control_ambiguous");
      const control = controls[0];
      if (
        control &&
        (control.tagName !== "BUTTON" ||
          control.type !== "button" ||
          control.getAttribute("aria-controls") !== "filter-sort-menu")
      )
        return failure("search_sort_control_unrecognized");
      if (
        control?.disabled ||
        control?.getAttribute("aria-disabled") === "true"
      ) {
        await new Promise((resolve) => setTimeout(resolve, 200));
        continue;
      }
      if (control?.textContent.trim() === "Date") {
        // Let the SPA replace its cards before observing them. Eligibility still
        // uses the actual job page's dates, never a search-card age label.
        if (++settled >= 5) return { kind: "date_sort", state: "selected" };
      } else if (control) {
        if (selected) {
          await new Promise((resolve) => setTimeout(resolve, 200));
          continue;
        }
        const options = [
          ...document.querySelectorAll('#filter-sort-menu [role="option"]'),
        ].filter((e) => e.title === "Date" && visible(e));
        if (options.length > 1) return failure("search_date_option_ambiguous");
        if (options.length === 1) {
          const links = [...options[0].querySelectorAll("a")].filter(visible);
          if (links.length !== 1)
            return failure("search_date_option_unsupported");
          // This observed SPA control uses an anchor with no navigation target.
          // Refuse new destinations, script URLs and new windows.
          const href = links[0].getAttribute("href");
          if (
            (href && href !== "#") ||
            ![null, "", "_self"].includes(links[0].getAttribute("target"))
          )
            return failure("search_date_option_unsupported");
          const refused = safe();
          if (refused) return failure(refused);
          selected = true;
          links[0].click();
        } else if (!opened) {
          opened = true;
          control.click();
        }
      } else if (
        /no jobs found|no results found/i.test(document.body?.innerText || "")
      ) {
        return { kind: "date_sort", state: "no_results" };
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return failure(
      opened
        ? "search_date_sort_not_confirmed"
        : "search_sort_control_unrecognized",
    );
  } finally {
    document.removeEventListener("visibilitychange", visibilityChanged);
  }
}

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
      if (
        ![
          "inspect_job",
          "search_jobs",
          "inspect_profile",
          "inspect_application",
          "reconcile_application",
          "inspect_profile_sync",
          "verify_account",
        ].includes(work.operation)
      )
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
      if (work.execution) {
        work = await this.execute(work, context);
        await this.closeOwned(work);
        await this.api.storage.session.remove(key);
        return;
      }
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
      if (work.operation === "search_jobs") {
        await this.assertInactive(work, context);
        const sorted = await this.api.scripting.executeScript({
          target: { tabId: work.ownedTabId, frameIds: [0] },
          world: "ISOLATED",
          func: sortNaukriSearchDate,
          args: [work.url],
        });
        await this.assertInactive(work, context);
        const report = sorted.length === 1 && sorted[0].result;
        if (report?.kind !== "date_sort")
          throw Error(report?.reason || "search_date_sort_not_confirmed");
      }
      const report = await this.observeReady(work, context);
      if (!report || (await this.api.tabs.get(tab.id)).active)
        throw Error("owner_tab_active");
      await this.command("finish_naukri_work", work, { work_report: report });
      await this.closeOwned(work);
      await this.api.storage.session.remove(key);
    } catch (error) {
      work = (await this.api.storage.session.get(key))[key] || work;
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
  async execute(initial, context) {
    let work = initial;
    for (let step = 0; step < 3; step++) {
      const tabId = work.ownedTabId;
      if (!["apply", "sync_profile"].includes(work.operation)) {
        await this.assertInactive(work, context);
        await this.api.tabs.update(tabId, {
          url: work.target_url,
          active: false,
        });
        for (let i = 0; i < 50; i++) {
          const tab = await this.assertInactive(work, context);
          if (tab.status === "complete") break;
          if (i === 49) throw Error("background_page_timeout");
          await this.delay(200);
        }
      }
      await this.assertInactive(work, context);
      if ((await this.api.tabs.get(tabId)).url !== work.target_url)
        throw Error("provider_context_changed");
      const admitted = await this.command("admit_naukri_work", work);
      work = { ...admitted.work, ownedTabId: tabId };
      await this.api.storage.session.set({ [key]: work });
      await this.assertInactive(work, context);
      const injected = await this.api.scripting.executeScript({
        target: { tabId, frameIds: [0] },
        world: "ISOLATED",
        func: executeNaukri,
        args: [work],
      });
      let report = injected.length === 1 && injected[0].result;
      if (!report) throw Error("provider_execution_unconfirmed");
      if (
        work.operation === "inspect_profile" &&
        report.reason === "profile_resume_download_capture_required"
      ) {
        await this.assertInactive(work, context);
        const capture = await this.api.scripting.executeScript({
          target: { tabId, frameIds: [0] },
          world: "MAIN",
          func: captureNaukriResumeDownload,
          args: [work],
        });
        const pdf = capture.length === 1 && capture[0].result;
        if (pdf?.kind !== "provider_pdf_digest")
          throw Error(pdf?.reason || "profile_resume_download_capture_failed");
        await this.assertInactive(work, context);
        const verified = await this.api.scripting.executeScript({
          target: { tabId, frameIds: [0] },
          world: "ISOLATED",
          func: executeNaukri,
          args: [
            {
              ...work,
              execution: { ...work.execution, provider_pdf_observation: pdf },
            },
          ],
        });
        report = verified.length === 1 && verified[0].result;
        if (!report) throw Error("provider_execution_unconfirmed");
      }
      if (
        work.operation === "inspect_application" &&
        report.execution?.state === "NOT_APPLIED"
      ) {
        const observed = await this.observeReady(
          { ...work, operation: "inspect_job" },
          context,
        );
        if (observed?.kind !== "job_facts")
          throw Error(observed?.reason || "provider_job_facts_required");
        report = { ...report, job: observed.job };
      }
      await this.assertInactive(work, context);
      const finished = await this.command("finish_naukri_work", work, {
        work_report: report,
      });
      work = { ...finished.work, ownedTabId: tabId };
      await this.api.storage.session.set({ [key]: work });
      if (!finished.continue) return work;
    }
    throw Error("background_step_limit_reached");
  }
  async observeReady(work, context) {
    // Navigation complete can precede React hydration. Only read-only layout
    // absence is retried; challenges, ambiguity and all writes are terminal.
    const transient = new Set([
      "job_header_unrecognized",
      "job_required_facts_unrecognized",
      "search_layout_unrecognized",
    ]);
    for (let attempt = 0; attempt < 9; attempt++) {
      const tab = await this.assertInactive(work, context);
      const actual = new URL(tab.url),
        expected = new URL(work.url);
      if (
        actual.origin !== expected.origin ||
        actual.pathname !== expected.pathname
      )
        throw Error("provider_context_changed");
      const result = await this.api.scripting.executeScript({
        target: { tabId: work.ownedTabId, frameIds: [0] },
        world: "ISOLATED",
        func: observeNaukri,
        args: [work.url, work.operation],
      });
      const report = result.length === 1 && result[0].result;
      await this.assertInactive(work, context);
      if (!report || !transient.has(report.reason) || attempt === 8)
        return report;
      await this.delay(250);
    }
  }
  async assertInactive(work, context) {
    const tab = await this.api.tabs.get(work.ownedTabId);
    if (
      tab.active ||
      this.adopted.has(tab.id) ||
      tab.windowId !== context.window_id
    )
      throw Error("owner_tab_active");
    const ownerTabs = await this.api.tabs.query({ active: true });
    if (
      ownerTabs.some((t) =>
        /^https:\/\/(?:www\.)?naukri\.com\//.test(t.url || ""),
      )
    )
      throw Error("owner_platform_active");
    return tab;
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
      if (
        !tab.active &&
        !this.adopted.has(tab.id) &&
        tab.windowId === work.binding.window_id
      )
        await this.api.tabs.remove(tab.id);
    } catch {
      /* Closed or moved tabs are never replaced. */
    }
  }
}
