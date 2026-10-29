import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { formDOM } from "../form-dom.js";

function fixture(html, options = {}) {
  const dom = new JSDOM(html, {
    url: "https://fictional.example/jobs/42",
    runScripts: "outside-only",
  });
  const w = dom.window;
  w.TextEncoder = TextEncoder;
  w.HTMLElement.prototype.getClientRects = function () {
    return this.hidden ? [] : [{}];
  };
  w.HTMLElement.prototype.getBoundingClientRect = () => ({
    width: 100,
    height: 30,
  });
  const run = (req) =>
    w.eval(`(${formDOM.toString()})(${JSON.stringify(req)})`);
  return {
    w,
    run,
    inspect: () => run({ operation: "inspect", only_empty: true, ...options }),
    close: () => w.close(),
  };
}
const action = (field, value) => ({
  field_id: field.field_id,
  kind: field.kind,
  value,
});

test("semantic identity uses SHA256 of metadata and survives other previously answered controls", () => {
  const f = fixture(
    "<label>Email<input id=email></label><label>Phone<input type=tel name=phone></label>",
  );
  try {
    const first = f.inspect();
    const phone = first.fields[1];
    const expected = JSON.stringify([
      "https://fictional.example",
      "/jobs/42",
      "Application",
      null,
      null,
      "Phone",
      "tel",
      "name:phone",
      "",
      "",
      "",
    ]);
    assert.equal(
      phone.semantic_key,
      createHash("sha256").update(expected).digest("hex"),
    );
    f.w.document.querySelector("#email").value = "owner-entered@example.org";
    const second = f.inspect();
    assert.equal(second.fields[0].field_id, "f0");
    assert.equal(second.fields[0].semantic_key, phone.semantic_key);
    assert.equal(second.completed_count, 1);
    assert.equal(
      JSON.stringify(second).includes("owner-entered@example.org"),
      false,
    );
  } finally {
    f.close();
  }
});

test("repeated employment and education sections keep separate semantic identities", () => {
  const f = fixture(
    "<div aria-current=step>Employment</div><fieldset><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset><fieldset><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset><fieldset><legend>Education history</legend><label>Start date<input type=date name=start></label></fieldset>",
  );
  try {
    const inspection = f.inspect();
    assert.equal(new Set(inspection.fields.map((x) => x.semantic_key)).size, 3);
    assert.match(inspection.fields[0].section, /entry 1/);
    assert.match(inspection.fields[1].section, /entry 2/);
    assert.equal(inspection.fields[2].section, "Education history");
    assert.ok(inspection.fields.every((x) => x.page_step === "Employment"));
    f.w.document.querySelector("[aria-current]").textContent = "Education";
    assert.notEqual(
      f.inspect().fields[0].semantic_key,
      inspection.fields[0].semantic_key,
    );
  } finally {
    f.close();
  }
});

test("unlabeled repeated questions remain manual even with distinct control IDs", () => {
  const f = fixture(
    "<label>Start date<input type=date id=a></label><label>Start date<input type=date id=b></label>",
  );
  try {
    const inspection = f.inspect();
    assert.ok(inspection.fields.every((x) => x.preview_only));
    assert.notEqual(
      inspection.fields[0].semantic_key,
      inspection.fields[1].semantic_key,
    );
  } finally {
    f.close();
  }
});

test("challenge presence, blocking, disappearance and fresh review never imply resolved CAPTCHA", () => {
  const f = fixture(
    "<label>Email<input></label><div data-sitekey=fictional></div>",
  );
  try {
    assert.equal(f.inspect().challenge_state, "WIDGET_PRESENT_UNVERIFIED");
    f.w.document.querySelector("[data-sitekey]").remove();
    const next = f.inspect();
    assert.equal(next.challenge_state, "UNKNOWN");
    assert.equal(next.state, "manual_required");
    const alert = f.w.document.createElement("h1");
    alert.textContent = "Verify you are human";
    f.w.document.body.append(alert);
    assert.equal(f.inspect().challenge_state, "CHALLENGE_BLOCKING");
    alert.remove();
    assert.equal(f.inspect().challenge_state, "UNKNOWN");
  } finally {
    f.close();
  }
});

