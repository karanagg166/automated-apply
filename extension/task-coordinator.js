import { installGuard, guardActive, releaseGuard } from "./network-guard.js";
// Privileged MV3 worker coordinator. Only extension pages may call this API.
// Persist identifiers/status only. Candidate answers remain in backend plan storage.
import {
  inspectForm,
  prepareAnswers,
  fillForm,
  cancelPreparedForm,
  inspectOnly,
  interruptForm,
} from "./form-bridge.js";

const host = "com.automated_apply.agent";
const storageKey = "applicationTaskBindingsV1";
const sessionKey = "applicationBrowserSessionV1";
const uuid = /^[a-f0-9-]{36}$/;
const terminal = new Set([
  "FAILED_FINAL",
  "SUBMITTED_CONFIRMED",
  "SUBMISSION_UNKNOWN",
  "CANCELLED",
]);
export class TaskCoordinator {
  constructor(api = chrome) {
    this.api = api;
    this.bindings = {};
    this.busy = new Set();
    this.queue = Promise.resolve();
    this.ready = this.initialize();
  }
  async initialize() {
    // Content scripts never receive persisted private task context.
    await this.api.storage.local.setAccessLevel?.({
      accessLevel: "TRUSTED_CONTEXTS",
    });
    await this.api.storage.session.setAccessLevel?.({
      accessLevel: "TRUSTED_CONTEXTS",
    });
    const stored = await this.api.storage.session.get(sessionKey);
    this.sessionId = stored[sessionKey] || crypto.randomUUID();
    await this.api.storage.session.set({ [sessionKey]: this.sessionId });
    this.bindings =
      (await this.api.storage.local.get(storageKey))[storageKey] || {};
    // No executable plan or fill authorization is restored after worker restart.
    for (const binding of Object.values(this.bindings)) {
      binding.requiresInspection = true;
      if (terminal.has(binding.state)) continue;
      try {
        if (binding.browserSessionId === this.sessionId)
          await interruptForm(binding.tabId, binding.documentId, this.api);
        await this.update(
          binding.id,
          binding.browserSessionId === this.sessionId
            ? "worker_restart"
            : "recover",
        );
      } catch {
        // Offline recovery never turns a stale local binding into executable context.
        binding.state = "PAUSED";
      }
    }
    await this.persist();
  }
  async native(command, extra = {}) {
    const request = {
      version: 1,
      request_id: crypto.randomUUID(),
      command,
      ...extra,
    };
    let timer;
    try {
      const result = await Promise.race([
        this.api.runtime.sendNativeMessage(host, request),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error("backend_timeout")), 45000);
        }),
      ]);
      if (
        result?.version !== 1 ||
        result.request_id !== request.request_id ||
        typeof result.ok !== "boolean"
      )
        throw Error("native_protocol_error");
      if (!result.ok)
        throw Error(
          /^[a-z][a-z0-9_]{1,63}$/.test(result.error_code)
            ? result.error_code
            : "native_protocol_error",
        );
      if (
        command !== "get_agent_capabilities" &&
        result.data?.submitted !== false
      )
        throw Error("native_protocol_error");
      return result.data;
    } finally {
      clearTimeout(timer);
    }
  }
  async persist() {
    await this.api.storage.local.set({ [storageKey]: this.bindings });
  }
  accept(task, previous = {}) {
    if (!task || !uuid.test(task.id) || !Number.isInteger(task.version))
      throw Error("native_protocol_error");
    this.bindings[task.id] = {
      ...previous,
      id: task.id,
      version: task.version,
      applicationId: task.application_id,
      tabId: task.tab_id,
      browserSessionId: task.browser_session_id,
      url: task.current_url || task.target_url,
      state: task.state,
      requiresInspection: previous.requiresInspection ?? true,
    };
    return this.bindings[task.id];
  }
  context(binding) {
    return {
      task_id: binding.id,
      expected_task_version: binding.version,
      browser_session_id: this.sessionId,
      tab_id: binding.tabId,
    };
  }
  async task(id) {
    if (!uuid.test(id || "")) throw Error("application_task_required");
    const data = await this.native("get_application_task", { task_id: id });
    this.accept(data.task, this.bindings[id]);
    await this.persist();
    data.task.network_guard_active = await guardActive(
      this.api,
      this.bindings[id].tabId,
    );
    return data.task;
  }
  async update(id, event, extra = {}) {
    await this.task(id); // Also observes dashboard cancellation before each operation.
    const binding = this.bindings[id];
    const data = await this.native("update_application_task", {
      ...this.context(binding),
      task_event: event,
      ...extra,
    });
    this.accept(data.task, binding);
    await this.persist();
    return data.task;
  }
  async active(binding) {
    if (binding.browserSessionId !== this.sessionId)
      throw Error("browser_restart_reopen_required");
    const [tab] = await this.api.tabs.query({
      active: true,
      currentWindow: true,
    });
    if (!Number.isInteger(tab?.id) || (binding && tab.id !== binding.tabId))
      throw Error("application_tab_not_active");
    if (tab.url !== binding.url) throw Error("page_changed");
    return tab;
  }
  // Serializes task versions, native calls and the single active DOM review context.
  dispatch(message) {
    if (["pause", "cancel"].includes(message.action)) cancelPreparedForm();
    const run = this.queue.then(async () => {
      await this.ready;
      return this.handle(message);
    });
    this.queue = run.catch(() => {});
    return run;
  }
  async handle(message) {
    const { action, task_id: id } = message;
    if (action === "list") {
      await this.native("get_agent_capabilities");
      const items = [];
      for (const binding of Object.values(this.bindings)) {
        try {
          items.push(await this.task(binding.id));
        } catch {
          items.push({
            id: binding.id,
            state: "FAILED_RETRYABLE",
            next_action:
              "Reconnect the local backend; no fill will resume automatically.",
            tab_id: binding.tabId,
          });
        }
      }
      return { tasks: items, browser_session_id: this.sessionId };
    }
    if (["destination", "open"].includes(action)) {
      if (!uuid.test(message.application_id || ""))
        throw Error("application_id_required");
      const known = Object.values(this.bindings).find(
        (binding) => binding.applicationId === message.application_id,
      );
      if (known && known.browserSessionId !== this.sessionId)
        await this.update(known.id, "recover");
      const data = await this.native("open_application_task", {
        application_id: message.application_id,
        browser_session_id: this.sessionId,
      });
      let binding = this.accept(data.task);
      await this.persist();
      if (terminal.has(data.task.state))
        throw Error("application_not_eligible");
      if (action === "destination") return { task: data.task };
      const origin = new URL(data.task.target_url).origin;
      if (!(await this.api.permissions.contains({ origins: [origin + "/*"] })))
        throw Error("application_origin_permission_required");
      // Never search, enumerate or read unrelated tabs. Only this saved tab ID.
      if (
        Number.isInteger(binding.tabId) &&
        binding.browserSessionId === this.sessionId
      ) {
        try {
          const existing = await this.api.tabs.get(binding.tabId);
          if (existing.url === binding.url) {
            await this.api.tabs.update(binding.tabId, { active: true });
            return { task: data.task };
          }
        } catch {
          // A closed/replaced saved tab must be released before assigning a new one.
          await this.update(binding.id, "tab_closed");
          binding = this.bindings[binding.id];
        }
      }
      const url = new URL(data.task.target_url);
      if (url.protocol !== "https:" || url.username || url.password)
        throw Error("unsupported_application_page_required");
      const tab = await this.api.tabs.create({ url: url.href, active: true });
      try {
        const task = await this.update(binding.id, "bind", {
          tab_id: tab.id,
          observed_url: url.href,
        });
        return { task };
      } catch (error) {
        // A new tab may remain open, but cannot be used without a durable binding.
        throw error;
      }
    }
    if (action === "inspect") {
      if (id)
        await this.active(
          this.bindings[id] || (await this.task(id), this.bindings[id]),
        );
      return {
        inspection: await inspectOnly({
          interactions_allowed: message.interactions_allowed === true,
        }),
      };
    }
    if (action === "prepare") {
      let binding = id ? (await this.task(id), this.bindings[id]) : null;
      if (binding) await this.active(binding);
      const options = {
        interactions_allowed: message.interactions_allowed === true,
        taskContext: binding ? this.context(binding) : undefined,
      };
      const plan = binding
        ? await inspectForm(binding.applicationId, options)
        : await prepareAnswers(undefined, options);
      if (!binding) {
        const [tab] = await this.api.tabs.query({
          active: true,
          currentWindow: true,
        });
        const data = await this.native("open_application_task", {
          application_id: plan.application_id,
          browser_session_id: this.sessionId,
          tab_id: tab.id,
        });
        binding = this.accept(data.task);
        await this.persist();
        const task = await this.update(binding.id, "inspection_prepared", {
          plan_id: plan.id,
          observed_url: tab.url,
        });
        binding = this.bindings[task.id];
        if (task.state === "CHALLENGE_REQUIRED") {
          plan.state = "read_only";
          plan.inspection.challenge_state = task.challenge_state;
        }
      } else if (plan.task) binding = this.accept(plan.task, binding);
      for (const other of Object.values(this.bindings))
        other.requiresInspection = true;
      binding.documentId = plan.inspection.document_id;
      binding.requiresInspection = false;
      await this.persist();
      // Store review display in trusted session storage, never executable authorization.
      await this.api.storage.session.set({
        applicationReviewV1: { task_id: binding.id, plan },
      });
      return { task: await this.task(binding.id), plan };
    }
    if (!this.bindings[id]) await this.task(id);
    const binding = this.bindings[id];
    if (["pause", "resume", "cancel"].includes(action)) {
      cancelPreparedForm();
      binding.requiresInspection = true;
      const task = await this.update(id, action);
      await this.api.storage.session.remove("applicationReviewV1");
      return { task };
    }
    if (action === "return_control") {
      cancelPreparedForm();
      const saved = this.bindings[id];
      saved.requiresInspection = true;
      let task,
        synchronized = false;
      try {
        task = await this.task(id);
        if (!terminal.has(task.state)) task = await this.update(id, "pause");
        synchronized = true;
      } catch {
        saved.state = "PAUSED";
        await this.persist();
      }
      // Explicit owner takeover must restore the website even if the backend is offline.
      await releaseGuard(this.api, saved.tabId);
      if (synchronized) {
        try {
          task = await this.update(id, "guard_released");
        } catch {
          synchronized = false;
        }
      }
      task = task || {
        id,
        application_id: saved.applicationId,
        state: "PAUSED",
        tab_id: saved.tabId,
      };
      task.network_guard_active = false;
      if (!synchronized)
        task.next_action =
          "Browser control restored locally. Backend synchronization is pending; reconnect before using the assistant.";
      await this.api.storage.session.remove("applicationReviewV1");
      return { task, synchronized };
    }
    if (action === "ask") {
      await this.task(id);
      const data = await this.native(
        "ask_form_questions",
        this.context(this.bindings[id]),
      );
      this.accept(data.task, binding);
      await this.persist();
      return data;
    }
    if (action === "fill") {
      const task = await this.task(id);
      let latest = this.bindings[id];
      if (
        terminal.has(task.state) ||
        ["PAUSED", "CHALLENGE_REQUIRED"].includes(task.state)
      )
        throw Error("task_paused_or_closed");
      if (latest.requiresInspection) throw Error("inspect_and_review_first");
      await this.active(latest);
      // Install before native authorization or any field event. No rule reads bodies.
      await installGuard(this.api, latest.tabId);
      await this.update(id, "guard_installed");
      latest = this.bindings[id];
      if (this.busy.has(binding.tabId)) throw Error("application_tab_busy");
      this.busy.add(binding.tabId);
      binding.requiresInspection = true; // Consume even if native transport fails.
      latest.requiresInspection = true;
      await this.persist();
      let watching = true,
        checking = false;
      const monitor = setInterval(async () => {
        if (!watching || checking) return;
        checking = true;
        try {
          if (!(await guardActive(this.api, latest.tabId))) {
            cancelPreparedForm();
            return;
          }
          const data = await this.native("get_application_task", {
            task_id: id,
          });
          if (
            watching &&
            (terminal.has(data.task?.state) ||
              ["PAUSED", "CHALLENGE_REQUIRED", "FAILED_RETRYABLE"].includes(
                data.task?.state,
              ))
          )
            cancelPreparedForm();
        } catch {
          if (watching) cancelPreparedForm();
        } finally {
          checking = false;
        }
      }, 750);
      try {
        const result = await fillForm({
          interaction_authorized: message.interaction_authorized === true,
          taskContext: this.context(latest),
          field_ids: message.field_ids,
          network_guard: true,
        });
        if (result.task) this.accept(result.task, binding);
        await this.persist();
        await this.api.storage.session.remove("applicationReviewV1");
        const finalTask = result.task || (await this.task(id));
        finalTask.network_guard_active = await guardActive(
          this.api,
          latest.tabId,
        );
        return { result, task: finalTask };
      } finally {
        watching = false;
        clearInterval(monitor);
        this.busy.delete(binding.tabId);
      }
    }
    throw Error("unsupported_assistant_action");
  }
  event(tabId, event, url) {
    // Mark in memory immediately so a concurrent native authorization cannot continue.
    if (
      !Object.values(this.bindings).some(
        (binding) =>
          binding.tabId === tabId &&
          binding.browserSessionId === this.sessionId,
      )
    )
      return Promise.resolve();
    cancelPreparedForm();
    const run = this.queue.then(async () => {
      await this.ready;
      for (const binding of Object.values(this.bindings)) {
        if (
          binding.tabId !== tabId ||
          binding.browserSessionId !== this.sessionId ||
          terminal.has(binding.state)
        )
          continue;
        binding.requiresInspection = true;
        if (event === "tab_closed") await releaseGuard(this.api, tabId);
        try {
          await this.update(
            binding.id,
            event,
            url ? { observed_url: url } : {},
          );
        } catch {
          binding.requiresInspection = true;
          binding.state = "PAUSED";
          await this.persist();
        }
      }
    });
    this.queue = run.catch(() => {});
    return run;
  }
}
