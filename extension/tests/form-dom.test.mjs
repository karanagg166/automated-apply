// Inspector logic with fictional DOMs. Chromium journey separately verifies real controls.
import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { formDOM } from "../form-dom.js";
import { formPlanText } from "../form-messages.js";

function fixture(html) {
  const dom = new JSDOM(html, {
    url: "https://job-boards.greenhouse.io/fictional/jobs/1",
    runScripts: "outside-only",
  });
  const w = dom.window;
  w.HTMLElement.prototype.getClientRects = function () {
    return this.hidden ? [] : [{}];
  };
  w.HTMLElement.prototype.getBoundingClientRect = () => ({
    width: 100,
    height: 30,
  });
  const run = (req) =>
    w.eval(`(${formDOM.toString()})(${JSON.stringify(req)})`);
  const inspection = run({ operation: "inspect", only_empty: true });
  return { w, run, inspection, close: () => w.close() };
}
function fill(f, value, field = f.inspection.fields[0]) {
  return f.run({
    operation: "fill",
    only_empty: true,
    document_id: f.inspection.document_id,
    actions: [{ field_id: field.field_id, kind: field.kind, value }],
  });
}

test("widget presence is unverified, ordinary fields stay readable, and fill is blocked", () => {
  const f = fixture(
    "<form><label>Email<input type=email></label><div data-sitekey=fictional></div></form>",
  );
  try {
    assert.equal(f.inspection.security_status, "unverified_widget");
    assert.equal(f.inspection.state, "manual_required");
    assert.equal(f.inspection.fields[0].label, "Email");
    assert.equal(fill(f, "alex@example.org").state, "manual_required");
    assert.equal(f.w.document.querySelector("input").value, "");
  } finally {
    f.close();
  }
});

test("blocking interstitial is distinct from a widget and does not imply CAPTCHA completion", () => {
  const f = fixture(
    "<h1>Verify you are human</h1><form><label>Email<input></label></form>",
  );
  try {
    assert.equal(f.inspection.security_status, "blocking");
    assert.equal(f.inspection.manual_reason, "security_challenge");
  } finally {
    f.close();
  }
});

test("a challenge appearing after review prevents preflight and filling", () => {
  const f = fixture("<form><label>Email<input></label></form>");
  try {
    const widget = f.w.document.createElement("div");
    widget.setAttribute("data-sitekey", "fictional");
    f.w.document.body.append(widget);
    const result = f.run({
      operation: "validate_fill",
      document_id: f.inspection.document_id,
    });
    assert.equal(result.reason, "security_challenge");
    assert.equal(fill(f, "alex@example.org").results.length, 0);
  } finally {
    f.close();
  }
});

test("widget removal alone does not unlock a previously read-only inspection", () => {
  const f = fixture(
    "<label>Email<input></label><div data-sitekey=fictional></div>",
  );
  try {
    f.w.document.querySelector("[data-sitekey]").remove();
    assert.equal(fill(f, "alex@example.org").state, "manual_required");
    const fresh = f.run({ operation: "inspect", only_empty: true });
    assert.notEqual(fresh.document_id, f.inspection.document_id);
  } finally {
    f.close();
  }
});

test("native country dropdowns support more than 20 choices and preserve exact codes", () => {
  const options = [
    '<option value="">Select</option>',
    ...Array.from(
      { length: 249 },
      (_, i) => `<option value=c${i}>Country ${i}</option>`,
    ),
  ];
  const f = fixture(
    `<label>Country<select>${options.join("")}</select></label>`,
  );
  try {
    assert.equal(f.inspection.fields[0].options.length, 249);
    assert.equal(fill(f, "Country 125").results[0].status, "filled");
    assert.equal(f.w.document.querySelector("select").value, "c125");
    assert.equal(fill(f, "Country 126").state, "manual_required");
  } finally {
    f.close();
  }
});

test("accessible native datalist uses freshly bound exact choices without clicking", () => {
  const f = fixture(
    "<label>Career stage<input role=combobox list=stages></label><datalist id=stages><option value=Graduate><option value=Experienced></datalist>",
  );
  try {
    assert.equal(f.inspection.fields[0].kind, "select");
    assert.equal(f.inspection.fields[0].preview_only, false);
    assert.equal(fill(f, "Graduate").results[0].status, "filled");
  } finally {
    f.close();
  }
});

test("ARIA choices are exact read-only previews; preparation never opens or selects a menu", () => {
  const f = fixture(
    "<label>Industry<input role=combobox aria-controls=industries aria-expanded=true></label><div role=listbox id=industries><div role=option>Software</div><div role=option>Finance</div></div>",
  );
  try {
    assert.deepEqual(Array.from(f.inspection.fields[0].options), [
      "Software",
      "Finance",
    ]);
    assert.equal(f.inspection.fields[0].preview_only, true);
    assert.equal(f.inspection.unsupported_controls.length, 0);
    assert.equal(fill(f, "Software").results[0].status, "untouched");
    assert.equal(f.w.document.querySelector("input").value, "");
  } finally {
    f.close();
  }
});

test("missing, shared and ambiguous custom choices stay manual", () => {
  for (const html of [
    "<input role=combobox aria-label=Country aria-controls=missing>",
    "<input role=combobox aria-label=Country aria-expanded=true aria-controls=l><input role=combobox aria-label=City aria-controls=l><div role=listbox id=l><div role=option>India</div></div>",
    "<input role=combobox aria-label=Country aria-expanded=true aria-controls=l><div role=listbox id=l><div role=option>India</div><div role=option>India</div></div>",
  ]) {
    const f = fixture(html);
    try {
      assert.equal(f.inspection.fields.length, 0);
      assert.ok(f.inspection.unsupported_controls.length);
    } finally {
      f.close();
    }
  }
});

