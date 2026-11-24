import test from "node:test";
import assert from "node:assert/strict";
import { NaukriQueue, sortNaukriSearchDate } from "../naukri-queue.js";

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
    ...options.work,
  };
  let nextTabId = 44;
  let readFinished = false;
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
          windowId: 10,
          url: options.ownerNaukri
            ? "https://www.naukri.com/mnjuser/profile"
            : "https://example.com/owner-work",
        },
      ],
      create: async (input) => {
        calls.push(["create", input]);
        const tab = { ...input, id: nextTabId++, status: "complete" };
        tabs.set(tab.id, tab);
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
    windows: {
      getAll: async () => [{ id: 10, focused: options.focused !== false }],
    },
    scripting: {
      executeScript: async (input) => {
        calls.push(["inspect", input]);
        if (input.func === sortNaukriSearchDate)
          return [
            {
              result: options.sortReports?.shift() ||
                options.sortReport || {
                  kind: "date_sort",
                  state: "selected",
                },
            },
          ];
        if (options.adopt) {
          activation({ tabId: 44 });
          tabs.get(44).active = true;
          await Promise.resolve();
          tabs.get(44).active = false;
        }
        return [
          {
            result: options.reports?.shift() || {
              kind: "needs_input",
              reason: "fictional_unknown_layout",
            },
          },
        ];
      },
    },
  };
  const send = async (_, name, input) => {
    calls.push([name, input]);
    if (options.respond) {
      const response = await options.respond(name, input, work);
      if (response) {
        if (response.work) work = response.work;
        return response;
      }
    }
    if (name === "poll_naukri_work")
      return {
        maintenance: options.maintenance,
        work: readFinished
          ? null
          : options.operation
            ? { ...work, operation: options.operation }
            : work,
      };
    if (options.stop && name === "admit_naukri_work")
      throw Error("queue_lease_lost");
    if (options.lostFinish && name === "finish_naukri_work")
      throw Error("backend_timeout");
    if (name === "finish_naukri_work") readFinished = true;
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
    send,
    activate: (tabId) => activation({ tabId }),
    queue: new NaukriQueue(api, send, async () => {}),
  };
}
test("a Naukri tab selected in an unfocused window does not block background work", async () => {
  const f = fixture({ ownerNaukri: true, focused: false });
  await f.queue.tick();
  assert.ok(f.calls.some(([name]) => name === "poll_naukri_work"));
  assert.equal(f.calls.find(([name]) => name === "create")[1].active, false);
});

