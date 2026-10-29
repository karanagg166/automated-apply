import test from "node:test";
import assert from "node:assert/strict";
import { TaskCoordinator } from "../task-coordinator.js";
const app = "11111111-1111-4111-8111-111111111111";
const taskId = "22222222-2222-4222-8222-222222222222";
const url = "https://jobs.lever.co/fictional/fictional/apply";
function fixture() {
  const local = {},
    session = {},
    calls = [],
    tabs = new Map();
  let active = 7;
  let guardRules = [];
  const task = {
    id: taskId,
    application_id: app,
    job_id: app,
    version: 1,
    state: "PACKET_READY",
    target_url: url,
    current_url: url,
    tab_id: null,
    browser_session_id: null,
  };
  const store = (source) => ({
    get: async (key) => ({ [key]: source[key] }),
    set: async (values) => Object.assign(source, values),
    remove: async (key) => {
      delete source[key];
    },
    setAccessLevel: async () => {},
  });
  const api = {
    storage: { local: store(local), session: store(session) },
    permissions: {
      contains: async (request) => {
        if (request.origins)
          assert.deepEqual(request.origins, ["https://jobs.lever.co/*"]);
        else assert.deepEqual(request.permissions, ["declarativeNetRequest"]);
        return true;
      },
    },
    tabs: {
      query: async (filter) => {
        assert.deepEqual(filter, { active: true, currentWindow: true });
        calls.push("query_active");
        return [tabs.get(active)];
      },
      get: async (id) => {
        calls.push(`get:${id}`);
        if (!tabs.has(id)) throw Error("closed");
        return tabs.get(id);
      },
      update: async (id) => {
        calls.push(`activate:${id}`);
        active = id;
        return tabs.get(id);
      },
      create: async (data) => {
        calls.push("create");
        const tab = { id: 7, url: data.url };
        tabs.set(7, tab);
        return tab;
      },
    },
    declarativeNetRequest: {
      getSessionRules: async () => structuredClone(guardRules),
      updateSessionRules: async ({ removeRuleIds = [], addRules = [] }) => {
        guardRules = [
          ...guardRules.filter((rule) => !removeRuleIds.includes(rule.id)),
          ...addRules,
        ];
      },
    },
    runtime: {
      sendNativeMessage: async (_host, request) => {
        calls.push(request);
        if (request.command === "get_agent_capabilities")
          return {
            version: 1,
            ok: true,
            request_id: request.request_id,
            data: { submissions: false },
          };
        if (request.command === "open_application_task")
          task.browser_session_id = request.browser_session_id;
        if (request.command === "update_application_task") {
          assert.equal(request.expected_task_version, task.version);
          task.version++;
          if (
            ["guard_installed", "guard_released"].includes(request.task_event)
          )
            task.network_guard_active =
              request.task_event === "guard_installed";
          else if (request.task_event === "bind") {
            if (
              task.state === "PAUSED" &&
              ["owner_pause", "global_stop"].includes(task.reason)
            ) {
              return {
                version: 1,
                ok: false,
                request_id: request.request_id,
                error_code: "extension_task_paused_or_cancelled",
              };
            }
            task.tab_id = request.tab_id;
            task.state = "PACKET_READY";
          } else if (request.task_event === "recover") {
            task.tab_id = null;
            task.browser_session_id = request.browser_session_id;
            task.state = "PAUSED";
          } else if (request.task_event === "tab_closed") {
            task.tab_id = null;
            if (!["owner_pause", "global_stop"].includes(task.reason)) {
              task.reason = "tab_closed";
            }
            task.state = "PAUSED";
          } else if (request.task_event === "pause") {
            task.state = "PAUSED";
            task.reason = "owner_pause";
          } else if (request.task_event === "resume") {
            task.reason = "owner_resume";
            task.state = task.tab_id ? "PACKET_READY" : "PAUSED";
          } else {
            task.state =
              request.task_event === "cancel" ? "FAILED_FINAL" : "PAUSED";
          }
        }
        return {
          version: 1,
          ok: true,
          request_id: request.request_id,
          data: { task: structuredClone(task), submitted: false },
        };
      },
    },
  };
  return {
    api,
    local,
    session,
    calls,
    tabs,
    task,
    active: (id) => {
      active = id;
    },
  };
}
test("Open binds exact packet destination to only the dedicated tab and reuses it on repeated click", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  await coordinator.dispatch({ action: "open", application_id: app });
  assert.equal(f.calls.filter((item) => item === "create").length, 1);
  assert.ok(f.calls.includes("get:7"));
  assert.equal(coordinator.bindings[taskId].applicationId, app);
  assert.equal(coordinator.bindings[taskId].tabId, 7);
  assert.equal(JSON.stringify(f.local).includes("candidate"), false);
});
test("worker restart restores pending identity and requires fresh inspection without automatic fill", async () => {
  const f = fixture(),
    first = new TaskCoordinator(f.api);
  await first.dispatch({ action: "open", application_id: app });
  first.bindings[taskId].requiresInspection = false;
  await first.persist();
  const restarted = new TaskCoordinator(f.api);
  await restarted.ready;
  assert.equal(restarted.bindings[taskId].requiresInspection, true);
  await assert.rejects(
    restarted.dispatch({ action: "fill", task_id: taskId }),
    /inspect_and_review_first|task_paused_or_closed/,
  );
  assert.equal(
    f.calls.filter((item) => item.command === "authorize_form").length,
    0,
  );
});
test("browser restart never trusts a stale tab ID in another browser session", async () => {
  const f = fixture(),
    first = new TaskCoordinator(f.api);
  await first.dispatch({ action: "open", application_id: app });
  delete f.session.applicationBrowserSessionV1;
  const restarted = new TaskCoordinator(f.api);
  await restarted.ready;
  assert.equal(restarted.bindings[taskId].tabId, null);
  assert.equal(restarted.bindings[taskId].requiresInspection, true);
  await assert.rejects(
    restarted.active(restarted.bindings[taskId]),
    /application_tab_not_active/,
  );
});
test("unrelated tab navigation is ignored without reading its URL or invalidating application task", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  const before = f.calls.length;
  await coordinator.event(99, "navigation", "https://personal.example/private");
  assert.equal(f.calls.length, before);
  assert.equal(f.task.state, "PACKET_READY");
});
test("bound navigation and tab closure persist a paused state and invalidate fill context", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  await coordinator.event(7, "navigation", url + "?step=2");
  assert.equal(coordinator.bindings[taskId].requiresInspection, true);
  assert.equal(f.task.state, "PAUSED");
  await coordinator.event(7, "tab_closed");
  assert.ok(f.calls.some((item) => item.task_event === "tab_closed"));
});
test("dashboard cancellation is fetched before fill and blocks execution", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  coordinator.bindings[taskId].requiresInspection = false;
  f.task.state = "FAILED_FINAL";
  await assert.rejects(
    coordinator.dispatch({ action: "fill", task_id: taskId }),
    /task_paused_or_closed/,
  );
  assert.equal(
    f.calls.filter((item) => item.command === "authorize_form").length,
    0,
  );
});
test("concurrent Open calls serialize and cannot create two workers for one tab", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await Promise.all([
    coordinator.dispatch({ action: "open", application_id: app }),
    coordinator.dispatch({ action: "open", application_id: app }),
  ]);
  assert.equal(f.calls.filter((item) => item === "create").length, 1);
});
test("native correlation mismatch never opens a tab", async () => {
  const f = fixture();
  f.api.runtime.sendNativeMessage = async () => ({
    version: 1,
    ok: true,
    request_id: app,
    data: { task: f.task, submitted: false },
  });
  const coordinator = new TaskCoordinator(f.api);
  await assert.rejects(
    coordinator.dispatch({ action: "open", application_id: app }),
    /native_protocol_error/,
  );
  assert.equal(f.tabs.size, 0);
});

