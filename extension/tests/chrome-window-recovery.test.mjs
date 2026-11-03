import assert from "node:assert/strict";
import test from "node:test";
import { ChromeProfileConnection } from "../chrome-profile.js";

function fixture(overrides = {}) {
  const value = {
    id: "fixture",
    secret: "f".repeat(64),
    connected: true,
    commandsEnabled: true,
    windowId: 10,
  };
  const requests = [],
    created = [];
  let window;
  const api = {
    storage: {
      local: {
        get: async () => ({ connectedChromeProfileV1: value }),
        set: async () => {},
      },
      session: {
        get: async () => ({ applicationBrowserSessionV1: "session" }),
      },
    },
    windows: {
      get: async (id) => {
        if (window?.id === id) return window;
        throw Error("closed");
      },
      getLastFocused: async () => {
        throw Error("no window");
      },
      create: async (input) => {
        created.push(input);
        window = { id: 20, type: "normal", incognito: false, focused: false };
        return window;
      },
    },
    runtime: {
      sendNativeMessage: async (_, input) => {
        requests.push(input);
        return {
          version: 1,
          request_id: input.request_id,
          ok: true,
          data: {
            submitted: false,
            background_window_allowed: true,
            profile: {
              id: value.id,
              connected: true,
              selected: true,
              commands_enabled: true,
              status:
                input.window_id === null ? "PROFILE_OFFLINE" : "CONNECTED",
              ...overrides,
            },
          },
        };
      },
    },
  };
  const connection = Object.assign(
    Object.create(ChromeProfileConnection.prototype),
    { api, value, ready: Promise.resolve() },
  );
  return { connection, created, requests, api };
}

test("concurrent heartbeats recover one inactive blank window and bind it before returning", async () => {
  const { connection, created, requests } = fixture();
  const results = await Promise.all([
    connection.heartbeat(),
    connection.heartbeat(),
  ]);
  assert.deepEqual(created, [
    { type: "normal", focused: false, url: "about:blank" },
  ]);
  assert.deepEqual(
    requests.map((r) => r.window_id),
    [null, 20, 20],
  );
  assert.ok(results.every((r) => r.status === "CONNECTED"));
  assert.ok(requests.every((r) => r.command === "heartbeat_chrome_profile"));
});

for (const change of ["policy", "selection", "identity", "consent"]) {
  test(`no window recovery without ${change}`, async () => {
    const overrides =
      change === "selection"
        ? { selected: false }
        : change === "identity"
          ? { id: "other" }
          : change === "consent"
            ? { commands_enabled: false }
            : {};
    const { connection, created, api } = fixture(overrides);
    if (change === "policy") {
      const original = api.runtime.sendNativeMessage;
      api.runtime.sendNativeMessage = async (...args) => {
        const response = await original(...args);
        response.data.background_window_allowed = false;
        return response;
      };
    }
    await connection.heartbeat();
    assert.deepEqual(created, []);
  });
}

test("failed binding after creation cannot cause an unbounded window-creation loop", async () => {
  const { connection, created, requests, api } = fixture();
  api.windows.get = async () => {
    throw Error("closed again");
  };
  await connection.heartbeat();
  assert.equal(created.length, 1);
  assert.deepEqual(
    requests.map((r) => r.window_id),
    [null, null],
  );
});

test("an older server without recovery support cannot dispatch from a windowless profile", async () => {
  const { connection, created, requests, api } = fixture({
    status: "CONNECTED",
  });
  const original = api.runtime.sendNativeMessage;
  api.runtime.sendNativeMessage = async (...args) => {
    const response = await original(...args);
    delete response.data.background_window_allowed;
    return response;
  };
  let idleCalls = 0;
  await connection.tick(undefined, () => {
    idleCalls++;
  });
  assert.equal(idleCalls, 0);
  assert.deepEqual(created, []);
  assert.deepEqual(
    requests.map((r) => r.command),
    ["heartbeat_chrome_profile"],
  );
  assert.equal(connection.value.profile.status, "PROFILE_OFFLINE");
});
