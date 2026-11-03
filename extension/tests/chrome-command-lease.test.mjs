import assert from "node:assert/strict";
import test from "node:test";
import { ChromeProfileConnection } from "../chrome-profile.js";

test("remote execution passes the original shorter lease and fencing identity", async () => {
  const lease = new Date(Date.now() + 45000).toISOString();
  const command = {
    id: crypto.randomUUID(),
    version: 2,
    action: "prepare",
    application_id: crypto.randomUUID(),
    task_id: crypto.randomUUID(),
    packet_revision: 4,
    profile_binding_id: crypto.randomUUID(),
    browser_session_id: crypto.randomUUID(),
    expected_task_version: 7,
    lease_token: crypto.randomUUID(),
    lease_expires_at: lease,
    expires_at: new Date(Date.now() + 120000).toISOString(),
    destination: "https://www.naukri.com/job-listings-fixture-261026028027",
  };
  const stored = {
    connected: true,
    id: command.profile_binding_id,
    secret: "fictional",
    windowId: 1,
  };
  const api = {
    storage: {
      local: {
        get: async () => ({ connectedChromeProfileV1: stored }),
        set: async () => {},
        remove: async () => {},
      },
      session: {
        get: async () => ({
          applicationBrowserSessionV1: command.browser_session_id,
        }),
      },
    },
    runtime: {
      sendNativeMessage: async (_, request) => ({
        version: 1,
        request_id: request.request_id,
        ok: true,
        data: {
          submitted: false,
          command:
            request.command === "poll_chrome_command"
              ? command
              : { ...command, version: 3, state: "executing" },
        },
      }),
    },
  };
  const connection = Object.create(ChromeProfileConnection.prototype);
  Object.assign(connection, {
    api,
    value: { commandsEnabled: true },
    heartbeat: async () => ({
      status: "CONNECTED",
      selected: true,
      commands_enabled: true,
    }),
  });
  let observed;
  await connection.tick(async (message) => {
    observed = message;
  });
  assert.equal(observed.remote_expires_at, lease);
  assert.deepEqual(observed.remote_command_context, {
    chrome_command_id: command.id,
    expected_command_version: 3,
    command_lease_token: command.lease_token,
  });
});