function questionnaireFixture() {
  const binding = {
    profile_binding_id: "fixture-profile",
    browser_session_id: "fixture-session",
    window_id: 10,
    tab_id: null,
  };
  let finishes = 0;
  const options = {
    work: {
      operation: "inspect_profile",
      target_url: "https://www.naukri.com/mnjuser/profile",
      binding,
      execution: {},
    },
    reports: [
      {
        kind: "execution_observation",
        execution: { state: "PROFILE_VERIFIED" },
      },
      { kind: "execution_observation", execution: { state: "NOT_APPLIED" } },
      { kind: "job_facts", job: {} },
      { kind: "execution_observation", execution: { state: "QUESTIONNAIRE" } },
      {
        kind: "questionnaire",
        document_id: "11111111-1111-4111-8111-111111111111",
        step_sha256: "a".repeat(64),
        question: "What is your notice period?",
        answer_kind: "choice",
        options: ["Immediate"],
        max_characters: 4000,
      },
    ],
    respond: async (name, input, work) => {
      if (name !== "finish_naukri_work") return;
      finishes++;
      const operation = [
        "inspect_application",
        "apply",
        "inspect_questionnaire",
        "prepare_questionnaire",
      ][finishes - 1];
      return {
        work: {
          ...work,
          revision: work.revision + 1,
          operation,
          target_url: url,
          form_pending: finishes >= 3,
          stage: finishes >= 3 ? "QUESTIONS" : "READY_TO_APPLY",
          status: finishes >= 3 ? "queued" : "leased",
          execution: finishes < 4 ? {} : undefined,
        },
        continue: finishes < 3,
      };
    },
  };
  return fixture(options);
}
test("the original Apply tab is retained for questionnaire inspection across alarms", async () => {
  const f = questionnaireFixture();
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.equal(f.calls.filter(([name]) => name === "close").length, 0);
  assert.equal(f.session.naukriParkedQuestionnairesV1.fixture.ownedTabId, 44);
  assert.equal(f.session.naukriReadInFlightV1, undefined);
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.equal(f.calls.filter(([name]) => name === "close").length, 0);
  assert.equal(
    f.session.naukriParkedQuestionnairesV1.fixture.operation,
    "prepare_questionnaire",
  );
  const scripts = f.calls.filter(([name]) => name === "inspect");
  assert.equal(scripts.at(-1)[1].func.name, "naukriChatbot");
  assert.equal(scripts.at(-1)[1].target.tabId, 44);
});
test("owner adoption of a parked form is durable after service-worker reconstruction", async () => {
  const f = questionnaireFixture();
  await f.queue.tick();
  f.queue = new NaukriQueue(f.api, f.send, async () => {});
  f.activate(44);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(
    f.session.naukriParkedQuestionnairesV1.fixture.ownerAdopted,
    true,
  );
  const before = f.calls.filter(([name]) => name === "inspect").length;
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, before);
  assert.equal(f.calls.filter(([name]) => name === "close").length, 0);
});
test("questionnaire completion accepts only a same-document read-only Applied observation", async () => {
  const f = fixture();
  f.queue.assertInactive = async () => ({ active: false, url });
  const chatbot = {
    kind: "questionnaire_drawer_closed",
    document_id: "known-chatbot",
  };
  const work = {
    operation: "inspect_questionnaire",
    ownedTabId: 44,
    url,
    execution: { completion_document_id: chatbot.document_id },
  };
  const applied = {
    kind: "execution_observation",
    observed_url: url,
    execution: { state: "APPLIED" },
  };
  let browserDocument = "original-browser-document";
  f.api.scripting.executeScript = async (request) => {
    assert.equal(request.func.name, "executeNaukri");
    assert.deepEqual(request.target, { tabId: 44, frameIds: [0] });
    assert.equal(request.args[0].operation, "inspect_application");
    assert.equal(request.args[0].questionnaire_completion, true);
    return [{ documentId: browserDocument, result: applied }];
  };
  const inspect = () =>
    f.queue.inspectQuestionnaireCompletion(
      work,
      { window_id: 10 },
      chatbot,
      "original-browser-document",
    );
  assert.deepEqual(await inspect(), {
    ...applied,
    document_id: chatbot.document_id,
  });
  browserDocument = "another-browser-document";
  assert.equal(await inspect(), null);
  browserDocument = "original-browser-document";
  applied.execution.state = "NOT_APPLIED";
  assert.equal(await inspect(), null);
});
test("trusted maintenance opens only one own inactive setup tab and admits no job", async () => {
  const maintenance = {
    kind: "open_extension_manager",
    request_id: "11111111-1111-4111-8111-111111111111",
    expires_at: new Date(Date.now() + 60000).toISOString(),
  };
  const f = fixture({ maintenance });
  await f.queue.tick();
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.deepEqual(f.calls.find(([name]) => name === "create")[1], {
    url: "chrome://extensions/",
    active: false,
    windowId: 10,
  });
  assert.ok(
    !f.calls.some(([name]) =>
      ["bind_naukri_work", "admit_naukri_work", "inspect"].includes(name),
    ),
  );
});

function profileSetupRequest() {
  return {
    kind: "open_naukri_profile_setup",
    request_id: "11111111-1111-4111-8111-111111111111",
    expires_at: new Date(Date.now() + 60000).toISOString(),
    url: "https://example.com/untrusted-override",
  };
}

test("profile setup opens only the fixed inactive profile URL, acknowledges ownership and does no DOM work", async () => {
  const maintenance = profileSetupRequest();
  const f = fixture({ maintenance });
  await f.queue.tick();
  await f.queue.tick();
  maintenance.request_id = "22222222-2222-4222-8222-222222222222";
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.deepEqual(f.calls.find(([name]) => name === "create")[1], {
    url: "https://www.naukri.com/mnjuser/profile",
    active: false,
    windowId: 10,
  });
  const acknowledgements = f.calls.filter(
    ([name, input]) => name === "poll_naukri_work" && input.tab_id === 44,
  );
  assert.equal(acknowledgements.length, 3);
  assert.equal(acknowledgements.at(-1)[1].work_id, maintenance.request_id);
  assert.ok(
    !f.calls.some(([name]) =>
      [
        "navigate",
        "close",
        "inspect",
        "bind_naukri_work",
        "admit_naukri_work",
      ].includes(name),
    ),
  );
});

test("a lost profile setup creation response is not replayed across alarms or worker reconstruction", async () => {
  const f = fixture({ maintenance: profileSetupRequest() });
  const create = f.api.tabs.create;
  f.api.tabs.create = async (input) => {
    await create(input);
    throw Error("fictional_lost_create");
  };
  await f.queue.tick();
  f.queue = new NaukriQueue(f.api, f.send, async () => {});
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.equal(f.session.naukriProfileSetupTabV1.status, "creating");
  assert.ok(
    !f.calls.some(
      ([name, input]) => name === "poll_naukri_work" && input.tab_id,
    ),
  );
});