test("framework interactions require explicit preparation and fill authorization", async () => {
  const f = fixture(
    "<label>Email<input data-framework-controlled=true></label>",
  );
  try {
    const first = f.inspect();
    assert.equal(first.fields[0].preview_only, true);
    const second = f.run({
      operation: "inspect",
      only_empty: true,
      interactions_allowed: true,
    });
    assert.equal(second.fields[0].preview_only, false);
    const rejected = f.run({
      operation: "fill",
      document_id: second.document_id,
      only_empty: true,
      actions: [action(second.fields[0], "alex@example.org")],
    });
    assert.equal(rejected.results[0].status, "failed");
    assert.equal(f.w.document.querySelector("input").value, "");
  } finally {
    f.close();
  }
});

test("website retained value is checked after blur including a delayed reset", async () => {
  for (const reset of [false, true]) {
    const f = fixture(
      "<label>Email<input data-framework-controlled=true></label>",
      { interactions_allowed: true },
    );
    try {
      const el = f.w.document.querySelector("input");
      let receivedInput = false;
      el.addEventListener("input", () => {
        receivedInput = true;
      });
      el.addEventListener("blur", () => {
        if (reset)
          f.w.setTimeout(() => {
            el.value = "";
          }, 350);
      });
      const inspection = f.inspect();
      const result = await f.run({
        operation: "fill",
        document_id: inspection.document_id,
        only_empty: true,
        interaction_authorized: true,
        actions: [action(inspection.fields[0], "alex@example.org")],
      });
      assert.equal(receivedInput, true);
      assert.equal(result.results[0].status, reset ? "failed" : "filled");
      assert.equal(result.state, reset ? "needs_input" : "form_filled");
      assert.equal(result.verification, "retained_after_blur");
    } finally {
      f.close();
    }
  }
});

test("interactive cancellation stops remaining fields and preserves a partial receipt", async () => {
  const f = fixture(
    "<label>Email<input id=email></label><label>Phone<input id=phone></label>",
    { interactions_allowed: true },
  );
  try {
    const inspection = f.inspect();
    const pending = f.run({
      operation: "fill",
      document_id: inspection.document_id,
      only_empty: true,
      interaction_authorized: true,
      actions: inspection.fields.map((field) => action(field, "fictional")),
    });
    f.run({ operation: "cancel_fill", document_id: inspection.document_id });
    const result = await pending;
    assert.equal(result.state, "manual_required");
    assert.equal(result.reason, "form_cancelled_reprepare_required");
    assert.equal(result.results.length, 1);
    assert.equal(f.w.document.querySelector("#phone").value, "");
  } finally {
    f.close();
  }
});

test("a fresh inspection during an in-flight fill invalidates all remaining writes", async () => {
  const f = fixture(
    "<label>Email<input id=email></label><label>Phone<input id=phone></label>",
    { interactions_allowed: true },
  );
  try {
    const inspection = f.inspect();
    const pending = f.run({
      operation: "fill",
      document_id: inspection.document_id,
      only_empty: true,
      interaction_authorized: true,
      actions: inspection.fields.map((field) => action(field, "fictional")),
    });
    f.inspect();
    const result = await pending;
    assert.equal(result.state, "manual_required");
    assert.equal(result.reason, "step_changed");
    assert.equal(f.w.document.querySelector("#phone").value, "");
  } finally {
    f.close();
  }
});

test("an already-open uniquely bound ARIA combobox supports exact reviewed option interaction", async () => {
  const f = fixture(
    "<label>Career stage<input role=combobox aria-expanded=true aria-controls=stages></label><div role=listbox id=stages><div role=option>Graduate</div><div role=option>Experienced</div></div>",
    { interactions_allowed: true },
  );
  try {
    const el = f.w.document.querySelector("input");
    const list = f.w.document.querySelector("[role=listbox]");
    const option = list.querySelector("[role=option]");
    let clicks = 0;
    option.addEventListener("click", () => {
      clicks++;
      el.value = option.textContent;
      option.setAttribute("aria-selected", "true");
      el.setAttribute("aria-expanded", "false");
      list.hidden = true;
    });
    const inspection = f.inspect();
    assert.equal(inspection.fields[0].preview_only, false);
    assert.equal(clicks, 0);
    const result = await f.run({
      operation: "fill",
      only_empty: true,
      interaction_authorized: true,
      document_id: inspection.document_id,
      actions: [action(inspection.fields[0], "Graduate")],
    });
    assert.equal(result.results[0].status, "filled");
    assert.equal(result.state, "form_filled");
    assert.equal(clicks, 1);
    assert.equal(el.value, "Graduate");
  } finally {
    f.close();
  }
});

