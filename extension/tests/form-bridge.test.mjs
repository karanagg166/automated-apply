import assert from "node:assert/strict";
import test from "node:test";
import {
  inspectForm,
  prepareAnswers,
  fillForm,
  cancelPreparedForm,
} from "../form-bridge.js";
import { formErrorMessage, formPlanText } from "../form-messages.js";
const url = "https://jobs.lever.co/fictional-owner/fictional-job";
const zohoUrl =
  "https://fictional-tenant.zohorecruit.in/jobs/Careers/987654/Senior-Backend-Engineer?source=CareerSite&ref=fictional";
const app = "11111111-1111-4111-8111-111111111111";
let calls, tab, mode, inspectionOverride, planOverride;
function setup() {
  calls = [];
  tab = { id: 7, url };
  mode = "normal";
  inspectionOverride = null;
  planOverride = null;
  global.chrome = {
    storage: {
      local: {
        get: async () => ({
          connectedChromeProfileV1: {
            id: app,
            secret: "f".repeat(64),
            connected: true,
            windowId: 1,
          },
        }),
      },
      session: { get: async () => ({ applicationBrowserSessionV1: app }) },
    },
    tabs: { query: async () => [tab] },
    scripting: {
      executeScript: async (request) => {
        calls.push({ script: request });
        if (request.args?.[0]?.operation === "fill")
          return [
            {
              result: {
                state: "form_filled",
                results: [{ field_id: "f0", status: "filled" }],
                submitted: false,
              },
            },
          ];
        return [
          {
            result: inspectionOverride || {
              version: 1,
              document_id: app,
              url: tab.url,
              fields: [{ field_id: "f0", kind: "email", label: "Email" }],
              state: "ready",
              has_submit: true,
              has_next: false,
            },
          },
        ];
      },
    },
    runtime: {
      sendNativeMessage: async (_host, req) => {
        calls.push({ native: req });
        if (mode === "mismatch")
          return {
            version: 1,
            request_id: "wrong",
            ok: true,
            data: { submitted: false },
          };
        const plan = planOverride || {
          id: app,
          target_url: tab.url,
          inspection: {
            document_id: app,
            fields: [{ field_id: "f0", label: "Email" }],
          },
          actions: [
            {
              field_id: "f0",
              kind: "email",
              value: "alex@example.org",
              needs_input: false,
            },
            { field_id: "f1", kind: "file", needs_input: false },
          ],
          approved_fields: ["f0"],
        };
        return {
          version: 1,
          request_id: req.request_id,
          ok: true,
          data: { submitted: false, plan },
        };
      },
    },
  };
}
for (const lostCommand of ["authorize_form", "record_form_fill"]) {
  test(`native connection loss during ${lostCommand} never replays a consumed fill`, async () => {
    setup();
    const original = chrome.runtime.sendNativeMessage;
    chrome.runtime.sendNativeMessage = async (host, request) => {
      const response = await original(host, request);
      if (request.command === lostCommand)
        throw Error("Native host disconnected");
      return response;
    };
    await inspectForm(app);
    await assert.rejects(fillForm(), /Native host disconnected/);
    await assert.rejects(fillForm(), /inspect_and_review_first/);
    assert.equal(
      calls.filter((c) => c.native?.command === "authorize_form").length,
      1,
    );
    assert.equal(
      calls.filter((c) => c.script?.args?.[0]?.operation === "fill").length,
      lostCommand === "record_form_fill" ? 1 : 0,
    );
  });
}
test("manual bridge inspects, authorizes exact nonfile fields, fills once and records status only", async () => {
  setup();
  await inspectForm(app);
  const result = await fillForm();
  assert.equal(result.state, "form_filled");
  const native = calls.filter((c) => c.native).map((c) => c.native);
  assert.deepEqual(
    native.map((n) => n.command),
    ["inspect_form", "authorize_form", "record_form_fill"],
  );
  assert.deepEqual(native[1].field_ids, ["f0"]);
  assert.equal(JSON.stringify(native[2]).includes("alex@"), false);
  assert.equal(
    calls.find((c) => c.script?.args?.[0]?.operation === "fill").script.args[0]
      .only_empty,
    true,
  );
  await assert.rejects(fillForm(), /inspect_and_review_first/);
});
test("current form prepares answers without inventing or asking for an application ID", async () => {
  setup();
  const plan = await prepareAnswers();
  assert.equal(plan.id, app);
  const native = calls.find((call) => call.native).native;
  assert.equal(native.command, "prepare_form_answers");
  assert.equal(native.application_id, undefined);
  assert.deepEqual(calls[0].script.args, [
    { operation: "inspect", only_empty: true },
  ]);
  assert.equal(
    calls.some((call) => call.script?.args?.[0]?.operation === "fill"),
    false,
  );
  await fillForm();
});
test("current form preserves actionable, bounded backend failures", async () => {
  setup();
  chrome.runtime.sendNativeMessage = async (_host, req) => ({
    version: 1,
    request_id: req.request_id,
    ok: false,
    error_code: "profile_review_required",
  });
  await assert.rejects(prepareAnswers(), /profile_review_required/);
  await assert.rejects(fillForm(), /inspect_and_review_first/);
});
test("current form rejects a different active page before inspection", async () => {
  setup();
  await assert.rejects(prepareAnswers({ id: 99, url }), /page_changed/);
  assert.equal(calls.length, 0);
});
test("manual bridge rejects navigation between inspection and fill", async () => {
  setup();
  await inspectForm(app);
  tab = { id: 8, url };
  await assert.rejects(fillForm(), /page_changed/);
  assert.equal(
    calls.filter((c) => c.native?.command === "authorize_form").length,
    0,
  );
});

