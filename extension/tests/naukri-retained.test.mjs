import test from "node:test";
import assert from "node:assert/strict";
import { continueRetainedQuestionnaire } from "../naukri-retained.js";

function fixture(change = {}) {
  const calls = [];
  const binding = {
    profile_binding_id: "profile",
    browser_session_id: "session",
    window_id: 7,
  };
  const form = {
    id: "retained",
    form_pending: true,
    ownedTabId: 11,
    binding,
    url: "https://www.naukri.com/job-listings-fictional-123456789012",
    ...change.form,
  };
  const session = {
    applicationBrowserSessionV1: "session",
    naukriParkedQuestionnairesV1: change.forms || { retained: form },
    naukriReadInFlightV1: change.inFlight,
  };
  const api = {
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
      session: { get: async (k) => ({ [k]: session[k] }) },
    },
    tabs: {
      get: async () => ({
        id: 11,
        windowId: 7,
        active: false,
        url: form.url,
        ...change.tab,
      }),
    },
    alarms: {
      get: async () => ({ periodInMinutes: 0.5 }),
      clear: async () => calls.push("alarm_paused"),
      create: async () => calls.push("alarm_restored"),
    },
  };
  class Queue {
    constructor(client, send) {
      this.send = send;
    }
    async ownerUsingNaukri() {
      return !!change.ownerActive;
    }
    async tick() {
      calls.push("tick");
      if (change.error) throw Error("fictional_failure");
      await this.send(api, "poll_naukri_work", binding);
      if (change.wait) await change.wait;
    }
  }
  const send = async (client, command, args) => {
    calls.push({ command, args });
    return command === "poll_naukri_work"
      ? { work: change.polled || null }
      : {};
  };
  return { calls, run: () => continueRetainedQuestionnaire(api, send, Queue) };
}

test("same-session original retained tab uses the normal queue and restores heartbeat", async () => {
  const f = fixture();
  await f.run();
  assert.deepEqual(
    f.calls.filter((x) => typeof x === "string"),
    ["alarm_paused", "tick", "alarm_restored"],
  );
  assert.equal(
    f.calls.filter((x) => x.command === "poll_naukri_work").length,
    1,
  );
});
for (const [name, change, error] of [
  ["no parked form", { forms: {} }, "one_retained_questionnaire_required"],
  [
    "owner adoption",
    { form: { ownerAdopted: true } },
    "one_retained_questionnaire_required",
  ],
  [
    "browser restart",
    {
      form: {
        binding: {
          profile_binding_id: "profile",
          browser_session_id: "different",
          window_id: 7,
        },
      },
    },
    "questionnaire_original_browser_context_required",
  ],
  [
    "active original tab",
    { tab: { active: true } },
    "questionnaire_original_tab_unavailable",
  ],
  [
    "changed original URL",
    { tab: { url: "https://example.com" } },
    "questionnaire_original_tab_unavailable",
  ],
  [
    "in-flight work",
    { inFlight: { id: "other" } },
    "background_operation_in_flight",
  ],
  ["owner using provider", { ownerActive: true }, "owner_using_naukri"],
])
  test(`${name} performs no queue operation`, async () => {
    const f = fixture(change);
    await assert.rejects(f.run, new RegExp(error));
    assert.deepEqual(f.calls, []);
  });
test("a failed continuation still restores the heartbeat alarm", async () => {
  const f = fixture({ error: true });
  await assert.rejects(f.run, /fictional_failure/);
  assert.equal(f.calls.at(-1), "alarm_restored");
});
for (const operation of ["apply", "inspect_job", "search_jobs"])
  test(`continuation never admits ${operation}`, async () => {
    const f = fixture({
      polled: {
        id: "other",
        operation,
        revision: 5,
        lease_token: "lease",
        binding: { tab_id: null },
      },
    });
    await f.run();
    const commands = f.calls.filter((x) => x.command).map((x) => x.command);
    assert.deepEqual(commands, ["poll_naukri_work", "abandon_naukri_work"]);
  });
