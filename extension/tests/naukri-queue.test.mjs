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
              result: options.sortReport || {
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