test("only the profile setup ACK is retried after its response is lost", async () => {
  let acks = 0;
  const f = fixture({
    maintenance: profileSetupRequest(),
    respond: async (name, input) => {
      if (name === "poll_naukri_work" && input.tab_id && ++acks === 1)
        throw Error("backend_timeout");
    },
  });
  await f.queue.tick();
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
  assert.equal(acks, 2);
  assert.equal(f.session.naukriProfileSetupTabV1.status, "opened");
});

test("adopted setup ownership survives reconstruction and the owner tab is never reused or changed", async () => {
  const maintenance = profileSetupRequest();
  const f = fixture({ maintenance });
  await f.queue.tick();
  f.tabs.get(44).active = true;
  f.activate(44);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(f.session.naukriProfileSetupTabV1.ownerAdopted, true);
  f.tabs.get(44).active = false;
  maintenance.request_id = "22222222-2222-4222-8222-222222222222";
  f.queue = new NaukriQueue(f.api, f.send, async () => {});
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "create").length, 2);
  assert.ok(f.tabs.has(44));
  assert.ok(
    !f.calls.some(([name]) => ["navigate", "close", "inspect"].includes(name)),
  );
});

for (const invalid of ["expired", "unknown_kind"]) {
  test(`invalid profile setup intent ${invalid} creates no tab or ACK`, async () => {
    const maintenance = profileSetupRequest();
    if (invalid === "expired")
      maintenance.expires_at = new Date(Date.now() - 1).toISOString();
    else maintenance.kind = "arbitrary_url";
    const f = fixture({ maintenance });
    await f.queue.tick();
    assert.ok(!f.calls.some(([name]) => name === "create"));
    assert.ok(
      !f.calls.some(
        ([name, input]) => name === "poll_naukri_work" && input.tab_id,
      ),
    );
  });
}

test("search observes candidates only after Date sorting succeeds", async () => {
  const f = fixture({
    operation: "search_jobs",
    work: {
      operation: "search_jobs",
      url: "https://www.naukri.com/backend-developer-jobs",
    },
    reports: [{ kind: "source_candidates", candidates: [url] }],
  });
  await f.queue.tick();
  const inspections = f.calls
    .filter(([name]) => name === "inspect")
    .map(([, input]) => input);
  assert.equal(inspections[0].func, sortNaukriSearchDate);
  assert.equal(inspections.length, 2);
  assert.equal(
    f.calls.find(([name]) => name === "finish_naukri_work")[1].work_report.kind,
    "source_candidates",
  );
});
test("a confirmed keyword relevance search proceeds through the same observation and finish", async () => {
  const search = "https://www.naukri.com/backend-developer-fresher-jobs";
  const f = fixture({
    work: { operation: "search_jobs", url: search },
    sortReport: { kind: "search_ready", state: "keyword_relevance" },
    reports: [{ kind: "source_candidates", candidates: [url] }],
  });
  await f.queue.tick();
  assert.equal(f.calls.find(([name]) => name === "inspect")[1].args[0], search);
  assert.deepEqual(
    f.calls.find(([name]) => name === "finish_naukri_work")[1].work_report
      .candidates,
    [url],
  );
});

test("unknown keyword search order yields without observing or admitting candidates", async () => {
  const f = fixture({
    work: {
      operation: "search_jobs",
      url: "https://www.naukri.com/backend-developer-fresher-jobs",
    },
    sortReport: {
      kind: "needs_input",
      reason: "search_keyword_order_unrecognized",
    },
  });
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, 1);
  assert.equal(
    f.calls.some(([name]) => name === "finish_naukri_work"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "search_keyword_order_unrecognized",
  );
});

test("unconfirmed search sorting reports failure without observing or admitting candidates", async () => {
  const f = fixture({
    operation: "search_jobs",
    work: {
      operation: "search_jobs",
      url: "https://www.naukri.com/backend-developer-jobs",
    },
    sortReport: {
      kind: "needs_input",
      reason: "search_date_sort_not_confirmed",
    },
  });
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, 1);
  assert.equal(
    f.calls.some(([name]) => name === "finish_naukri_work"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "search_date_sort_not_confirmed",
  );
});

test("search carries synchronous sort progress between worker-scheduled steps", async () => {
  const search = "https://www.naukri.com/backend-developer-jobs";
  const state = { expectedUrl: search, document: 123, opened: true };
  const f = fixture({
    work: { operation: "search_jobs", url: search },
    sortReports: [
      { kind: "date_sort_pending", state },
      { kind: "date_sort", state: "selected" },
    ],
    reports: [{ kind: "source_candidates", candidates: [url] }],
  });
  await f.queue.tick();
  const sortCalls = f.calls.filter(
    ([name, input]) =>
      name === "inspect" && input.func === sortNaukriSearchDate,
  );
  assert.equal(sortCalls.length, 2);
  assert.deepEqual(sortCalls[0][1].args, [search, null]);
  assert.deepEqual(sortCalls[1][1].args, [search, state]);
  assert.ok(f.calls.some(([name]) => name === "finish_naukri_work"));
});

