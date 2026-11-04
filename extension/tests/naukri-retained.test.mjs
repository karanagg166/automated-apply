import test from "node:test";
import assert from "node:assert/strict";
import {
  continueRetainedQuestionnaire,
  inspectUnansweredRetainedForm,
} from "../naukri-retained.js";

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
  return {
    calls,
    run: () => continueRetainedQuestionnaire(api, send, Queue, change.identity),
  };
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

test("an explicit retained identity selects only that form and leaves other uncertain forms alone", async () => {
  const forms = {
    retained: {
      id: "retained",
      form_pending: true,
      ownedTabId: 11,
      binding: {
        profile_binding_id: "profile",
        browser_session_id: "session",
        window_id: 7,
      },
      url: "https://www.naukri.com/job-listings-fictional-123456789012",
    },
    uncertain: { id: "uncertain", form_pending: true, ownedTabId: 12 },
  };
  const f = fixture({ forms, identity: "retained" });
  await f.run();
  assert.equal(
    f.calls.filter((x) => x.command === "poll_naukri_work").length,
    1,
  );
  assert.equal(forms.uncertain.ownedTabId, 12);
  const bad = fixture({ forms, identity: "absent" });
  await assert.rejects(bad.run, /one_retained_questionnaire_required/);
  assert.deepEqual(bad.calls, []);
});

for (const change of [null, "active", "session-window", "question", "nonempty"])
  test(`read-only first-form recovery ${change || "preserves exact original ownership"}`, async () => {
    const calls = [];
    const form = {
      id: "11111111-1111-4111-8111-111111111111",
      url: "https://www.naukri.com/job-listings-fictional-123456789012",
      requisition: "123456789012",
      question: "Any training?",
      original_binding: {
        profile_binding_id: "profile",
        browser_session_id: "old",
        window_id: 7,
        tab_id: 11,
      },
    };
    if (change === "session-window") form.original_binding.window_id = 8;
    let result;
    const api = {
      storage: {
        local: {
          get: async (k) => ({
            [k]: {
              id: "profile",
              secret: "never-expose",
              connected: true,
              windowId: 7,
            },
          }),
        },
        session: {
          get: async (k) => ({
            [k]: k === "applicationBrowserSessionV1" ? "new" : {},
          }),
          set: async (v) => {
            result = v;
          },
        },
      },
      tabs: {
        get: async () => ({
          id: 11,
          active: change === "active",
          url: form.url,
          windowId: 7,
        }),
      },
      scripting: {
        executeScript: async (args) => {
          calls.push(args);
          return [
            {
              result:
                calls.length === 1
                  ? {
                      kind: "questionnaire",
                      question:
                        change === "question"
                          ? "Different question"
                          : form.question,
                      answer_kind: "text",
                      options: [],
                      document_id: "new-document",
                      step_sha256: "a".repeat(64),
                    }
                  : change !== "nonempty",
            },
          ];
        },
      },
    };
    if (change) {
      await assert.rejects(() => inspectUnansweredRetainedForm(form, api));
      assert.equal(result, undefined);
    } else {
      const proof = await inspectUnansweredRetainedForm(form, api);
      assert.equal(proof.binding.browser_session_id, "new");
      assert.equal(proof.binding.tab_id, 11);
      assert.equal(proof.empty_first_question, true);
      assert.equal(JSON.stringify(result).includes("never-expose"), false);
      assert.equal(
        calls.every((x) => x.world === "ISOLATED" && x.target.tabId === 11),
        true,
      );
    }
  });