test("authorization cannot switch the reviewed plan or destination", async () => {
  setup();
  await inspectForm(app);
  planOverride = {
    id: app,
    target_url: "https://jobs.lever.co/different/job",
    inspection: { document_id: app },
    actions: [],
    approved_fields: [],
  };
  await assert.rejects(fillForm(), /form_request_rejected/);
  assert.equal(
    calls.filter((c) => c.script?.args?.[0]?.operation === "fill").length,
    0,
  );
});

test("navigation after filling records manual handoff instead of a completed page", async () => {
  setup();
  await inspectForm(app);
  const execute = chrome.scripting.executeScript;
  chrome.scripting.executeScript = async (request) => {
    const result = await execute(request);
    if (request.args?.[0]?.operation === "fill")
      tab = { ...tab, url: "https://example.com/elsewhere" };
    return result;
  };
  const result = await fillForm();
  assert.equal(result.state, "manual_required");
  const receipt = calls.find((c) => c.native?.command === "record_form_fill")
    .native.receipt;
  assert.equal(receipt.state, "manual_required");
  assert.equal(receipt.submitted, false);
});
test("manual bridge rejects bad IDs and restricted pages before native dispatch", async () => {
  setup();
  await assert.rejects(inspectForm("invented"), /application_id_required/);
  tab = { id: 7, url: "chrome://settings" };
  await assert.rejects(inspectForm(app), /supported_application_page_required/);
  assert.equal(calls.length, 0);
});
test("native correlation mismatch cannot yield executable mappings", async () => {
  setup();
  mode = "mismatch";
  await assert.rejects(inspectForm(app), /form_request_rejected/);
  await assert.rejects(fillForm(), /inspect_and_review_first/);
});
test("bridge strips client-only unsupported control diagnostics before native dispatch and reattaches them to the plan", async () => {
  setup();
  tab = { id: 7, url: zohoUrl, title: "Zoho Recruit Fictional Role" };
  inspectionOverride = {
    version: 1,
    document_id: app,
    url: zohoUrl,
    fields: [{ field_id: "f0", kind: "email", label: "Email", required: true }],
    state: "ready",
    has_submit: true,
    has_next: false,
    manual_reason: null,
    unsupported_controls: [
      {
        kind: "custom_combobox",
        label: "Preferred Location",
        required: true,
        reason: "Custom combobox or dropdown requires manual selection",
      },
    ],
  };
  const plan = await prepareAnswers();
  const nativeInspection = calls.find((c) => c.native).native.inspection;
  assert.equal("unsupported_controls" in nativeInspection, false);
  assert.equal("manual_reason" in nativeInspection, false);
  assert.equal(plan.unsupported_controls.length, 1);
  assert.equal(plan.unsupported_controls[0].label, "Preferred Location");
});
test("expired review authorization is rejected before native authorization or DOM fill", async () => {
  setup();
  planOverride = {
    id: app,
    target_url: url,
    expires_at: new Date(Date.now() - 5000).toISOString(),
    inspection: {
      document_id: app,
      fields: [{ field_id: "f0", label: "Email" }],
    },
    actions: [
      {
        field_id: "f0",
        kind: "email",
        value: "alex@example.org",
        needs_input: false,
      },
    ],
    approved_fields: ["f0"],
  };
  await prepareAnswers();
  await assert.rejects(fillForm(), /fill_plan_stale/);
  assert.equal(
    calls.some((c) => c.native?.command === "authorize_form"),
    false,
  );
  assert.equal(
    calls.some((c) => c.script?.args?.[0]?.operation === "fill"),
    false,
  );
});
test("form messages explain unsupported Zoho controls, consent, radio groups, and DOM/step changes", () => {
  const errCombo = Object.assign(Error("unsupported_application_form"), {
    manual_reason: "unsupported_controls",
    unsupported_controls: [
      {
        kind: "custom_combobox",
        label: "Department",
        required: true,
        reason: "Custom combobox or dropdown requires manual selection",
      },
    ],
  });
  assert.match(formErrorMessage(errCombo), /Custom combobox or dropdown/);

  const errFrame = Object.assign(Error("unsupported_application_form"), {
    manual_reason: "cross_origin_frame",
  });
  assert.match(formErrorMessage(errFrame), /cross-origin frame/i);

  const errSensitive = Object.assign(Error("unsupported_application_form"), {
    manual_reason: "sensitive_control",
  });
  assert.match(formErrorMessage(errSensitive), /Sensitive fields/);

  assert.match(
    formErrorMessage(Error("dom_changed")),
    /form changed after answers were prepared/i,
  );
  assert.match(formErrorMessage(Error("step_changed")), /form step changed/i);
  assert.match(
    formErrorMessage(Error("fill_plan_stale")),
    /review authorization expired/i,
  );

  const text = formPlanText({
    inspection: {
      fields: [
        {
          field_id: "f0",
          kind: "radio",
          label: "Remote",
          group_label: "Work arrangement",
          required: true,
        },
        {
          field_id: "f1",
          kind: "checkbox",
          label: "I agree to the privacy policy",
          required: true,
        },
        {
          field_id: "f2",
          kind: "email",
          label: "Email",
          required: true,
          invalid: true,
        },
      ],
    },
    actions: [
      {
        field_id: "f0",
        kind: "radio",
        value: "true",
        needs_input: false,
        evidence: ["candidate_profile:1"],
      },
      {
        field_id: "f1",
        kind: "checkbox",
        value: null,
        needs_input: true,
        evidence: [],
      },
      {
        field_id: "f2",
        kind: "email",
        value: "alex@example.org",
        needs_input: false,
        evidence: ["candidate_profile:1"],
      },
    ],
    unsupported_controls: [
      {
        kind: "date",
        label: "Available Start Date",
        required: true,
        reason: "Date field requires manual entry",
      },
    ],
  });
  assert.match(text, /Work arrangement \(Remote\) \(required\)/);
  assert.match(
    text,
    /Consent and legal declarations are never selected automatically/,
  );
  assert.match(text, /Email \(required, validation error on page\)/);
  assert.match(
    text,
    /Available Start Date \(required\)\nManual completion required: Date field requires manual entry\nSource: Manual only/,
  );
});