test("unsettled sort stops at forty worker steps without admitting candidates", async () => {
  const search = "https://www.naukri.com/backend-developer-jobs";
  const f = fixture({
    work: { operation: "search_jobs", url: search },
    sortReport: {
      kind: "date_sort_pending",
      state: { expectedUrl: search, document: 123, opened: true },
    },
  });
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, 40);
  assert.equal(
    f.calls.some(([name]) => name === "finish_naukri_work"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "search_date_sort_not_confirmed",
  );
});

test("a stalled renderer sort call is bounded by the worker clock", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const f = fixture({
    work: {
      operation: "search_jobs",
      url: "https://www.naukri.com/backend-developer-jobs",
    },
  });
  f.api.scripting.executeScript = async (input) => {
    f.calls.push(["inspect", input]);
    return new Promise(() => {});
  };
  const run = f.queue.tick();
  for (let i = 0; i < 100 && !f.calls.some(([name]) => name === "inspect"); i++)
    await Promise.resolve();
  assert.ok(f.calls.some(([name]) => name === "inspect"));
  t.mock.timers.tick(10000);
  await run;
  assert.equal(
    f.calls.some(([name]) => name === "finish_naukri_work"),
    false,
  );
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "search_date_sort_not_confirmed",
  );
});

for (const operation of ["inspect_profile", "inspect_profile_sync"]) {
  test(`${operation} Download uses one owned-tab capture and isolated account recheck`, async () => {
    const report = {
      kind: "execution_observation",
      execution: {
        state:
          operation === "inspect_profile"
            ? "PROFILE_VERIFIED"
            : "PROFILE_OBSERVED",
        resume_sha256: "a".repeat(64),
        resume_bytes: 42,
      },
    };
    const f = fixture({
      operation,
      work: {
        operation,
        target_url: "https://www.naukri.com/mnjuser/profile",
        execution: { expected_resume_sha256: "a".repeat(64) },
      },
      reports: [
        {
          kind: "needs_input",
          reason: "profile_resume_download_capture_required",
        },
        { kind: "provider_pdf_digest", sha256: "a".repeat(64), byte_count: 42 },
        report,
      ],
    });
    await f.queue.tick();
    const injections = f.calls
      .filter(([name]) => name === "inspect")
      .map(([, input]) => input);
    assert.deepEqual(
      injections.map((x) => x.world),
      ["ISOLATED", "MAIN", "ISOLATED"],
    );
    assert.ok(injections.every((x) => x.target.tabId === 44));
    assert.deepEqual(injections[1].args, [
      { target_url: "https://www.naukri.com/mnjuser/profile" },
    ]);
    assert.equal(
      injections[2].args[0].execution.provider_pdf_observation.kind,
      "provider_pdf_digest",
    );
    assert.deepEqual(
      f.calls.find(([name]) => name === "finish_naukri_work")[1].work_report,
      report,
    );
  });
}

