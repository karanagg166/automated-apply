import { profileContext, profileNative } from "./chrome-profile.js";
import { observeNaukri } from "./naukri-observation.js";
import { executeNaukri } from "./naukri-execution.js";
import { executeNaukriSkills } from "./naukri-profile-skills.js";
import { captureNaukriResumeDownload } from "./naukri-resume-download.js";
import { naukriChatbot } from "./naukri-chatbot.js";

// Injected only into this consumer's inactive search tab, after read admission.
// Use the observed ordinary Sort menu; never guess a provider query parameter.
export function sortNaukriSearchDate(expectedUrl, state = null) {
  const failure = (reason) => ({ kind: "needs_input", reason });
  const expected = new URL(expectedUrl);
  if (
    state &&
    (state.expectedUrl !== expectedUrl ||
      state.document !== performance.timeOrigin)
  )
    return failure("provider_context_changed");
  const pagePath = expected.pathname.match(/^(\/[a-z0-9-]+-jobs)(?:-([23]))?$/);
  const targetPage = Number(pagePath?.[2] || 1);
  let allowedPaths = new Set(state?.allowedPaths || [expected.pathname]);
  let pendingPage = state?.pendingPage ?? null;
  let previousLinks = state?.previousLinks ?? null;
  const listingLinks = () =>
    [...document.querySelectorAll('a[href*="/job-listings-"]')]
      .map((e) => e.href)
      .join("\n");
  let adopted = false;
  const visibilityChanged = () => {
    if (document.visibilityState !== "hidden") adopted = true;
  };
  const safe = () => {
    const actual = new URL(location.href);
    if (adopted || document.visibilityState !== "hidden")
      return "owner_tab_active";
    if (
      actual.origin !== "https://www.naukri.com" ||
      actual.origin !== expected.origin ||
      !allowedPaths.has(actual.pathname)
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
  let opened = state?.opened || false,
    selected = state?.selected || false,
    settled = state?.settled || 0;
  // One synchronous DOM step per injection. Waiting belongs to the extension
  // worker: Chrome may throttle chained timers in an inactive provider page.
  const pending = () => ({
    kind: "date_sort_pending",
    state: {
      expectedUrl,
      document: performance.timeOrigin,
      allowedPaths: [...allowedPaths],
      pendingPage,
      previousLinks,
      opened,
      selected,
      settled,
    },
  });
  document.addEventListener("visibilitychange", visibilityChanged);
  try {
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
      return pending();
    }
    if (control?.textContent.trim() === "Date") {
      if (targetPage > 1) {
        if (!pagePath) return failure("search_page_path_unrecognized");
        const pagers = [
          ...document.querySelectorAll('nav[aria-label="Pagination"]'),
        ].filter(visible);
        const current =
          pagers.length === 1
            ? [...pagers[0].querySelectorAll('a[aria-current="page"]')].filter(
                visible,
              )
            : [];
        const number =
          current.length === 1 &&
          /^([1-3])$/.exec(current[0].textContent.trim());
        if (!number) return failure("search_page_control_unrecognized");
        const page = Number(number[1]);
        const path = pagePath[1] + (page > 1 ? "-" + page : "");
        if (
          new URL(location.href).pathname !== path ||
          (pendingPage && page !== pendingPage)
        ) {
          return pending();
        }
        if (pendingPage && listingLinks() === previousLinks) {
          return pending();
        }
        pendingPage = null;
        if (page < targetPage) {
          const next = [...pagers[0].querySelectorAll("a")].filter(
            (e) => visible(e) && e.textContent.trim() === "Next",
          );
          const nextPath = pagePath[1] + "-" + (page + 1);
          let destination;
          try {
            destination = next.length === 1 && new URL(next[0].href);
          } catch {
            /* Refuse malformed navigation. */
          }
          if (
            !destination ||
            destination.origin !== expected.origin ||
            destination.pathname !== nextPath ||
            destination.search ||
            destination.hash ||
            destination.username ||
            destination.password ||
            destination.port ||
            next[0].hasAttribute("disabled") ||
            next[0].getAttribute("aria-disabled") === "true" ||
            ![null, "", "_self"].includes(next[0].getAttribute("target"))
          )
            return failure("search_next_page_control_unsupported");
          const refused = safe();
          if (refused) return failure(refused);
          previousLinks = listingLinks();
          pendingPage = page + 1;
          allowedPaths = new Set([path, nextPath]);
          settled = 0;
          next[0].click();
          return pending();
        }
        if (
          page !== targetPage ||
          new URL(location.href).pathname !== expected.pathname
        )
          return failure("search_page_identity_changed");
      }
      // Let the SPA replace its cards before observing them. Eligibility still
      // uses the actual job page's dates, never a search-card age label.
      if (++settled >= 5) return { kind: "date_sort", state: "selected" };
    } else if (control) {
      if (selected) {
        return pending();
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
        // The genuine Date control resets a paginated search to page one.
        // Permit only that explicit same-role transition, then advance via
        // its ordinary Next links while preserving Date in the SPA.
        if (targetPage > 1 && pagePath)
          allowedPaths = new Set([expected.pathname, pagePath[1]]);
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
    return pending();
  } finally {
    document.removeEventListener("visibilitychange", visibilityChanged);
  }
}

const key = "naukriReadInFlightV1";
const parkedKey = "naukriParkedQuestionnairesV1";
const profileSetupKey = "naukriProfileSetupTabV1";
const formOperations = new Set([
  "inspect_questionnaire",
  "refresh_questionnaire_profile",
  "refresh_questionnaire_job",
  "answer_questionnaire",
]);
const isFormWork = (work) =>
  formOperations.has(work?.operation) ||
  work?.operation === "prepare_questionnaire";
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
      // Also remember a parked tab adopted before a reconstructed worker has
      // loaded its ownership map. Record synchronously before storage awaits.
      this.adopted.add(tabId);
      void this.api.storage.session.get(key).then(async (saved) => {
        if (saved[key]?.ownedTabId === tabId)
          await this.api.storage.session.set({
            [key]: { ...saved[key], ownerAdopted: true },
          });
        if (saved[key]?.auxiliaryTabId === tabId)
          await this.api.storage.session.set({
            [key]: { ...saved[key], auxiliaryAdopted: true },
          });
      });
      void this.api.storage.session.get(parkedKey).then(async (saved) => {
        const forms = { ...(saved[parkedKey] || {}) };
        let changed = false;
        for (const [id, form] of Object.entries(forms)) {
          if (form.ownedTabId === tabId) {
            forms[id] = { ...form, ownerAdopted: true };
            changed = true;
          }
        }
        if (changed) await this.api.storage.session.set({ [parkedKey]: forms });
      });
      void this.api.storage.session.get(profileSetupKey).then(async (saved) => {
        const setup = saved[profileSetupKey];
        if (setup?.tab_id !== tabId) return;
        await this.api.storage.session.set({
          [profileSetupKey]: { ...setup, ownerAdopted: true },
        });
        if (Date.parse(setup.expires_at) <= Date.now()) return;
        try {
          const context = await profileContext(this.api);
          if (
            setup.profile_binding_id === context.profile_binding_id &&
            setup.browser_session_id === context.browser_session_id &&
            setup.window_id === context.window_id
          )
            await this.recordProfileSetup(setup, context, { id: tabId }, true);
        } catch {
          // Local adoption remains authoritative even if its bounded ACK fails.
        }
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
      const started = Date.now();
      // Completed ordinary reads can release the lane immediately instead of
      // waiting for another 30-second alarm. Never drain after uncertain work,
      // a challenge, a parked form or an execution flow. Each next poll repeats
      // the current owner/profile/policy checks and leases one work item only.
      for (
        let completed = 0;
        completed < 3 && Date.now() - started < 30000;
        completed++
      ) {
        if (!(await this.run())) break;
      }
    } finally {
      this.ticking = false;
    }
  }
  async ownerUsingNaukri() {
    const tabs = (await this.api.tabs.query({ active: true })).filter((t) =>
      /^https:\/\/(?:www\.)?naukri\.com\//.test(t.url || ""),
    );
    if (!tabs.length) return false;
    const windows = await this.api.windows.getAll({ windowTypes: ["normal"] });
    // A selected tab in an unfocused window is not the owner's current work.
    // Missing/ambiguous window evidence still yields instead of guessing.
    return tabs.some((tab) => {
      const matches = windows.filter((window) => window.id === tab.windowId);
      return matches.length !== 1 || matches[0].focused !== false;
    });
  }
  async maintenance(request, context) {
    const remaining = Date.parse(request?.expires_at) - Date.now();
    const profileSetup = request?.kind === "open_naukri_profile_setup";
    if (
      (!profileSetup && request?.kind !== "open_extension_manager") ||
      !/^[a-f0-9-]{36}$/.test(request.request_id || "") ||
      !Number.isFinite(remaining) ||
      remaining <= 0 ||
      remaining > 120000
    )
      return;
    const url = profileSetup
      ? "https://www.naukri.com/mnjuser/profile"
      : "chrome://extensions/";
    const key = profileSetup ? profileSetupKey : "naukriMaintenanceTabV1";
    const previous = (await this.api.storage.session.get(key))[key];
    if (previous?.request_id === request.request_id) {
      // An uncertain ACK can be repeated; an uncertain tab creation cannot.
      if (profileSetup && previous.status === "opened") {
        if (
          previous.profile_binding_id !== context.profile_binding_id ||
          previous.browser_session_id !== context.browser_session_id
        )
          return;
        try {
          const tab = await this.api.tabs.get(previous.tab_id);
          const adopted =
            previous.ownerAdopted ||
            this.adopted.has(tab.id) ||
            tab.active ||
            tab.windowId !== context.window_id;
          await this.recordProfileSetup(request, context, tab, adopted);
        } catch {
          // A missing/adopted tab is never recreated for the same intent.
        }
      }
      return;
    }
    // Persist the intent first. A lost create response cannot create duplicate
    // setup tabs on the next alarm. This path never selects or focuses a tab.
    await this.api.storage.session.set({
      [key]: { request_id: request.request_id, status: "creating" },
    });
    let tab;
    if (
      Number.isInteger(previous?.tab_id) &&
      (!profileSetup ||
        (!previous.ownerAdopted &&
          !this.adopted.has(previous.tab_id) &&
          previous.profile_binding_id === context.profile_binding_id &&
          previous.browser_session_id === context.browser_session_id))
    ) {
      try {
        const saved = await this.api.tabs.get(previous.tab_id);
        if (
          !saved.active &&
          saved.windowId === context.window_id &&
          saved.url === url
        )
          tab = saved;
      } catch {
        /* A closed or adopted setup tab is never recreated in place. */
      }
    }
    tab ||= await this.api.tabs.create({
      url,
      active: false,
      windowId: context.window_id,
    });
    await this.api.storage.session.set({
      [key]: {
        request_id: request.request_id,
        status: "opened",
        tab_id: tab.id,
        window_id: context.window_id,
        ...(profileSetup
          ? {
              expires_at: request.expires_at,
              profile_binding_id: context.profile_binding_id,
              browser_session_id: context.browser_session_id,
              ownerAdopted: this.adopted.has(tab.id) || Boolean(tab.active),
            }
          : {}),
      },
    });
    if (profileSetup) {
      const current = await this.api.tabs.get(tab.id);
      const adopted =
        this.adopted.has(tab.id) ||
        current.active ||
        current.windowId !== context.window_id;
      if (adopted)
        await this.api.storage.session.set({
          [key]: {
            ...(await this.api.storage.session.get(key))[key],
            ownerAdopted: true,
          },
        });
      await this.recordProfileSetup(request, context, current, adopted);
    }
  }
  async recordProfileSetup(request, context, tab, adopted) {
    await this.send(this.api, "poll_naukri_work", {
      ...context,
      tab_id: tab.id,
      work_id: request.request_id,
      ...(adopted
        ? { work_report: { kind: "needs_input", reason: "owner_tab_active" } }
        : {}),
    });
  }
  async run() {
    let work = (await this.api.storage.session.get(key))[key];
    try {
      if (work) {
        if (work.form_pending && isFormWork(work)) {
          if (work.auxiliaryTabId)
            await this.closeOwned({
              ...work,
              ownedTabId: work.auxiliaryTabId,
              ownerAdopted: work.auxiliaryAdopted,
            });
          if (["leased", "executing"].includes(work.status)) {
            try {
              await this.command("abandon_naukri_work", work, {
                work_report: {
                  kind: "needs_input",
                  reason: "questionnaire_worker_restarted_reconcile_only",
                },
              });
            } catch {
              /* Fenced lease is authoritative. */
            }
          }
          await this.park(work);
          await this.api.storage.session.remove(key);
          work = null;
        }
      }
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
      if (await this.ownerUsingNaukri()) return;
      const polled = await this.send(this.api, "poll_naukri_work", context);
      if (polled.maintenance) {
        await this.maintenance(polled.maintenance, context);
        return;
      }
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
          ...formOperations,
        ].includes(work.operation)
      )
        throw Error("background_operation_not_supported");
      const parked = ((await this.api.storage.session.get(parkedKey))[
        parkedKey
      ] || {})[work.id];
      let tab;
      if (formOperations.has(work.operation)) {
        if (
          !parked ||
          parked.ownerAdopted ||
          this.adopted.has(parked.ownedTabId)
        )
          throw Error("questionnaire_original_tab_unavailable");
        if (
          ["profile_binding_id", "browser_session_id", "window_id"].some(
            (k) => parked.binding[k] !== context[k],
          )
        )
          throw Error("questionnaire_original_browser_context_required");
        tab = await this.api.tabs.get(parked.ownedTabId);
        if (
          tab.active ||
          tab.windowId !== context.window_id ||
          tab.url !== work.url
        )
          throw Error("questionnaire_original_tab_unavailable");
      } else
        tab = await this.api.tabs.create({
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
        work = formOperations.has(work.operation)
          ? await this.executeQuestionnaire(work, context)
          : await this.execute(work, context);
        if (work.form_pending && isFormWork(work)) await this.park(work);
        else await this.closeOwned(work);
        if (work.stage === "SUBMITTED_CONFIRMED" && parked) {
          await this.closeOwned(parked);
          const forms = {
            ...((await this.api.storage.session.get(parkedKey))[parkedKey] ||
              {}),
          };
          delete forms[work.id];
          await this.api.storage.session.set({ [parkedKey]: forms });
        }
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
        let report,
          state = null;
        const started = Date.now();
        for (let step = 0; step < 40 && Date.now() - started < 10000; step++) {
          await this.assertInactive(work, context);
          let timer, sorted;
          try {
            sorted = await Promise.race([
              this.api.scripting.executeScript({
                target: { tabId: work.ownedTabId, frameIds: [0] },
                world: "ISOLATED",
                func: sortNaukriSearchDate,
                args: [work.url, state],
              }),
              new Promise((_, reject) => {
                timer = setTimeout(
                  () => reject(Error("search_date_sort_not_confirmed")),
                  Math.max(1, 10000 - (Date.now() - started)),
                );
              }),
            ]);
          } finally {
            clearTimeout(timer);
          }
          await this.assertInactive(work, context);
          report = sorted.length === 1 && sorted[0].result;
          if (report?.kind !== "date_sort_pending") break;
          state = report.state;
          await this.delay(200);
        }
        if (report?.kind !== "date_sort")
          throw Error(report?.reason || "search_date_sort_not_confirmed");
      }
      const report = await this.observeReady(work, context);
      if (!report || (await this.api.tabs.get(tab.id)).active)
        throw Error("owner_tab_active");
      await this.command("finish_naukri_work", work, { work_report: report });
      await this.closeOwned(work);
      await this.api.storage.session.remove(key);
      return ["job_facts", "source_candidates"].includes(report.kind);
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
        if (
          (work.form_pending && isFormWork(work)) ||
          ["apply", "answer_questionnaire"].includes(work.operation)
        )
          await this.park(work);
        else await this.closeOwned(work);
      }
      await this.api.storage.session.remove(key);
    }
  }
  async park(work) {
    const forms = {
      ...((await this.api.storage.session.get(parkedKey))[parkedKey] || {}),
    };
    forms[work.id] = {
      ...work,
      form_pending: true,
      ownerAdopted: !!(
        work.ownerAdopted ||
        forms[work.id]?.ownerAdopted ||
        this.adopted.has(work.ownedTabId)
      ),
    };
    await this.api.storage.session.set({ [parkedKey]: forms });
  }
  async auxiliaryObservation(work, context) {
    await this.assertInactive(work, context);
    const tab = await this.api.tabs.create({
      url: "about:blank",
      active: false,
      windowId: context.window_id,
    });
    this.ownedAuxId = tab.id;
    await this.api.storage.session.set({
      [key]: { ...work, auxiliaryTabId: tab.id },
    });
    const aux = { ...work, ownedTabId: tab.id };
    try {
      await this.api.tabs.update(tab.id, {
        url: work.target_url,
        active: false,
      });
      for (let i = 0; i < 50; i++) {
        const current = await this.assertInactive(aux, context);
        if (current.status === "complete") break;
        if (i === 49) throw Error("background_page_timeout");
        await this.delay(200);
      }
      if ((await this.assertInactive(aux, context)).url !== work.target_url)
        throw Error("provider_context_changed");
      if (work.operation === "refresh_questionnaire_job")
        return await this.observeReady(
          { ...aux, operation: "inspect_job" },
          context,
        );
      const profileWork = { ...work, operation: "inspect_profile" };
      let r = await this.api.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [0] },
        world: "ISOLATED",
        func: executeNaukri,
        args: [profileWork],
      });
      let report = r.length === 1 && r[0].result;
      if (report?.reason === "profile_resume_download_capture_required") {
        await this.assertInactive(aux, context);
        r = await this.api.scripting.executeScript({
          target: { tabId: tab.id, frameIds: [0] },
          world: "MAIN",
          func: captureNaukriResumeDownload,
          args: [{ target_url: work.target_url }],
        });
        const pdf = r.length === 1 && r[0].result;
        if (pdf?.kind !== "provider_pdf_digest")
          throw Error(pdf?.reason || "profile_resume_download_capture_failed");
        await this.assertInactive(aux, context);
        r = await this.api.scripting.executeScript({
          target: { tabId: tab.id, frameIds: [0] },
          world: "ISOLATED",
          func: executeNaukri,
          args: [
            {
              ...profileWork,
              execution: {
                ...profileWork.execution,
                provider_pdf_observation: pdf,
              },
            },
          ],
        });
        report = r.length === 1 && r[0].result;
      }
      return report;
    } finally {
      await this.closeOwned(aux);
      this.ownedAuxId = null;
    }
  }
  async executeQuestionnaire(initial, context) {
    let work = initial;
    for (let step = 0; step < 4; step++) {
      await this.assertInactive(work, context);
      if ((await this.api.tabs.get(work.ownedTabId)).url !== work.url)
        throw Error("questionnaire_original_tab_unavailable");
      const admitted = await this.command("admit_naukri_work", work);
      work = { ...admitted.work, ownedTabId: work.ownedTabId };
      await this.api.storage.session.set({ [key]: work });
      let report;
      if (work.operation.startsWith("refresh_questionnaire_"))
        report = await this.auxiliaryObservation(work, context);
      else {
        let observed;
        for (let attempt = 0; attempt < 8; attempt++) {
          const r = await this.api.scripting.executeScript({
            target: { tabId: work.ownedTabId, frameIds: [0] },
            world: "ISOLATED",
            func: naukriChatbot,
            args: [
              {
                operation:
                  work.operation === "answer_questionnaire"
                    ? "answer"
                    : "inspect",
                url: work.url,
                requisition: work.requisition,
                ...work.execution?.questionnaire,
              },
            ],
          });
          observed = r.length === 1 && r[0].result;
          if (
            work.operation !== "inspect_questionnaire" ||
            ![
              "questionnaire_drawer_unrecognized",
              "questionnaire_question_unrecognized",
              "questionnaire_controls_unrecognized",
            ].includes(observed?.reason) ||
            attempt === 7
          )
            break;
          await this.assertInactive(work, context);
          await this.delay(250);
        }
        if (observed?.kind === "questionnaire") {
          const { kind, ...questionnaire } = observed;
          report = {
            kind,
            questionnaire,
            observed_url: work.url,
            requisition: work.requisition,
          };
        } else
          report = observed && {
            ...observed,
            observed_url: work.url,
            requisition: work.requisition,
          };
      }
      if (!report) throw Error("questionnaire_observation_failed");
      await this.assertInactive(work, context);
      const finished = await this.command("finish_naukri_work", work, {
        work_report: report,
      });
      work = { ...finished.work, ownedTabId: work.ownedTabId };
      await this.api.storage.session.set({ [key]: work });
      if (!finished.continue) return work;
    }
    throw Error("questionnaire_step_limit_reached");
  }
  async execute(initial, context) {
    let work = initial;
    const steps = ["inspect_profile_sync", "sync_profile"].includes(
      initial.operation,
    )
      ? 4
      : 3;
    for (let step = 0; step < steps; step++) {
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
      const skills =
        work.operation === "sync_profile" &&
        work.execution?.sync_field === "skills";
      const currentUrl = (await this.api.tabs.get(tabId)).url;
      if (
        currentUrl !== work.target_url &&
        !(skills && currentUrl === work.target_url + "?action=modalOpen")
      )
        throw Error("provider_context_changed");
      const admitted = await this.command("admit_naukri_work", work);
      work = { ...admitted.work, ownedTabId: tabId };
      await this.api.storage.session.set({ [key]: work });
      await this.assertInactive(work, context);
      const injected = await this.api.scripting.executeScript({
        target: { tabId, frameIds: [0] },
        world: "ISOLATED",
        func: skills ? executeNaukriSkills : executeNaukri,
        args: [work],
      });
      let report = injected.length === 1 && injected[0].result;
      if (!report) throw Error("provider_execution_unconfirmed");
      if (skills && work.execution.sync_phase === "prepare") {
        const started = Date.now();
        for (
          let tick = 0;
          report.kind === "profile_skills_prepare_pending" &&
          tick < 40 &&
          Date.now() - started < 10000;
          tick++
        ) {
          await this.delay(200);
          await this.assertInactive(work, context);
          const next = await this.api.scripting.executeScript({
            target: { tabId, frameIds: [0] },
            world: "ISOLATED",
            func: executeNaukriSkills,
            args: [work],
          });
          report = next.length === 1 && next[0].result;
          if (!report) throw Error("profile_skills_preparation_unconfirmed");
        }
        if (report.kind === "profile_skills_prepare_pending")
          throw Error("profile_skills_preparation_unconfirmed");
      }
      if (
        ["inspect_profile", "inspect_profile_sync"].includes(work.operation) &&
        report.reason === "profile_resume_download_capture_required"
      ) {
        await this.assertInactive(work, context);
        const capture = await this.api.scripting.executeScript({
          target: { tabId, frameIds: [0] },
          world: "MAIN",
          func: captureNaukriResumeDownload,
          // MAIN needs only the exact profile URL, never a work lease/binding.
          args: [{ target_url: work.target_url }],
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
    const saved = (await this.api.storage.session.get(key))[key];
    const parked = ((await this.api.storage.session.get(parkedKey))[
      parkedKey
    ] || {})[work.id];
    if (
      tab.active ||
      work.ownerAdopted ||
      (parked?.ownedTabId === tab.id && parked.ownerAdopted) ||
      (saved?.ownedTabId === tab.id && saved.ownerAdopted) ||
      (saved?.auxiliaryTabId === tab.id && saved.auxiliaryAdopted) ||
      this.adopted.has(tab.id) ||
      tab.windowId !== context.window_id
    )
      throw Error("owner_tab_active");
    if (await this.ownerUsingNaukri()) throw Error("owner_platform_active");
    return tab;
  }
  async closeOwned(work) {
    const saved = (await this.api.storage.session.get(key))[key];
    const parked = ((await this.api.storage.session.get(parkedKey))[
      parkedKey
    ] || {})[work?.id];
    if (
      !Number.isInteger(work?.ownedTabId) ||
      work.ownerAdopted ||
      (parked?.ownedTabId === work.ownedTabId && parked.ownerAdopted) ||
      (saved?.ownedTabId === work.ownedTabId && saved.ownerAdopted) ||
      (saved?.auxiliaryTabId === work.ownedTabId && saved.auxiliaryAdopted) ||
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
