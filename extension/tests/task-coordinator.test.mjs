import test from "node:test";
import assert from "node:assert/strict";
import { TaskCoordinator } from "../task-coordinator.js";
import { fixtureNativePort } from "./native-port.fixture.mjs";
const app = "11111111-1111-4111-8111-111111111111";
const taskId = "22222222-2222-4222-8222-222222222222";
const url = "https://jobs.lever.co/fictional/fictional/apply";
function fixture() {
  const local = {
      connectedChromeProfileV1: {
        id: "a1111111-1111-4111-8111-111111111111",
        secret: "f".repeat(64),
        connected: true,
        windowId: 10,
      },
    },
    session = {},
    calls = [],
    tabs = new Map();
  let active = 7;
  let guardRules = [];
  const task = {
    id: taskId,
    application_id: app,
    profile_binding_id: local.connectedChromeProfileV1.id,
    packet_revision: 1,
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
    alarms: { create: async () => {}, clear: async () => {} },
    windows: {
      get: async (id) => ({ id, type: "normal" }),
      getLastFocused: async () => ({ id: 10, type: "normal" }),
      update: async () => {},
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
        const tab = { id: 7, windowId: data.windowId, url: data.url };
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
      connectNative: (host) => fixtureNativePort(api.runtime, host),
      sendNativeMessage: async (_host, request) => {
        calls.push(request);
        if (request.command === "heartbeat_chrome_profile")
          return {
            version: 1,
            ok: true,
            request_id: request.request_id,
            data: {
              submitted: false,
              profile: {
                id: request.profile_binding_id,
                selected: true,
                connected: true,
                status: "CONNECTED",
                version: 1,
              },
            },
          };
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
            task.window_id = request.window_id;
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

test("expired remote command cannot open or inspect any tab", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await assert.rejects(
    coordinator.dispatch({
      action: "open",
      application_id: app,
      remote_command: true,
      remote_expires_at: "2000-01-01T00:00:00Z",
    }),
    /profile_command_expired/,
  );
  assert.equal(f.tabs.size, 0);
  assert.equal(
    f.calls.some((value) => value.command === "open_application_task"),
    false,
  );
});

test("remote open creates an inactive tab and reuses it without focusing its window", async () => {
  const f = fixture();
  const coordinator = new TaskCoordinator(f.api);
  const create = f.api.tabs.create;
  const created = [];
  f.api.tabs.create = async (options) => {
    created.push(options);
    return create(options);
  };
  f.api.windows.update = f.api.tabs.update = async () => {
    throw Error("remote_open_must_not_change_focus");
  };
  const message = {
    action: "open",
    application_id: app,
    expected_task_version: f.task.version,
    expected_packet_revision: f.task.packet_revision,
    expected_destination: url,
    remote_command: true,
    remote_expires_at: new Date(Date.now() + 120000).toISOString(),
  };
  const opened = await coordinator.dispatch(message);
  const reused = await coordinator.dispatch({
    ...message,
    expected_task_version: opened.task.version,
  });
  assert.deepEqual(created, [{ url, active: false, windowId: 10 }]);
  assert.equal(reused.task.tab_id, opened.task.tab_id);
});

test("revoked origin permission blocks remote preparation before any DOM read", async () => {
  const f = fixture(),
    coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  f.api.permissions.contains = async () => false;
  await assert.rejects(
    coordinator.dispatch({
      action: "prepare",
      application_id: app,
      task_id: taskId,
      expected_task_version: f.task.version,
      expected_packet_revision: f.task.packet_revision,
      expected_destination: url,
      expected_profile_binding_id: f.task.profile_binding_id,
      expected_browser_session_id: f.task.browser_session_id,
      remote_command: true,
      remote_expires_at: new Date(Date.now() + 120000).toISOString(),
    }),
    /application_origin_permission_required/,
  );
  assert.equal(
    f.calls.some((value) => value.command === "inspect_form"),
    false,
  );
});

async function boundPreparation() {
  const f = fixture();
  const coordinator = new TaskCoordinator(f.api);
  await coordinator.dispatch({ action: "open", application_id: app });
  const message = {
    action: "prepare",
    application_id: app,
    task_id: taskId,
    expected_task_version: f.task.version,
    expected_packet_revision: f.task.packet_revision,
    expected_destination: url,
    expected_profile_binding_id: f.task.profile_binding_id,
    expected_browser_session_id: f.task.browser_session_id,
    remote_command: true,
    remote_expires_at: new Date(Date.now() + 120000).toISOString(),
  };
  f.active(99);
  f.api.tabs.query = async () => {
    throw Error("unrelated_tab_must_not_be_queried");
  };
  f.api.windows.update = f.api.tabs.update = async () => {
    throw Error("preparation_must_not_change_focus");
  };
  f.api.scripting = {
    executeScript: async (request) => {
      f.calls.push({ script: request });
      return [
        { result: { document_id: app, url, state: "ready", fields: [] } },
      ];
    },
  };
  const native = f.api.runtime.sendNativeMessage;
  f.api.runtime.sendNativeMessage = async (host, request) => {
    const response = await native(host, request);
    if (request.command === "inspect_form") {
      f.task.version++;
      f.task.state = "FORM_INSPECTED";
      response.data.task = structuredClone(f.task);
      response.data.plan = {
        id: app,
        target_url: url,
        inspection: request.inspection,
        actions: [],
      };
    }
    return response;
  };
  global.chrome = f.api;
  f.calls.length = 0;
  return { ...f, coordinator, message };
}

test("remote Prepare reads only the exact bound tab in its stored window without focus or filling", async () => {
  const f = await boundPreparation();
  // Profile Open defaults are independent of an already bound task's window.
  f.local.connectedChromeProfileV1.windowId = 20;
  const result = await f.coordinator.dispatch({
    ...f.message,
    interactions_allowed: true,
  });
  assert.equal(result.task.state, "FORM_INSPECTED");
  const scripts = f.calls.filter((call) => call.script);
  assert.equal(scripts.length, 1);
  assert.deepEqual(scripts[0].script.target, { tabId: 7, frameIds: [0] });
  assert.deepEqual(scripts[0].script.args, [
    { operation: "inspect", only_empty: true },
  ]);
  const inspection = f.calls.find((call) => call.command === "inspect_form");
  assert.equal(inspection.tab_id, 7);
  assert.equal(inspection.window_id, 10);
  assert.equal(
    inspection.profile_binding_id,
    f.message.expected_profile_binding_id,
  );
  assert.equal(
    inspection.browser_session_id,
    f.message.expected_browser_session_id,
  );
  assert.equal(
    f.calls.some((call) => call.command === "authorize_form"),
    false,
  );
  assert.ok(
    f.calls
      .filter((call) => typeof call === "string")
      .every((call) => call === "get:7"),
  );
});

for (const [name, change, error] of [
  [
    "different profile",
    (f) => {
      f.task.profile_binding_id = app;
    },
    /PROFILE_NOT_SELECTED/,
  ],
  [
    "old browser session",
    (f) => {
      f.task.browser_session_id = app;
    },
    /browser_restart_reopen_required/,
  ],
  [
    "closed tab",
    (f) => {
      f.tabs.delete(7);
    },
    /closed/,
  ],
  [
    "moved window",
    (f) => {
      f.tabs.get(7).windowId = 20;
    },
    /page_changed/,
  ],
  [
    "navigated URL",
    (f) => {
      f.tabs.get(7).url = url + "?other";
    },
    /page_changed/,
  ],
  [
    "pending navigation",
    (f) => {
      f.tabs.get(7).pendingUrl = url;
    },
    /page_changed/,
  ],
  [
    "loading document",
    (f) => {
      f.tabs.get(7).status = "loading";
    },
    /page_changed/,
  ],
  [
    "discarded document",
    (f) => {
      f.tabs.get(7).discarded = true;
    },
    /page_changed/,
  ],
  [
    "incognito tab",
    (f) => {
      f.tabs.get(7).incognito = true;
    },
    /page_changed/,
  ],
  [
    "non-normal window",
    (f) => {
      f.api.windows.get = async () => ({ type: "popup" });
    },
    /extension_tab_binding_mismatch/,
  ],
  [
    "packet revision",
    (f) => {
      f.message.expected_packet_revision++;
    },
    /extension_task_context_stale/,
  ],
  [
    "task revision",
    (f) => {
      f.message.expected_task_version++;
    },
    /extension_task_revision_conflict/,
  ],
  [
    "command profile",
    (f) => {
      f.message.expected_profile_binding_id = app;
    },
    /extension_task_context_stale/,
  ],
  [
    "command session",
    (f) => {
      f.message.expected_browser_session_id = app;
    },
    /extension_task_context_stale/,
  ],
  [
    "command destination",
    (f) => {
      f.message.expected_destination = url + "?other";
    },
    /extension_task_context_stale/,
  ],
  [
    "unbound remote command",
    (f) => {
      delete f.message.task_id;
    },
    /extension_task_required/,
  ],
  [
    "expiry during validation",
    (f) => {
      f.api.permissions.contains = async () => {
        f.message.remote_expires_at = "2000-01-01T00:00:00Z";
        return true;
      };
    },
    /profile_command_expired/,
  ],
]) {
  test(`remote Prepare rejects ${name} before DOM access`, async () => {
    const f = await boundPreparation();
    change(f);
    await assert.rejects(f.coordinator.dispatch(f.message), error);
    assert.equal(
      f.calls.some((call) => call.script),
      false,
    );
    assert.equal(
      f.calls.some((call) => call.command === "inspect_form"),
      false,
    );
  });
}

test("bound Prepare revalidates permission after DOM inspection before storing a plan", async () => {
  const f = await boundPreparation();
  const execute = f.api.scripting.executeScript;
  f.api.scripting.executeScript = async (request) => {
    const result = await execute(request);
    f.api.permissions.contains = async () => false;
    return result;
  };
  await assert.rejects(
    f.coordinator.dispatch(f.message),
    /application_origin_permission_required/,
  );
  assert.equal(f.calls.filter((call) => call.script).length, 1);
  assert.equal(
    f.calls.some((call) => call.command === "inspect_form"),
    false,
  );
});