test("unsupported Download capture waits without false profile verification", async () => {
  const f = fixture({
    operation: "inspect_profile",
    work: {
      operation: "inspect_profile",
      target_url: "https://www.naukri.com/mnjuser/profile",
      execution: {},
    },
    reports: [
      {
        kind: "needs_input",
        reason: "profile_resume_download_capture_required",
      },
      {
        kind: "needs_input",
        reason: "profile_resume_download_pdf_not_observed",
      },
    ],
  });
  await f.queue.tick();
  assert.ok(!f.calls.some(([name]) => name === "finish_naukri_work"));
  assert.equal(
    f.calls.find(([name]) => name === "abandon_naukri_work")[1].work_report
      .reason,
    "profile_resume_download_pdf_not_observed",
  );
});

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
for (const [outcome, expectedClose] of [
  ["confirmed", true],
  ["lost", false],
  ["denied", false],
  ["malformed", false],
  ["other work", false],
  ["other tab", false],
  ["other session", false],
  ["owner adopted", false],
  ["existing parked form", false],
]) {
  test(`cached Apply restart with ${outcome} release preserves tab ownership`, async () => {
    const pending = {
      id: "fixture",
      revision: 4,
      lease_token: "fixture-token",
      status: "leased",
      operation: "apply",
      url,
      binding: {
        tab_id: 55,
        window_id: 10,
        profile_binding_id: "fixture-profile",
        browser_session_id: "fixture-session",
      },
      ownedTabId: 55,
      ownerAdopted: outcome === "owner adopted",
    };
    const original = { ...pending, ownerAdopted: true, form_pending: true };
    const f = fixture({
      session: {
        naukriReadInFlightV1: pending,
        ...(outcome === "existing parked form"
          ? { naukriParkedQuestionnairesV1: { fixture: original } }
          : {}),
      },
      respond: async (name) => {
        assert.equal(name, "abandon_naukri_work");
        if (["lost", "existing parked form"].includes(outcome))
          throw Error("backend_timeout");
        if (outcome === "denied") throw Error("queue_lease_lost");
        return {
          unadmitted_apply_released: outcome === "malformed" ? "true" : true,
          continue: false,
          submitted: false,
          work: {
            ...pending,
            id: outcome === "other work" ? "different" : pending.id,
            revision: pending.revision + 1,
            binding: {
              ...pending.binding,
              tab_id: outcome === "other tab" ? 56 : 55,
              browser_session_id:
                outcome === "other session"
                  ? "different-session"
                  : pending.binding.browser_session_id,
            },
            status: "waiting",
            stage: "BLOCKED_PLATFORM",
            form_pending: false,
            lease_token: null,
            lease_until: null,
          },
        };
      },
    });
    f.tabs.set(55, { id: 55, url, active: false, windowId: 10 });
    await f.queue.tick();
    const calls = f.calls.map(([name]) => name);
    assert.deepEqual(
      calls,
      expectedClose
        ? ["abandon_naukri_work", "close"]
        : ["abandon_naukri_work"],
    );
    assert.equal(f.tabs.has(55), !expectedClose);
    assert.equal(f.session.naukriReadInFlightV1, undefined);
    const parked = f.session.naukriParkedQuestionnairesV1?.fixture;
    if (
      [
        "lost",
        "denied",
        "malformed",
        "other work",
        "other tab",
        "other session",
      ].includes(outcome)
    )
      assert.equal(parked.ownedTabId, 55);
    else if (outcome === "existing parked form")
      assert.deepEqual(parked, original);
    else assert.equal(parked, undefined);
  });
}

for (const lostAck of [false, true]) {
  test(`Apply failure after a read preserves the tab when abandon is ${lostAck ? "unconfirmed" : "confirmed"}`, async () => {
    const f = fixture({
      work: {
        operation: "inspect_application",
        target_url: url,
        execution: {},
        binding: {
          tab_id: null,
          window_id: 10,
          profile_binding_id: "fixture-profile",
          browser_session_id: "fixture-session",
        },
      },
      reports: [
        { kind: "execution_observation", execution: { state: "NOT_APPLIED" } },
        { kind: "job_facts" },
      ],
      respond: async (name, _, work) => {
        if (name === "finish_naukri_work")
          return {
            continue: true,
            work: { ...work, operation: "apply", status: "leased" },
          };
        if (name === "admit_naukri_work" && work.operation === "apply")
          throw Error("prepared_application_required");
        if (name === "abandon_naukri_work") {
          if (lostAck) throw Error("backend_timeout");
          return {
            unadmitted_apply_released: true,
            continue: false,
            submitted: false,
            work: {
              ...work,
              revision: work.revision + 1,
              status: "waiting",
              stage: "BLOCKED_PLATFORM",
              form_pending: false,
              lease_token: null,
              lease_until: null,
            },
          };
        }
      },
    });
    await f.queue.tick();
    assert.equal(f.calls.filter(([name]) => name === "inspect").length, 2);
    assert.deepEqual(
      f.calls.filter(([name]) => name === "close"),
      lostAck ? [] : [["close", 44]],
    );
    assert.equal(
      f.session.naukriParkedQuestionnairesV1?.fixture.ownedTabId,
      lostAck ? 44 : undefined,
    );
    assert.equal(f.session.naukriReadInFlightV1, undefined);
  });
}

test("concurrent alarms share one consumer run", async () => {
  const f = fixture();
  await Promise.all([f.queue.tick(), f.queue.tick()]);
  assert.equal(
    f.calls.filter(([name]) => name === "poll_naukri_work").length,
    1,
  );
  assert.equal(f.calls.filter(([name]) => name === "create").length, 1);
});

