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
        assert.deepEqual(request.origins, ["https://jobs.lever.co/*"]);
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
          if (request.task_event === "bind") task.tab_id = request.tab_id;
          else if (request.task_event === "recover") {
            task.tab_id = null;
            task.browser_session_id = request.browser_session_id;
            task.state = "PAUSED";
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
