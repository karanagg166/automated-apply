import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import {
  continueRetainedQuestionnaire,
  inspectUnansweredRetainedForm,
  configureRetainedHeartbeat,
} from "../naukri-retained.js";

function fixture(change = {}) {
  const calls = [];
  let creations = 0;
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
      creations++;
      this.send = send;
    }
    async ownerUsingNaukri() {
      return !!change.ownerActive;
    }
    async tick() {
      calls.push("tick");
      if (change.error) throw Error("fictional_failure");
      const result = await this.send(api, "poll_naukri_work", binding);
      if (change.follow && result.work)
        await this.send(api, change.follow, {
          ...binding,
          work_id: result.work.id,
        });
      if (change.wait) await change.wait;
    }
  }
  const send = async (client, command, args) => {
    calls.push({ command, args });
    return command === "poll_naukri_work"
      ? { work: change.polled || null }
      : change.follow
        ? { work: change.followWork || change.polled }
        : {};
  };
  return {
    calls,
    run: () =>
      continueRetainedQuestionnaire(
        api,
        send,
        Queue,
        change.identity,
        change.discovery,
      ),
    creations: () => creations,
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

for (const change of [
  null,
  "selected",
  "apply-document",
  "user-message",
  "disabled",
  "extra-message",
])
  test(`unparsed radio recovery ${change || "proves the original untouched isolated document"}`, async () => {
    const url = "https://www.naukri.com/job-listings-fictional-123456789012";
    const dom = new JSDOM(
      '<div class="chatbot_DrawerContentWrapper"><div class="chatbot_MessageContainer"><div class="botItem"><div class="botMsg">Hello fictional candidate</div></div><div class="botItem"><div class="botMsg">Are you willing to attend in-person interview?</div></div><div class="singleselect-radiobutton"><input type="radio" class="ssrc__radio" id="Yes" value="Yes" name="radio-button" data-val="pb" data-index="0"><label class="ssrc__label" for="Yes">Yes</label><input type="radio" class="ssrc__radio" id="No" value="No" name="radio-button" data-val="pb" data-index="1"><label class="ssrc__label" for="No">No</label></div></div></div>',
      { url, runScripts: "outside-only" },
    );
    const w = dom.window;
    Object.defineProperty(w, "crypto", { value: webcrypto });
    Object.defineProperty(w.document, "visibilityState", { value: "hidden" });
    Object.defineProperty(w.document.body, "innerText", {
      get() {
        return this.textContent;
      },
    });
    w.Element.prototype.getClientRects = function () {
      return [1];
    };
    w.__automatedApplyNaukriExecutionV1 = {
      documentId: change === "apply-document" ? "different" : "original-apply",
      used: true,
      adopted: false,
    };
    if (change === "selected") w.document.querySelector("input").checked = true;
    if (change === "disabled")
      w.document.querySelector("input").disabled = true;
    if (change === "user-message") {
      const e = w.document.createElement("div");
      e.className = "userMsg";
      e.textContent = "previous answer";
      w.document.body.firstElementChild.append(e);
    }
    if (change === "extra-message") {
      const e = w.document.createElement("div");
      e.className = "botItem";
      e.innerHTML = '<div class="botMsg">Another question?</div>';
      w.document.querySelector(".chatbot_MessageContainer").append(e);
    }
    let saved;
    const api = {
      storage: {
        local: {
          get: async (k) => ({
            [k]: {
              id: "profile",
              secret: "private-secret",
              connected: true,
              windowId: 7,
            },
          }),
        },
        session: {
          get: async (k) => ({
            [k]: k === "applicationBrowserSessionV1" ? "same" : {},
          }),
          set: async (value) => {
            saved = value;
          },
        },
      },
      tabs: { get: async () => ({ active: false, windowId: 7, url }) },
      scripting: {
        executeScript: async (args) => [
          {
            result: JSON.parse(
              JSON.stringify(
                await w.eval(
                  `(${args.func.toString()})(...${JSON.stringify(args.args || [])})`,
                ),
              ),
            ),
          },
        ],
      },
    };
    const envelope = {
      id: "11111111-1111-4111-8111-111111111111",
      requisition: "123456789012",
      url,
      question: "Are you willing to attend in-person interview?",
      original_binding: {
        profile_binding_id: "profile",
        window_id: 7,
        tab_id: 11,
      },
      apply_document_id: "original-apply",
    };
    try {
      if (change) {
        await assert.rejects(() =>
          inspectUnansweredRetainedForm(envelope, api),
        );
        assert.equal(saved, undefined);
      } else {
        const proof = await inspectUnansweredRetainedForm(envelope, api);
        assert.equal(proof.empty_first_question, true);
        assert.equal(proof.apply_document_id, "original-apply");
        assert.equal(proof.control_kind, "naukri_single_select_radio");
        assert.equal(proof.questionnaire.answer_kind, "choice");
        assert.deepEqual(proof.questionnaire.options, ["Yes", "No"]);
        assert.equal(JSON.stringify(proof).includes("private-secret"), false);
        assert.ok(saved);
      }
      assert.equal(
        w.document.querySelectorAll("input:checked").length,
        change === "selected" ? 1 : 0,
      );
    } finally {
      w.close();
    }
  });

for (const change of [
  null,
  "active",
  "adopted",
  "session",
  "window",
  "url",
  "missing",
])
  test(`exclusive retained heartbeat ${change || "preserves and restores the existing alarm"}`, async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const calls = [];
    const form = {
      form_pending: true,
      ownerAdopted: change === "adopted",
      ownedTabId: 11,
      url: "https://www.naukri.com/job-listings-fictional-123456789012",
      binding: {
        profile_binding_id: "profile",
        browser_session_id: change === "session" ? "different" : "session",
        window_id: 7,
      },
    };
    const api = {
      storage: {
        local: {
          get: async (k) => ({
            [k]: {
              connected: true,
              id: "profile",
              secret: "private",
              windowId: 7,
            },
          }),
        },
        session: {
          get: async (k) => ({
            [k]:
              k === "applicationBrowserSessionV1"
                ? "session"
                : change === "missing"
                  ? {}
                  : { [id]: form },
          }),
        },
      },
      tabs: {
        get: async () => ({
          active: change === "active",
          windowId: change === "window" ? 8 : 7,
          url: change === "url" ? "https://example.org/" : form.url,
        }),
      },
      alarms: {
        get: async () => ({ periodInMinutes: 0.75 }),
        clear: async (name) => calls.push(["clear", name]),
        create: async (name, value) => calls.push(["create", name, value]),
      },
    };
    try {
      if (change) {
        await assert.rejects(() => configureRetainedHeartbeat(api, id));
        assert.deepEqual(calls, []);
      } else {
        assert.deepEqual(await configureRetainedHeartbeat(api, id), {
          held: true,
        });
        assert.equal(calls.length, 1);
        await configureRetainedHeartbeat(api, id);
        assert.equal(calls.length, 2);
        assert.deepEqual(await configureRetainedHeartbeat(api), {
          held: false,
        });
        assert.deepEqual(calls.at(-1), [
          "create",
          "connected-chrome-heartbeat",
          { periodInMinutes: 0.75 },
        ]);
        await configureRetainedHeartbeat(api);
        assert.equal(calls.length, 3);
      }
    } finally {
      await configureRetainedHeartbeat(api);
    }
  });