test("delayed read-only hydration is bounded and returns the first complete facts", async () => {
  const f = fixture({
    reports: [
      { kind: "needs_input", reason: "job_header_unrecognized" },
      { kind: "needs_input", reason: "job_required_facts_unrecognized" },
      { kind: "job_facts", job: { evidence_sha256: "fictional" } },
    ],
  });
  await f.queue.tick();
  assert.equal(f.calls.filter(([name]) => name === "inspect").length, 3);
  assert.equal(
    f.calls.find(([name]) => name === "finish_naukri_work")[1].work_report.kind,
    "job_facts",
  );
  assert.equal(
    f.calls.filter(([name]) => name === "admit_naukri_work").length,
    1,
  );
});
test("hydration retries are bounded and never retry a provider challenge", async () => {
  const pending = fixture({
    reports: Array.from({ length: 12 }, () => ({
      kind: "needs_input",
      reason: "job_header_unrecognized",
    })),
  });
  await pending.queue.tick();
  assert.equal(pending.calls.filter(([name]) => name === "inspect").length, 9);
  const challenge = fixture({
    reports: [
      { kind: "needs_input", reason: "provider_challenge_requires_owner" },
    ],
  });
  await challenge.queue.tick();
  assert.equal(
    challenge.calls.filter(([name]) => name === "inspect").length,
    1,
  );
});

for (const fault of [null, "lost_preparation", "stop_before_save"]) {
  test(`skills preparation, Save and independent reload remain separate ${fault || "success"}`, async () => {
    const profile = "https://www.naukri.com/mnjuser/profile";
    let finishes = 0,
      admissions = 0;
    const options = {
      work: {
        operation: "inspect_profile_sync",
        url: profile,
        target_url: profile,
        execution: {},
      },
      reports: [
        {
          kind: "execution_observation",
          execution: { state: "PROFILE_OBSERVED" },
        },
        { kind: "profile_skills_prepare_pending" },
        {
          kind: "execution_observation",
          execution: {
            state: "PROFILE_SKILLS_PREPARED",
            profile_fields: { skills: ["Python", "FastAPI"] },
          },
        },
        {
          kind: "execution_observation",
          execution: { state: "PROFILE_SAVE_ATTEMPTED" },
        },
        {
          kind: "execution_observation",
          execution: { state: "PROFILE_OBSERVED" },
        },
      ],
      respond: async (name, input, work) => {
        if (name === "admit_naukri_work") {
          admissions++;
          if (fault === "stop_before_save" && admissions === 3)
            throw Error("queue_lease_lost");
        }
        if (name !== "finish_naukri_work") return;
        finishes++;
        if (fault === "lost_preparation" && finishes === 2)
          throw Error("backend_timeout");
        const operation =
          finishes < 3 ? "sync_profile" : "inspect_profile_sync";
        const execution =
          finishes < 3
            ? {
                sync_field: "skills",
                sync_phase: finishes === 1 ? "prepare" : "save",
              }
            : {};
        return {
          work: { ...work, revision: work.revision + 1, operation, execution },
          continue: finishes < 4,
        };
      },
    };
    const f = fixture(options);
    const original = f.api.scripting.executeScript;
    f.api.scripting.executeScript = async (input) => {
      if (
        input.func.name === "executeNaukriSkills" &&
        input.args[0].execution.sync_phase === "prepare"
      )
        f.tabs.get(44).url = profile + "?action=modalOpen";
      return original(input);
    };
    await f.queue.tick();
    const injected = f.calls
      .filter(([name]) => name === "inspect")
      .map(([, input]) => input);
    assert.equal(
      injected.filter(
        (x) =>
          x.func.name === "executeNaukriSkills" &&
          x.args[0].execution.sync_phase === "save",
      ).length,
      fault ? 0 : 1,
    );
    assert.equal(
      admissions,
      fault === "lost_preparation" ? 2 : fault === "stop_before_save" ? 3 : 4,
    );
    assert.equal(
      f.calls.filter(([name]) => name === "abandon_naukri_work").length,
      fault ? 1 : 0,
    );
    assert.equal(
      f.calls.filter(([name]) => name === "navigate").length,
      fault ? 1 : 2,
    );
    assert.equal(
      f.calls
        .filter(([name]) => name === "navigate")
        .every(([, v]) => v.url === profile && v.active === false),
      true,
    );
    assert.equal(f.calls.filter(([name]) => name === "close").length, 1);
  });
}

function drainFixture({
  beforePoll,
  afterFinish,
  lostFinish = false,
  reportKind = "job_facts",
} = {}) {
  let polls = 0,
    completed = 0;
  const f = fixture({
    reports: Array.from({ length: 9 }, () => ({
      kind: reportKind,
      reason:
        reportKind === "needs_input"
          ? "provider_challenge_requires_owner"
          : undefined,
    })),
    respond: async (name, input, current) => {
      if (name === "poll_naukri_work") {
        polls++;
        beforePoll?.(polls);
        return {
          work: {
            id: `read-${completed}`,
            revision: 1,
            lease_token: `lease-${completed}`,
            operation: "inspect_job",
            url,
            binding: { tab_id: null, window_id: 10 },
          },
        };
      }
      if (name === "finish_naukri_work") {
        if (lostFinish) throw Error("backend_timeout");
        completed++;
        afterFinish?.(completed, f);
        return { work: current };
      }
    },
  });
  return { ...f, completed: () => completed, polls: () => polls };
}