test("native date/month are supported; ambiguous dates and sensitive choices remain manual", () => {
  const f = fixture(
    "<label>Start date<input type=date min=2026-01-01 max=2026-12-31></label><label>End month<input type=month></label><label>Custom date<input placeholder=DD/MM/YYYY></label><label>Gender<select><option>Select</option><option>Woman</option></select></label>",
  );
  try {
    assert.deepEqual(
      Array.from(f.inspection.fields, (x) => x.kind),
      ["date", "month"],
    );
    assert.equal(f.inspection.unsupported_controls.length, 2);
    assert.equal(fill(f, "2027-01-01").results[0].status, "failed");
    assert.equal(f.w.document.querySelector("input").value, "");
    f.inspection = f.run({ operation: "inspect", only_empty: true });
    assert.equal(fill(f, "2026-11-01").results[0].status, "filled");
  } finally {
    f.close();
  }
});

test("date constraints and option code changes invalidate the entire reviewed snapshot", () => {
  for (const html of [
    "<label>Start date<input type=date min=2026-01-01></label>",
    "<label>Stage<input list=l></label><datalist id=l><option value=Graduate></datalist>",
  ]) {
    const f = fixture(html);
    try {
      if (f.w.document.querySelector("option"))
        f.w.document.querySelector("option").value = "Changed";
      else f.w.document.querySelector("input").min = "2027-01-01";
      assert.equal(fill(f, "Graduate").reason, "dom_changed");
    } finally {
      f.close();
    }
  }
});

test("duplicate diagnostics collapse only the same DOM control and retain separate history rows", () => {
  const f = fixture(
    '<fieldset><legend>Employer 1</legend><div role=combobox><input aria-label="Start year" role=combobox></div></fieldset><fieldset><legend>Employer 2</legend><div role=combobox><input aria-label="Start year" role=combobox></div></fieldset>',
  );
  try {
    const entries = f.inspection.unsupported_controls;
    assert.equal(entries.length, 2);
    assert.notEqual(entries[0].control_id, entries[1].control_id);
    const rendered = formPlanText({
      unsupported_controls: [entries[0], entries[0], entries[1]],
    });
    assert.equal(
      (rendered.match(/Manual completion required/g) || []).length,
      2,
    );
    assert.match(rendered, /Employer 1/);
    assert.match(rendered, /Employer 2/);
  } finally {
    f.close();
  }
});

test("existing values never enter the preview or get overwritten, including native dates", () => {
  const f = fixture(
    '<label>Email<input value="owner@example.org"></label><label>Start date<input type=date value=2026-10-01></label><label>Phone<input></label>',
  );
  try {
    assert.equal(f.inspection.fields.length, 1);
    assert.equal(
      JSON.stringify(f.inspection).includes("owner@example.org"),
      false,
    );
    fill(f, "123");
    assert.equal(
      f.w.document.querySelector("input").value,
      "owner@example.org",
    );
    assert.equal(f.w.document.querySelector("[type=date]").value, "2026-10-01");
  } finally {
    f.close();
  }
});

test("unqualified repeated fields stay separate and cannot reuse one ambiguous answer", () => {
  const f = fixture(
    "<label>Designation<input></label><label>Designation<input></label>",
  );
  try {
    assert.equal(f.inspection.fields.length, 2);
    assert.ok(f.inspection.fields.every((field) => field.preview_only));
    assert.equal(fill(f, "Engineer").results[0].status, "untouched");
  } finally {
    f.close();
  }
});

test("button combobox choices are readable while selected and sensitive widgets stay manual", () => {
  const f = fixture(
    "<button type=button role=combobox aria-label=Industry aria-controls=l aria-expanded=true></button><div id=l role=listbox><span role=option>Software</span></div><fieldset><legend>Gender</legend><input aria-label=Choice></fieldset>",
  );
  try {
    assert.equal(f.inspection.fields.length, 1);
    assert.equal(f.inspection.fields[0].label, "Industry");
    assert.equal(f.inspection.fields[0].preview_only, true);
    assert.equal(f.inspection.unsupported_controls.length, 1);
  } finally {
    f.close();
  }
});

test("incompleteRequired detects empty required custom combobox and returns needs_input on verify_fill", () => {
  const f = fixture(
    "<form><label>Email<input type=email required></label><div role=combobox aria-required=true aria-label=Department tabindex=0>Choose department</div></form>",
  );
  try {
    assert.equal(f.inspection.fields.length, 1);
    assert.equal(f.inspection.unsupported_controls.length, 1);
    assert.equal(f.inspection.unsupported_controls[0].required, true);

    // Native field is filled, but required custom combobox is unresolved
    const filled = fill(f, "alex@example.org");
    assert.equal(filled.results[0].status, "filled");
    // Must return needs_input rather than falsely inferring custom widget was filled
    assert.equal(filled.state, "needs_input");

    // When the custom combobox is answered on the page, verify_fill returns form_filled
    f.w.document
      .querySelector('[role="combobox"]')
      .setAttribute("data-value", "eng");
    const verified = f.run({
      operation: "verify_fill",
      document_id: f.inspection.document_id,
    });
    assert.equal(verified.state, "form_filled");
  } finally {
    f.close();
  }
});
