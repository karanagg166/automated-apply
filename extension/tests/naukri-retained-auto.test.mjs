import test from "node:test";
import assert from "node:assert/strict";
import {
  retainedAlarmController,
  retainedAlarm,
  retainedControllerKey,
} from "../naukri-retained.js";

const id = "11111111-1111-4111-8111-111111111111";
function fixture(t, changes = {}) {
  let time = 1000000;
  const settings = {
    id: 23,
    active: false,
    url: "chrome-extension://fixture/settings.html",
  };
  const form = {
    id,
    form_pending: true,
    ownedTabId: 11,
    binding: {
      profile_binding_id: "profile",
      browser_session_id: "session",
      window_id: 7,
    },
    url: "https://www.naukri.com/job-listings-fictional-123456789012",
  };
  const data = {
    applicationBrowserSessionV1: "session",
    naukriParkedQuestionnairesV1: { [id]: form },
  };
  const alarms = new Map([
    ["connected-chrome-heartbeat", { periodInMinutes: 0.5 }],
  ]);
  const listeners = new Set(),
    calls = [],
    statuses = [];
  const api = {
    runtime: { getURL: (p) => "chrome-extension://fixture/" + p },
    storage: {
      local: {
        get: async (k) => ({
          [k]: {
            id: "profile",
            secret: "private",
            connected: true,
            windowId: 7,
          },
        }),
      },
      session: {
        get: async (k) => ({ [k]: data[k] }),
        set: async (v) => Object.assign(data, v),
        remove: async (k) => {
          delete data[k];
        },
      },
    },
    tabs: {
      getCurrent: async () => settings,
      get: async () => ({
        id: 11,
        active: false,
        windowId: 7,
        url: form.url,
        ...changes.original,
      }),
    },
    alarms: {
      get: async (n) => alarms.get(n),
      clear: async (n) => alarms.delete(n),
      create: async (n, v) => {
        if (changes.createFailure && n === retainedAlarm)
          throw Error("alarm_failed");
        alarms.set(n, v);
      },
      onAlarm: {
        addListener: (f) => listeners.add(f),
        removeListener: (f) => listeners.delete(f),
      },
    },
  };
  const controller = retainedAlarmController(
    api,
    changes.heartbeat ||
      (async (work) => {
        calls.push({ heartbeat: work });
        return { ok: true, connected: !changes.offline };
      }),
    (s) => statuses.push(s),
    changes.run || (async (...args) => calls.push({ run: args.slice(3) })),
    () => time,
  );
  t.after(async () => {
    await controller.stop();
    controller.dispose();
  });
  return {
    api,
    controller,
    data,
    alarms,
    listeners,
    calls,
    statuses,
    settings,
    form,
    advance: (n) => {
      time += n;
    },
  };
}

test("alarms continue only the bound existing form with explicit discovery scope", async (t) => {
  const f = fixture(t);
  await f.controller.start(id, true);
  assert.equal(f.alarms.has("connected-chrome-heartbeat"), false);
  assert.deepEqual(f.alarms.get(retainedAlarm), { periodInMinutes: 0.5 });
  assert.deepEqual(
    f.calls.filter((c) => c.run).map((c) => c.run),
    [[id, true]],
  );
  await Promise.all([...f.listeners].map((fn) => fn({ name: "unrelated" })));
  assert.equal(f.calls.filter((c) => c.run).length, 1);
  await f.controller.tick();
  assert.equal(f.calls.filter((c) => c.run).length, 2);
  assert.equal(f.statuses.at(-1).state, "running");
});
for (const change of ["active", "url"])
  test(`an ${change} settings context cannot start automation`, async (t) => {
    const f = fixture(t);
    f.settings[change] =
      change === "active" ? true : "https://example.invalid/";
    await assert.rejects(
      f.controller.start(id, true),
      /inactive_retained_settings_required/,
    );
    assert.equal(f.calls.length, 0);
    assert.equal(f.alarms.has("connected-chrome-heartbeat"), true);
  });

test("another settings tab cannot resume or overwrite the current controller", async (t) => {
  const f = fixture(t);
  f.data[retainedControllerKey] = {
    settings_tab_id: 99,
    work_id: id,
    expires_at: 2000000,
  };
  assert.equal(await f.controller.resume(), false);
  await assert.rejects(
    f.controller.start(id, true),
    /another_retained_controller_exists/,
  );
  assert.equal(f.calls.length, 0);
});

test("same settings tab can restore its pending controller without Apply or a new form", async (t) => {
  const f = fixture(t);
  await f.controller.start(id, false);
  f.controller.dispose();
  assert.equal(await f.controller.resume(), true);
  assert.deepEqual(
    f.calls.filter((c) => c.run).map((c) => c.run),
    [
      [id, false],
      [id, false],
    ],
  );
});
for (const change of ["ownerAdopted", "form_pending"])
  test(`${change} ends continuation and restores the old heartbeat`, async (t) => {
    const f = fixture(t);
    await f.controller.start(id, true);
    f.form[change] = change === "ownerAdopted";
    await f.controller.tick();
    assert.equal(f.data[retainedControllerKey], undefined);
    assert.equal(f.alarms.has(retainedAlarm), false);
    assert.equal(f.alarms.has("connected-chrome-heartbeat"), true);
    assert.equal(f.calls.filter((c) => c.run).length, 1);
  });

test("expired continuation stops instead of extending its lifetime", async (t) => {
  const f = fixture(t);
  await f.controller.start(id, true);
  f.advance(2 * 86400000 + 1);
  await f.controller.tick();
  assert.equal(f.calls.filter((c) => c.run).length, 1);
  assert.equal(f.alarms.has("connected-chrome-heartbeat"), true);
});

test("offline heartbeat performs no queue work and can recover on the next alarm", async (t) => {
  let online = false;
  const f = fixture(t, {
    heartbeat: async () => ({ ok: true, connected: online }),
  });
  await f.controller.start(id, true);
  assert.equal(f.calls.length, 0);
  assert.equal(f.statuses.at(-1).reason, "profile_unavailable");
  online = true;
  await f.controller.tick();
  assert.equal(f.calls.filter((c) => c.run).length, 1);
});

test("alarm setup failure restores the old heartbeat and clears its intent", async (t) => {
  const f = fixture(t, { createFailure: true });
  await assert.rejects(f.controller.start(id, true), /alarm_failed/);
  assert.equal(f.data[retainedControllerKey], undefined);
  assert.equal(f.alarms.has("connected-chrome-heartbeat"), true);
  assert.equal(f.calls.length, 0);
});

test("stop during a pending heartbeat fences the late continuation", async (t) => {
  let release, entered;
  const enteredPromise = new Promise((r) => {
    entered = r;
  });
  const f = fixture(t, {
    heartbeat: () =>
      new Promise((r) => {
        release = r;
        entered();
      }),
  });
  const pending = f.controller.start(id, true);
  await enteredPromise;
  await f.controller.stop();
  release({ ok: true, connected: true });
  await pending;
  assert.equal(f.calls.length, 0);
  assert.equal(f.alarms.has("connected-chrome-heartbeat"), true);
});

test("an active settings tab yields and a later inactive alarm resumes", async (t) => {
  const f = fixture(t);
  await f.controller.start(id, true);
  f.settings.active = true;
  await f.controller.tick();
  assert.equal(f.calls.filter((c) => c.run).length, 1);
  f.settings.active = false;
  await f.controller.tick();
  assert.equal(f.calls.filter((c) => c.run).length, 2);
});