test("one wake drains at most three completed reads, releasing each owned tab before the next lease", async () => {
  const f = drainFixture();
  await f.queue.tick();
  assert.equal(f.completed(), 3);
  assert.equal(f.polls(), 3);
  assert.equal(f.calls.filter(([n]) => n === "create").length, 3);
  assert.equal(f.calls.filter(([n]) => n === "close").length, 3);
  const names = f.calls.map(([n]) => n);
  assert.ok(
    names.indexOf("close") <
      names.indexOf("poll_naukri_work", names.indexOf("poll_naukri_work") + 1),
  );
  assert.equal(f.tabs.size, 0);
  await f.queue.tick();
  assert.equal(f.completed(), 6);
});

test("the drain starts no additional read after its bounded scheduling window", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"] });
  const f = drainFixture({ afterFinish: () => t.mock.timers.tick(30001) });
  await f.queue.tick();
  assert.equal(f.completed(), 1);
  assert.equal(f.polls(), 1);
});

for (const failure of ["lost_finish", "challenge", "stop_before_next_poll"]) {
  test(`the drain yields after ${failure} without another observation or action`, async () => {
    const f = drainFixture({
      lostFinish: failure === "lost_finish",
      reportKind: failure === "challenge" ? "needs_input" : "job_facts",
      beforePoll: (count) => {
        if (failure === "stop_before_next_poll" && count === 2)
          throw Error("queue_lease_lost");
      },
    });
    await f.queue.tick();
    assert.equal(f.calls.filter(([n]) => n === "create").length, 1);
    assert.equal(f.calls.filter(([n]) => n === "inspect").length, 1);
    assert.equal(f.polls(), failure === "stop_before_next_poll" ? 2 : 1);
    assert.equal(f.calls.filter(([n]) => n === "close").length, 1);
  });
}

test("owner activity is checked again before a drain can poll for another read", async () => {
  const f = drainFixture({
    afterFinish: (_, f) => {
      f.api.tabs.query = async () => [
        {
          id: 7,
          active: true,
          windowId: 10,
          url: "https://www.naukri.com/mnjuser/profile",
        },
      ];
    },
  });
  await f.queue.tick();
  assert.equal(f.completed(), 1);
  assert.equal(f.polls(), 1);
});

for (const [name, reports, expected, attempts] of [
  [
    "hydrating then observed",
    [
      { kind: "needs_input", reason: "profile_identity_hydrating" },
      { kind: "needs_input", reason: "profile_identity_hydrating" },
      {
        kind: "execution_observation",
        execution: { state: "PROFILE_OBSERVED" },
      },
    ],
    "PROFILE_OBSERVED",
    3,
  ],
  [
    "mismatched account",
    [
      { kind: "needs_input", reason: "provider_account_identity_unverified" },
      {
        kind: "execution_observation",
        execution: { state: "PROFILE_OBSERVED" },
      },
    ],
    "provider_account_identity_unverified",
    1,
  ],
  [
    "challenge",
    [{ kind: "needs_input", reason: "provider_challenge_requires_owner" }],
    "provider_challenge_requires_owner",
    1,
  ],
  [
    "absent account",
    Array.from({ length: 40 }, () => ({
      kind: "needs_input",
      reason: "profile_identity_hydrating",
    })),
    "profile_identity_hydrating",
    40,
  ],
])
  test(`profile readiness ${name} remains a bounded read with no repeated admission`, async () => {
    const f = fixture({ reports });
    const tab = await f.api.tabs.create({
      url: "https://www.naukri.com/mnjuser/profile",
      active: false,
      windowId: 10,
    });
    const result = await f.queue.observeProfileReady(
      {
        id: "fixture",
        operation: "inspect_profile",
        ownedTabId: tab.id,
        target_url: tab.url,
        execution: {},
      },
      { window_id: 10 },
    );
    assert.equal(result.reason || result.execution.state, expected);
    assert.equal(f.calls.filter(([n]) => n === "inspect").length, attempts);
    assert.equal(f.calls.filter(([n]) => n === "admit_naukri_work").length, 0);
  });

test("profile hydration helper cannot retry an Apply or other write", async () => {
  const f = fixture();
  await assert.rejects(
    () => f.queue.observeProfileReady({ operation: "apply" }, {}),
    /profile_read_operation_required/,
  );
  assert.equal(f.calls.length, 0);
});