test("cancellation during native authorization prevents DOM mutation and replay", async () => {
  setup();
  await prepareAnswers();
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async (host, req) => {
    const response = await original(host, req);
    if (req.command === "authorize_form") cancelPreparedForm();
    return response;
  };
  await assert.rejects(fillForm(), /form_cancelled_reprepare_required/);
  assert.equal(
    calls.filter((c) => c.script?.args?.[0]?.operation === "fill").length,
    0,
  );
  await assert.rejects(fillForm(), /inspect_and_review_first/);
});

test("cancelled or superseded preparations cannot replace current reviewed context", async () => {
  setup();
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async (host, req) => {
    const response = await original(host, req);
    if (req.command === "prepare_form_answers") cancelPreparedForm();
    return response;
  };
  await assert.rejects(prepareAnswers(), /form_cancelled_reprepare_required/);
  await assert.rejects(fillForm(), /inspect_and_review_first/);
  chrome.runtime.sendNativeMessage = original;
  await prepareAnswers();
  assert.equal((await fillForm()).submitted, false);
});

for (const host of [
  "simplify.jobs",
  "www.linkedin.com",
  "mail.google.com",
  "accounts.google.com",
]) {
  test(`restricted form on ${host} is refused before reading the DOM or contacting native host`, async () => {
    setup();
    tab.url = `https://${host}/fictional/apply`;
    await assert.rejects(
      prepareAnswers(),
      /supported_application_page_required/,
    );
    assert.equal(calls.length, 0);
  });
}