test("ARIA option click without a retained site value remains manual and never writes a fake selection", async () => {
  const f = fixture(
    "<label>Career stage<input role=combobox aria-expanded=true aria-controls=stages></label><div role=listbox id=stages><div role=option>Graduate</div></div>",
    { interactions_allowed: true },
  );
  try {
    const inspection = f.inspect();
    const result = await f.run({
      operation: "fill",
      only_empty: true,
      interaction_authorized: true,
      document_id: inspection.document_id,
      actions: [action(inspection.fields[0], "Graduate")],
    });
    assert.equal(result.results[0].status, "failed");
    assert.equal(f.w.document.querySelector("input").value, "");
  } finally {
    f.close();
  }
});

test("reordered history rows without stable entry identities remain manual", () => {
  const f = fixture(
    "<fieldset data-test=first><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset><fieldset data-test=second><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset>",
  );
  try {
    const first = f.inspect();
    assert.ok(
      first.fields.every(
        (field) => field.preview_only && /no stable/.test(field.manual_reason),
      ),
    );
    f.w.document.body.prepend(f.w.document.querySelector("[data-test=second]"));
    const reordered = f.inspect();
    assert.ok(reordered.fields.every((field) => field.preview_only));
    const result = f.run({
      operation: "fill",
      document_id: reordered.document_id,
      only_empty: true,
      actions: [action(reordered.fields[0], "2020-01-01")],
    });
    assert.equal(result.results[0].status, "untouched");
    assert.ok(
      [...f.w.document.querySelectorAll("input")].every(
        (el) => el.value === "",
      ),
    );
  } finally {
    f.close();
  }
});

test("stable history container identity survives entry reorder without swapping answers", () => {
  const f = fixture(
    "<fieldset id=employment-alpha><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset><fieldset id=employment-beta><legend>Employment history</legend><label>Start date<input type=date name=start></label></fieldset>",
  );
  try {
    const first = f.inspect();
    assert.ok(first.fields.every((field) => !field.preview_only));
    f.w.document.body.prepend(f.w.document.querySelector("#employment-beta"));
    const second = f.inspect();
    assert.equal(second.fields[0].semantic_key, first.fields[1].semantic_key);
    assert.equal(second.fields[1].semantic_key, first.fields[0].semantic_key);
  } finally {
    f.close();
  }
});

test("expiration during eventful filling stops before writing the next field", async () => {
  const f = fixture(
    "<label>Email<input id=email></label><label>Phone<input id=phone></label>",
    { interactions_allowed: true },
  );
  try {
    const inspection = f.inspect();
    const result = await f.run({
      operation: "fill",
      document_id: inspection.document_id,
      expires_at: new Date(Date.now() + 50).toISOString(),
      only_empty: true,
      interaction_authorized: true,
      actions: inspection.fields.map((field) => action(field, "fictional")),
    });
    assert.equal(result.state, "manual_required");
    assert.equal(result.reason, "fill_plan_stale");
    assert.equal(f.w.document.querySelector("#phone").value, "");
  } finally {
    f.close();
  }
});

test("service-worker-controlled pages remain read-only for eventful filling", () => {
  const f = fixture("<label>Email<input id=email></label>", {
    interactions_allowed: true,
  });
  try {
    Object.defineProperty(f.w.navigator, "serviceWorker", {
      value: { controller: {} },
    });
    const inspection = f.inspect();
    assert.equal(inspection.state, "manual_required");
    assert.equal(
      inspection.manual_reason,
      "background_network_scope_unverified",
    );
    assert.equal(f.w.document.querySelector("input").value, "");
  } finally {
    f.close();
  }
});

test("questions reaching the bounded label limit remain manual rather than answering truncated text", () => {
  const f = fixture(
    `<label>${"Complete question ".repeat(15)}<textarea></textarea></label>`,
    { interactions_allowed: true },
  );
  try {
    const inspection = f.inspect();
    assert.equal(inspection.fields[0].label.length, 160);
    assert.equal(inspection.fields[0].preview_only, true);
    assert.match(
      inspection.fields[0].manual_reason,
      /complete question manually/,
    );
  } finally {
    f.close();
  }
});