test("repeated retained ticks reuse one queue and its adoption listeners", async () => {
  const f = fixture();
  await f.run();
  await f.run();
  assert.equal(f.creations(), 1);
  assert.equal(f.calls.filter((v) => v === "tick").length, 2);
});
for (const operation of ["inspect_job", "search_jobs"])
  test(`optional discovery permits only leased ${operation} reads alongside the original form`, async () => {
    const f = fixture({
      discovery: true,
      polled: { id: "other", operation, binding: { tab_id: 8 } },
      follow: "admit_naukri_work",
    });
    await f.run();
    assert.ok(f.calls.some((c) => c.command === "admit_naukri_work"));
    assert.equal(
      f.calls.filter((c) => c.command === "abandon_naukri_work").length,
      0,
    );
  });
for (const operation of [
  "apply",
  "answer_questionnaire",
  "sync_profile",
  "inspect_profile",
])
  test(`discovery continuation never permits foreign ${operation}`, async () => {
    const f = fixture({
      discovery: true,
      polled: { id: "other", operation, binding: { tab_id: 8 } },
      follow: "admit_naukri_work",
    });
    await f.run();
    assert.equal(
      f.calls.filter((c) => c.command === "admit_naukri_work").length,
      0,
    );
    assert.equal(
      f.calls.filter((c) => c.command === "abandon_naukri_work").length,
      1,
    );
  });
test("a read lease cannot transition to foreign execution before browser work", async () => {
  const f = fixture({
    discovery: true,
    polled: { id: "other", operation: "inspect_job", binding: { tab_id: 8 } },
    follow: "admit_naukri_work",
    followWork: { id: "other", operation: "apply", execution: {} },
  });
  await assert.rejects(f.run, /retained_read_scope_changed/);
});
test("a read-shaped foreign execution descriptor is refused before admission", async () => {
  const f = fixture({
    discovery: true,
    polled: {
      id: "other",
      operation: "inspect_job",
      binding: { tab_id: 8 },
      execution: {},
    },
    follow: "admit_naukri_work",
  });
  await f.run();
  assert.equal(
    f.calls.filter((c) => c.command === "admit_naukri_work").length,
    0,
  );
});