for (const operation of [
  "inspect_job",
  "reconcile_application",
  "prepare_questionnaire",
]) {
  test(`generic ${operation} cleanup cannot close a retained application tab`, async () => {
    const original = {
      id: "original",
      ownedTabId: 44,
      form_pending: true,
      binding: { window_id: 10 },
    };
    const f = fixture({
      session: { naukriParkedQuestionnairesV1: { original } },
    });
    f.tabs.set(44, { id: 44, active: false, windowId: 10, url });
    await f.queue.closeOwned({
      ...original,
      id: operation === "inspect_job" ? "different-read" : "original",
      operation,
    });
    assert.ok(f.tabs.has(44));
    assert.ok(!f.calls.some(([name]) => name === "close"));
  });
}
test("only the matching server-confirmed result permits retained form cleanup", async () => {
  const original = {
    id: "original",
    ownedTabId: 44,
    form_pending: true,
    binding: { window_id: 10 },
  };
  const f = fixture({
    session: { naukriParkedQuestionnairesV1: { original } },
  });
  f.tabs.set(44, { id: 44, active: false, windowId: 10, url });
  await f.queue.closeOwned(original, {
    id: "different",
    stage: "SUBMITTED_CONFIRMED",
  });
  await f.queue.closeOwned(original, {
    id: "original",
    stage: "SUBMISSION_UNKNOWN",
  });
  assert.ok(f.tabs.has(44));
  await f.queue.closeOwned(original, {
    id: "original",
    stage: "SUBMITTED_CONFIRMED",
  });
  assert.ok(!f.tabs.has(44));
});
test("even a confirmed result cannot close an owner-adopted retained form", async () => {
  const original = {
    id: "original",
    ownedTabId: 44,
    form_pending: true,
    ownerAdopted: true,
    binding: { window_id: 10 },
  };
  const f = fixture({
    session: { naukriParkedQuestionnairesV1: { original } },
  });
  f.tabs.set(44, { id: 44, active: false, windowId: 10, url });
  await f.queue.closeOwned(original, {
    id: "original",
    stage: "SUBMITTED_CONFIRMED",
  });
  assert.ok(f.tabs.has(44));
});

function lostFormFixture(options = {}) {
  const original = {
    id: "original",
    ownedTabId: 44,
    form_pending: true,
    binding: {
      profile_binding_id: "fixture-profile",
      browser_session_id: "fixture-session",
      window_id: 10,
    },
  };
  const f = fixture({
    session: { naukriParkedQuestionnairesV1: { original } },
    respond: (name, input) =>
      input.work_report?.reason === "original_questionnaire_tab_unavailable"
        ? { form_loss_recorded: true }
        : null,
    ...options,
  });
  return { ...f, original };
}
test("missing original form is reported once with no provider or tab action", async () => {
  const f = lostFormFixture();
  await f.queue.reportLostForms();
  await f.queue.reportLostForms();
  assert.equal(f.calls.length, 1);
  const [name, input] = f.calls[0];
  assert.equal(name, "poll_naukri_work");
  assert.equal(input.work_id, "original");
  assert.equal(input.tab_id, 44);
  assert.deepEqual(input.work_report, {
    kind: "needs_input",
    reason: "original_questionnaire_tab_unavailable",
  });
  assert.equal(
    f.session.naukriParkedQuestionnairesV1.original.loss_reported,
    true,
  );
});
test("an existing original document and unrelated removal are not reported as lost", async () => {
  const f = lostFormFixture();
  f.tabs.set(44, { id: 44, active: false, windowId: 10, url });
  await f.queue.reportLostForms();
  await f.queue.reportLostForms(99);
  assert.equal(f.calls.length, 0);
});
for (const field of ["profile_binding_id", "browser_session_id", "window_id"])
  test(`lost-form reporting refuses a different ${field}`, async () => {
    const f = lostFormFixture();
    f.original.binding[field] = field === "window_id" ? 99 : "different";
    await f.queue.reportLostForms();
    assert.equal(f.calls.length, 0);
  });
test("an interrupted loss-report ACK can retry without opening the application", async () => {
  let attempts = 0;
  const f = lostFormFixture({
    respond: (name, input) => {
      if (
        input.work_report?.reason !== "original_questionnaire_tab_unavailable"
      )
        return null;
      if (++attempts === 1) throw Error("backend_unavailable");
      return { form_loss_recorded: true };
    },
  });
  await f.queue.reportLostForms();
  assert.equal(f.original.loss_reported, undefined);
  await f.queue.reportLostForms();
  assert.equal(
    f.session.naukriParkedQuestionnairesV1.original.loss_reported,
    true,
  );
  assert.equal(attempts, 2);
  assert.ok(
    !f.calls.some(([name]) =>
      ["create", "navigate", "inspect", "close", "admit_naukri_work"].includes(
        name,
      ),
    ),
  );
});
test("confirmed-form cleanup is not reported as a lost pending form", async () => {
  const f = lostFormFixture();
  f.original.form_pending = false;
  await f.queue.reportLostForms(44);
  assert.equal(f.calls.length, 0);
});
