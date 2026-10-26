import assert from "node:assert/strict";
import test from "node:test";
import { inspectForm, fillForm } from "../form-bridge.js";
const url = "https://jobs.lever.co/fictional-owner/fictional-job";
const app = "11111111-1111-4111-8111-111111111111";
let calls, tab, mode;
function setup() {
  calls = [];
  tab = { id: 7, url };
  mode = "normal";
  global.chrome = {
    tabs: { query: async () => [tab] },
    scripting: {
      executeScript: async (request) => {
        calls.push({ script: request });
        if (request.args)
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
            result: {
              version: 1,
              document_id: app,
              url,
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
        const plan = {
          id: app,
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
  await assert.rejects(fillForm(), /inspect_and_review_first/);
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