test("Open refuses absent origin permission before creating or reading an application tab", async () => {
  const f = fixture();
  f.api.permissions.contains = async () => false;
  const coordinator = new TaskCoordinator(f.api);
  await assert.rejects(
    coordinator.dispatch({ action: "open", application_id: app }),
    /application_origin_permission_required/,
  );
  assert.equal(f.tabs.size, 0);
});

test("destination review creates no tab or permission grant", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  const result = await coordinator.dispatch({
    action: "destination",
    application_id: app,
  });
  assert.equal(result.task.target_url, url);
  assert.equal(f.tabs.size, 0);
});

test("worker restart cancels the exact saved document before pausing its task", async () => {
  const f = fixture(),
    first = new TaskCoordinator(f.api);
  await first.dispatch({ action: "open", application_id: app });
  first.bindings[taskId].documentId = app;
  await first.persist();
  const interrupted = [];
  f.api.scripting = {
    executeScript: async (request) => {
      interrupted.push(request);
      return [{ result: { state: "manual_required", submitted: false } }];
    },
  };
  const restarted = new TaskCoordinator(f.api);
  await restarted.ready;
  assert.equal(interrupted.length, 1);
  assert.deepEqual(interrupted[0].target, { tabId: 7, frameIds: [0] });
  assert.deepEqual(interrupted[0].args, [
    { operation: "cancel_fill", document_id: app },
  ]);
  assert.ok(f.calls.some((request) => request.task_event === "worker_restart"));
});

test("binding a replacement tab is denied during owner pause until authorized resume", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  assert.equal(coordinator.bindings[taskId].tabId, 7);

  // 1. Owner pauses the task
  await coordinator.dispatch({ action: "pause", task_id: taskId });
  assert.equal(coordinator.bindings[taskId].state, "PAUSED");
  assert.equal(coordinator.bindings[taskId].reason, "owner_pause");

  // 2. Tab is closed
  f.tabs.delete(7);
  // Re-opening while paused must reject and refuse to bind a replacement tab
  await assert.rejects(
    coordinator.dispatch({ action: "open", application_id: app }),
    /extension_task_paused_or_cancelled/,
  );
  // Binding remains absent / paused
  assert.equal(coordinator.bindings[taskId].state, "PAUSED");
  assert.equal(coordinator.bindings[taskId].reason, "owner_pause");

  // 3. Authorized resume clears the owner pause
  await coordinator.dispatch({ action: "resume", task_id: taskId });
  assert.equal(coordinator.bindings[taskId].reason, "owner_resume");

  // 4. Now opening creates and binds the new replacement tab
  const reopened = await coordinator.dispatch({
    action: "open",
    application_id: app,
  });
  assert.equal(reopened.task.state, "PACKET_READY");
  assert.equal(coordinator.bindings[taskId].tabId, 7);
  assert.equal(coordinator.bindings[taskId].requiresInspection, true);
});
