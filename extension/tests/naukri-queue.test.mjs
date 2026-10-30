import test from "node:test";
import assert from "node:assert/strict";
import { NaukriQueue } from "../naukri-queue.js";

const url = "https://www.naukri.com/job-listings-fictional-291026123456";
function fixture(options = {}) {
  const local = {
    connectedChromeProfileV1: {
      id: "fixture-profile",
      secret: "f".repeat(64),
      connected: true,
      windowId: 10,
    },
  };
  const session = {
    applicationBrowserSessionV1: "fixture-session",
    ...options.session,
  };
  const store = (value) => ({
    get: async (key) => ({ [key]: value[key] }),
    set: async (next) => Object.assign(value, next),
    remove: async (key) => {
      delete value[key];
    },
  });
  const calls = [],
    tabs = new Map();
  let activation;
  let work = {
    id: "fixture",
    revision: 1,
    lease_token: "fixture-token",
    operation: "inspect_job",
    url,
    binding: { tab_id: null, window_id: 10 },
  };
  const api = {
    storage: { local: store(local), session: store(session) },
    permissions: { contains: async () => options.permission !== false },
    tabs: {
      onActivated: {
        addListener: (fn) => {
          activation = fn;
        },
      },
      query: async () => [
        {
          id: 7,
          active: true,
          url: options.ownerNaukri
            ? "https://www.naukri.com/mnjuser/profile"
            : "https://example.com/owner-work",
        },
      ],
      create: async (input) => {
        calls.push(["create", input]);
        const tab = { ...input, id: 44, status: "complete" };
        tabs.set(44, tab);
        return tab;
      },
      get: async (id) => {
        const tab = tabs.get(id);
        if (!tab) throw Error("tab_closed");
        return { ...tab, url: options.redirect || tab.url };
      },
      remove: async (id) => {
        calls.push(["close", id]);
        tabs.delete(id);
      },
      update: async (id, values) => {
        calls.push(["navigate", values]);
        Object.assign(tabs.get(id), values);
        return tabs.get(id);
      },
    },
    scripting: {
      executeScript: async (input) => {
        calls.push(["inspect", input]);
        if (options.adopt) {
          activation({ tabId: 44 });
          tabs.get(44).active = true;
          await Promise.resolve();
          tabs.get(44).active = false;
        }
        return [
          {
            result: { kind: "needs_input", reason: "fictional_unknown_layout" },
          },
        ];
      },
    },
  };
  const send = async (_, name, input) => {
    calls.push([name, input]);
    if (name === "poll_naukri_work")
      return {
        work: options.operation
          ? { ...work, operation: options.operation }
          : work,
      };
    if (options.stop && name === "admit_naukri_work")
      throw Error("queue_lease_lost");
    if (options.lostFinish && name === "finish_naukri_work")
      throw Error("backend_timeout");
    work = {
      ...work,
      revision: work.revision + 1,
      binding: { ...work.binding, tab_id: input.tab_id },
    };
    return { work };
  };
  return {
    api,
    calls,
    session,
    tabs,
    queue: new NaukriQueue(api, send, async () => {}),
  };
}

test("background read creates and closes only its own inactive exact-window tab", async () => {
  const f = fixture();
  await f.queue.tick();
  assert.deepEqual(f.calls.find(([name]) => name === "create")[1], {
    url: "about:blank",
    active: false,
    windowId: 10,
  });
  assert.deepEqual(f.calls.find(([name]) => name === "inspect")[1].target, {
    tabId: 44,
    frameIds: [0],
  });
  assert.equal(
    f.calls.find(([name]) => name === "inspect")[1].world,
    "ISOLATED",
  );
  assert.deepEqual(
    f.calls.filter(([name]) => name === "close"),
    [["close", 44]],
  );
  assert.equal(f.session.naukriReadInFlightV1, undefined);
  assert.equal(
    f.calls.filter(([name]) => name === "admit_naukri_work").length,
    1,
  );
});

for (const [name, options] of [
  ["missing origin permission", { permission: false }],
  ["owner working on Naukri", { ownerNaukri: true }],
]) {
  test(`${name} creates no tab, reads no DOM and polls no work`, async () => {
    const f = fixture(options);
    await f.queue.tick();
    assert.deepEqual(f.calls, []);
  });
}
test("owner adoption is permanent for this tab even after switching away", async () => {
  const f = fixture({ adopt: true });
  await f.queue.tick();
  assert.equal(
    f.calls.some(([name]) => name === "close"),
    false,
  );
  assert.equal(f.tabs.size, 1);
});
test("redirect prevents DOM access and closes only the created inactive tab", async () => {
  const f = fixture({ redirect: "https://accounts.example.com/login" });
  await f.queue.tick();
  assert.equal(
    f.calls.some(([name]) => name === "inspect"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "provider_context_changed",
  );
});
test("Stop before read admission prevents DOM access", async () => {
  const f = fixture({ stop: true });
  await f.queue.tick();
  assert.equal(
    f.calls.some(([name]) => name === "inspect"),
    false,
  );
});
test("the observer cannot execute a queued Apply operation", async () => {
  const f = fixture({ operation: "apply" });
  await f.queue.tick();
  assert.equal(
    f.calls.some(([name]) => name === "create"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "background_operation_not_supported",
  );
});
test("lost finish response never repeats inspection or admission", async () => {
  const f = fixture({ lostFinish: true });
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, 1);
  assert.equal(
    f.calls.filter(([name]) => name === "admit_naukri_work").length,
    1,
  );
});
test("restart abandons the saved read before polling without replaying the old tab", async () => {
  const pending = {
    id: "old",
    revision: 4,
    lease_token: "old-token",
    operation: "inspect_job",
    url,
    binding: { tab_id: 55, window_id: 10 },
    ownedTabId: 55,
    ownerAdopted: true,
  };
  const f = fixture({
    session: { naukriReadInFlightV1: pending },
    permission: false,
  });
  await f.queue.tick();
  assert.equal(f.calls[0][0], "abandon_naukri_work");
  assert.equal(f.calls[0][1].work_id, "old");
  assert.equal(
    f.calls.some(
      ([name]) => name === "create" || name === "inspect" || name === "close",
    ),
    false,
  );
});
test("concurrent alarms share one consumer run", async () => {
  const f = fixture();
  await Promise.all([f.queue.tick(), f.queue.tick()]);
  assert.equal(
    f.calls.filter(([name]) => name === "poll_naukri_work").length,
    1,
  );
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
});