test("CAPTCHA preview keeps blocked state in native request and cannot authorize even with ready answers", async () => {
  setup();
  inspectionOverride = {
    version: 1,
    document_id: app,
    url,
    state: "manual_required",
    fields: [{ field_id: "f0", kind: "email", label: "Email" }],
    security_status: "unverified_widget",
    manual_reason: "security_widget",
  };
  const plan = await inspectForm(app);
  assert.equal(plan.state, "read_only");
  assert.equal(
    calls.find((c) => c.native).native.inspection.state,
    "manual_required",
  );
  assert.equal(
    "security_status" in calls.find((c) => c.native).native.inspection,
    false,
  );
  assert.match(formPlanText(plan), /completion is unverified/);
  await assert.rejects(fillForm(), /read_only_preview/);
  assert.equal(
    calls.some((c) => c.native?.command === "authorize_form"),
    false,
  );
});

test("fresh security preflight rejects before native authorization", async () => {
  setup();
  await prepareAnswers();
  const execute = chrome.scripting.executeScript;
  chrome.scripting.executeScript = async (req) =>
    req.args[0].operation === "validate_fill"
      ? [{ result: { state: "manual_required", reason: "security_challenge" } }]
      : execute(req);
  await assert.rejects(fillForm(), /security_challenge/);
  assert.equal(
    calls.some((c) => c.native?.command === "authorize_form"),
    false,
  );
});

test("read-only action values are never included in fill authorization", async () => {
  setup();
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async (host, req) => {
    const result = await original(host, req);
    result.data.plan.actions.push({
      field_id: "f2",
      kind: "select",
      value: "Graduate",
      needs_input: false,
      preview_only: true,
    });
    return result;
  };
  await inspectForm(app);
  await fillForm();
  assert.deepEqual(
    calls.find((c) => c.native?.command === "authorize_form").native.field_ids,
    ["f0"],
  );
});

test("fill authorizes only the owner's selected subset and rejects forged field IDs", async () => {
  setup();
  const original = chrome.runtime.sendNativeMessage;
  chrome.runtime.sendNativeMessage = async (host, request) => {
    const result = await original(host, request);
    if (request.command !== "authorize_form")
      result.data.plan.actions.push({
        field_id: "f2",
        kind: "text",
        value: "confirmed",
        needs_input: false,
      });
    return result;
  };
  await prepareAnswers();
  await fillForm({ field_ids: ["f0"] });
  assert.deepEqual(
    calls.find((c) => c.native?.command === "authorize_form").native.field_ids,
    ["f0"],
  );
  await prepareAnswers();
  await assert.rejects(
    fillForm({ field_ids: ["f99"] }),
    /reviewed_field_selection_invalid/,
  );
  assert.equal(
    calls.filter((c) => c.native?.command === "authorize_form").length,
    1,
  );
});
