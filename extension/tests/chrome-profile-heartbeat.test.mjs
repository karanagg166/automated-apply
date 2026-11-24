import assert from "node:assert/strict";
import test from "node:test";
import { profileNative } from "../chrome-profile.js";
import { fixtureNativePort } from "./native-port.fixture.mjs";

function fixture(reply) {
  const requests = [];
  let disconnects = 0;
  const bridge = {
    async sendNativeMessage(host, request) {
      requests.push({ host, request });
      return reply(request);
    },
  };
  const runtime = {
    connectNative(host) {
      const port = fixtureNativePort(bridge, host);
      return {
        ...port,
        disconnect() {
          disconnects++;
          port.disconnect();
        },
      };
    },
    sendNativeMessage() {
      assert.fail("heartbeat used a channel it could not cancel");
    },
  };
  return { api: { runtime }, requests, disconnects: () => disconnects };
}

function response(request, data = { submitted: false }) {
  return { version: 1, request_id: request.request_id, ok: true, data };
}

test("heartbeat closes its native port after one correlated reply", async () => {
  const f = fixture(response);
  assert.deepEqual(await profileNative(f.api, "heartbeat_chrome_profile"), {
    submitted: false,
  });
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].host, "com.automated_apply.agent");
  assert.equal(f.disconnects(), 1);
});

test("a stalled heartbeat closes its native port by the deadline", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let resolveLate;
  const f = fixture(
    (request) =>
      new Promise((resolve) => {
        resolveLate = () => resolve(response(request));
      }),
  );
  const pending = assert.rejects(
    profileNative(f.api, "heartbeat_chrome_profile"),
    { message: "backend_timeout" },
  );
  t.mock.timers.tick(45000);
  await pending;
  assert.equal(f.requests.length, 1);
  assert.equal(f.disconnects(), 1);
  resolveLate();
  await Promise.resolve();
  assert.equal(f.disconnects(), 1);
});

test("a closed native port fails without sending a second heartbeat", async () => {
  const f = fixture(() => {
    throw Error("untrusted disconnected host error");
  });
  await assert.rejects(profileNative(f.api, "heartbeat_chrome_profile"), {
    message: "backend_offline",
  });
  assert.equal(f.requests.length, 1);
});

test("heartbeat rejects a wrong request ID or submission claim", async () => {
  for (const reply of [
    () => response({ request_id: "wrong" }),
    (request) => response(request, { submitted: true }),
  ]) {
    const f = fixture(reply);
    await assert.rejects(profileNative(f.api, "heartbeat_chrome_profile"), {
      message: "native_protocol_error",
    });
    assert.equal(f.disconnects(), 1);
  }
});
