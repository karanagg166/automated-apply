import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { naukriChatbot } from "../naukri-chatbot.js";

const url = "https://www.naukri.com/job-listings-fictional-291026123456";
async function fixture(options = {}) {
  const dom = new JSDOM(
    `<div class="chatbot_DrawerContentWrapper"><div class="chatbot_Nav">Application</div><div class="chatbot_MessageContainer"><div class="botItem chatbot_ListItem"><div class="botMsg msg">${options.question || "What is your notice period?"}</div></div></div><div class="footerInputBoxWrapper"><div class="chipsContainer">${options.text ? "" : '<div class="chatbot_Chip chipItem">Immediate</div><div class="chatbot_Chip chipItem">30 days</div>'}</div><div class="textArea" contenteditable="true"${options.text ? "" : " hidden"}></div><div class="send"><div class="sendMsg">Save</div></div>${options.file ? '<input class="chatbot_Uploader" type="file">' : ""}</div></div>`,
    { url, runScripts: "outside-only" },
  );
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  Object.defineProperty(w.navigator, "userActivation", {
    value: { isActive: false },
  });
  let visibility = "hidden",
    clicks = 0,
    inputEvents = 0;
  Object.defineProperty(w.document, "visibilityState", {
    get: () => visibility,
  });
  Object.defineProperty(w.document.body, "innerText", {
    get() {
      return this.textContent;
    },
  });
  w.Element.prototype.getClientRects = function () {
    return this.closest("[hidden]") ? [] : [1];
  };
  w.setTimeout = (fn) => setTimeout(fn, 0);
  for (const e of w.document.querySelectorAll(".chatbot_Chip,.send"))
    e.onclick = () => {
      clicks++;
    };
  w.document.querySelector(".textArea").oninput = () => {
    inputEvents++;
  };
  if (options.file)
    w.document.querySelector(".chatbot_Chip").textContent = "Upload Resume";
  if (options.existing)
    w.document.querySelector(".textArea").textContent =
      "Owner's existing value";
  if (options.duplicate)
    w.document.body.append(
      w.document.querySelector(".chatbot_DrawerContentWrapper").cloneNode(true),
    );
  const run = async (extra = {}) =>
    JSON.parse(
      JSON.stringify(
        await w.eval(
          `(${naukriChatbot.toString()})(${JSON.stringify({ operation: "inspect", url, requisition: "291026123456", ...extra })})`,
        ),
      ),
    );
  return {
    run,
    w,
    close: () => w.close(),
    counts: () => ({ clicks, inputEvents }),
    adopt: () => {
      visibility = "visible";
      w.document.dispatchEvent(new w.Event("visibilitychange"));
      visibility = "hidden";
      w.document.dispatchEvent(new w.Event("visibilitychange"));
    },
  };
}
const permit = (step, answer) => ({
  operation: "answer",
  document_id: step.document_id,
  step_sha256: step.step_sha256,
  answer,
  permit_expires_at: new Date(Date.now() + 1500).toISOString(),
});
test("retained genuine chatbot class structure produces a bounded semantic question", async () => {
  const f = await fixture();
  try {
    const s = await f.run();
    assert.equal(s.kind, "questionnaire");
    assert.equal(s.answer_kind, "choice");
    assert.deepEqual(s.options, ["Immediate", "30 days"]);
    assert.match(s.step_sha256, /^[a-f0-9]{64}$/);
    assert.equal(f.counts().clicks, 0);
  } finally {
    f.close();
  }
});
test("an exact approved choice is consumed once even if its handler submits immediately", async () => {
  const f = await fixture();
  try {
    const s = await f.run();
    const a = permit(s, "Immediate");
    assert.equal((await f.run(a)).kind, "questionnaire_answer_attempted");
    assert.equal(
      (await f.run(a)).reason,
      "questionnaire_step_changed_or_consumed",
    );
    assert.equal(f.counts().clicks, 1);
  } finally {
    f.close();
  }
});
test("background text input and Save use no focus, keyboard or clipboard", async () => {
  const f = await fixture({ text: true, question: "What is your full name?" });
  try {
    const s = await f.run();
    const r = await f.run(permit(s, "Fictional Candidate"));
    assert.equal(r.kind, "questionnaire_answer_attempted");
    assert.equal(r.submitted, false);
    assert.deepEqual(f.counts(), { clicks: 1, inputEvents: 1 });
  } finally {
    f.close();
  }
});
test("the observed text editor plus optional Skip chip accepts text without clicking Skip", async () => {
  const f = await fixture({ text: true, question: "Explain your training" });
  try {
    const chips = f.w.document.querySelector(".chipsContainer");
    const skip = f.w.document.createElement("div");
    skip.className = "chatbot_Chip chipInRow chipItem";
    skip.textContent = "Skip this question";
    let skipped = 0;
    skip.onclick = () => skipped++;
    chips.append(skip);
    const s = await f.run();
    assert.equal(s.answer_kind, "text");
    assert.deepEqual(s.options, []);
    const a = permit(s, "Fictional owner-confirmed training answer");
    assert.equal((await f.run(a)).kind, "questionnaire_answer_attempted");
    assert.deepEqual(f.counts(), { clicks: 1, inputEvents: 1 });
    assert.equal(skipped, 0);
    assert.equal(
      (await f.run(a)).reason,
      "questionnaire_step_changed_or_consumed",
    );
  } finally {
    f.close();
  }
});
test("a Skip chip without a visible editor retains exact-choice handling", async () => {
  const f = await fixture();
  try {
    const chips = f.w.document.querySelector(".chipsContainer");
    chips.replaceChildren(chips.firstElementChild);
    chips.firstElementChild.textContent = "Skip this question";
    const s = await f.run();
    assert.equal(s.answer_kind, "choice");
    assert.deepEqual(s.options, ["Skip this question"]);
    assert.equal(
      (await f.run(permit(s, "Invented free text"))).reason,
      "questionnaire_exact_choice_required",
    );
    assert.deepEqual(f.counts(), { clicks: 0, inputEvents: 0 });
  } finally {
    f.close();
  }
});
test("visible editors do not turn genuine choices into unrestricted text", async () => {
  const f = await fixture();
  try {
    f.w.document.querySelector(".textArea").removeAttribute("hidden");
    const s = await f.run();
    assert.equal(s.answer_kind, "choice");
    assert.equal(
      (await f.run(permit(s, "Unknown choice"))).reason,
      "questionnaire_exact_choice_required",
    );
    assert.deepEqual(f.counts(), { clicks: 0, inputEvents: 0 });
  } finally {
    f.close();
  }
});
test("a real choice appearing beside the text editor invalidates the old text permit", async () => {
  const f = await fixture({ text: true });
  try {
    const s = await f.run();
    const chip = f.w.document.createElement("div");
    chip.className = "chatbot_Chip";
    chip.textContent = "Immediate";
    f.w.document.querySelector(".chipsContainer").append(chip);
    assert.equal(
      (await f.run(permit(s, "Fictional text"))).reason,
      "questionnaire_step_changed_or_consumed",
    );
    assert.deepEqual(f.counts(), { clicks: 0, inputEvents: 0 });
  } finally {
    f.close();
  }
});
for (const [name, options, mutate, answer, reason] of [
  [
    "unknown choice",
    {},
    null,
    "60 days",
    "questionnaire_exact_choice_required",
  ],
  [
    "expired permit",
    {},
    (a) => {
      a.permit_expires_at = new Date(Date.now() - 1000).toISOString();
    },
    "Immediate",
    "questionnaire_action_permit_expired",
  ],
  [
    "changed step",
    {},
    (a) => {
      a.step_sha256 = "f".repeat(64);
    },
    "Immediate",
    "questionnaire_step_changed_or_consumed",
  ],
  [
    "email identity",
    { question: "Confirm your email address" },
    null,
    "Immediate",
    "questionnaire_identity_or_consent_requires_owner",
  ],
  [
    "existing owner value",
    { text: true, existing: true },
    null,
    "Fictional text",
    "questionnaire_existing_value_preserved",
  ],
  [
    "resume upload",
    { file: true },
    null,
    "Upload Resume",
    "questionnaire_resume_attachment_requires_supported_upload",
  ],
])
  test(`${name} refuses without a write`, async () => {
    const f = await fixture(options);
    try {
      const s = await f.run();
      const a = permit(s, answer);
      mutate?.(a);
      assert.equal((await f.run(a)).reason, reason);
      assert.deepEqual(f.counts(), { clicks: 0, inputEvents: 0 });
    } finally {
      f.close();
    }
  });
test("owner adoption remains fenced after the tab is hidden again", async () => {
  const f = await fixture();
  try {
    const s = await f.run();
    f.adopt();
    assert.equal(
      (await f.run(permit(s, "Immediate"))).reason,
      "owner_tab_active",
    );
    assert.equal(f.counts().clicks, 0);
  } finally {
    f.close();
  }
});
test("ambiguous provider drawers cannot be used", async () => {
  const f = await fixture({ duplicate: true });
  try {
    assert.equal((await f.run()).reason, "questionnaire_drawer_unrecognized");
    assert.equal(f.counts().clicks, 0);
  } finally {
    f.close();
  }
});

test("only the retained original document can report that its drawer closed", async () => {
  const f = await fixture();
  try {
    const step = await f.run();
    f.w.document.querySelector(".chatbot_DrawerContentWrapper").remove();
    assert.equal((await f.run()).reason, "questionnaire_drawer_unrecognized");
    assert.equal(
      (await f.run({ completion_document_id: "different-document" })).reason,
      "questionnaire_drawer_unrecognized",
    );
    const completion = { completion_document_id: step.document_id };
    assert.deepEqual(await f.run(completion), {
      kind: "questionnaire_drawer_closed",
      document_id: step.document_id,
    });
    f.adopt();
    assert.equal((await f.run(completion)).reason, "owner_tab_active");
    assert.equal(f.counts().clicks, 0);
  } finally {
    f.close();
  }
});

async function radioFixture(mode = "save") {
  const f = await fixture({
    question: "Are you willing to attend in-person interview?",
  });
  const d = f.w.document.querySelector(".chatbot_DrawerContentWrapper");
  d.querySelector(".chipsContainer").replaceChildren();
  const panel = f.w.document.createElement("div");
  panel.className = "singleselect-radiobutton";
  panel.innerHTML = `<div class="singleselect-radiobutton-container">${["Yes", "No"].map((v, i) => `<div class="ssrc__radio-btn-container"><input type="radio" id="${v}" name="radio-button" value="${v}" class="ssrc__radio" data-val="pb" data-index="${i}"><label for="${v}" class="ssrc__label">${v}</label></div>`).join("")}</div>`;
  d.querySelector(".chatbot_MessageContainer").append(panel);
  const send = d.querySelector(".send");
  send.classList.add("disabled");
  let changes = 0;
  for (const input of panel.querySelectorAll("input"))
    input.onchange = () => {
      changes++;
      if (mode === "advance")
        d.querySelector(".botMsg").textContent = "Next question?";
      else if (mode === "remove") d.remove();
      else if (mode === "save") send.classList.remove("disabled");
      else if (mode === "adopt") f.adopt();
    };
  return { ...f, panel, radioChanges: () => changes };
}
for (const mode of ["save", "advance", "remove"])
  test(`real-shaped radio ${mode} consumes one choice without a later-question Save`, async () => {
    const f = await radioFixture(mode);
    try {
      const step = await f.run();
      assert.equal(step.answer_kind, "choice");
      assert.deepEqual(step.options, ["Yes", "No"]);
      assert.equal(f.radioChanges(), 0);
      const request = permit(step, "No");
      const r = await f.run(request);
      assert.equal(r.kind, "questionnaire_answer_attempted");
      assert.equal(r.submitted, false);
      assert.equal(f.radioChanges(), 1);
      assert.equal(f.counts().clicks, mode === "save" ? 1 : 0);
      assert.notEqual(
        (await f.run(request)).kind,
        "questionnaire_answer_attempted",
      );
      assert.equal(f.radioChanges(), 1);
    } finally {
      f.close();
    }
  });
for (const [name, change, reason] of [
  [
    "selected",
    (f) => (f.panel.querySelector("input").checked = true),
    "questionnaire_existing_value_preserved",
  ],
  [
    "disabled",
    (f) => (f.panel.querySelector('input[value="No"]').disabled = true),
    "questionnaire_control_disabled",
  ],
  [
    "wrong label",
    (f) => (f.panel.querySelector("label").textContent = "Maybe"),
    "questionnaire_radio_controls_unrecognized",
  ],
  [
    "duplicate group",
    (f) => f.panel.parentElement.append(f.panel.cloneNode(true)),
    "questionnaire_radio_controls_unrecognized",
  ],
  [
    "mixed chips",
    (f) => {
      const c = f.w.document.createElement("div");
      c.className = "chatbot_Chip";
      c.textContent = "Other";
      f.w.document.querySelector(".chipsContainer").append(c);
    },
    "questionnaire_radio_controls_unrecognized",
  ],
])
  test(`radio ${name} refuses without a click`, async () => {
    const f = await radioFixture();
    try {
      const s = await f.run();
      change(f);
      const r = await f.run(permit(s, "No"));
      assert.equal(r.reason, reason);
      assert.equal(f.radioChanges(), 0);
      assert.equal(f.counts().clicks, 0);
    } finally {
      f.close();
    }
  });
for (const [mode, reason] of [
  ["no-save", "questionnaire_send_control_not_confirmed"],
  ["adopt", "owner_tab_active"],
])
  test(`radio ${mode} never repeats selection or guesses a Save`, async () => {
    const f = await radioFixture(mode);
    try {
      const s = await f.run();
      const a = permit(s, "Yes");
      assert.equal((await f.run(a)).reason, reason);
      assert.equal(f.radioChanges(), 1);
      assert.equal(f.counts().clicks, 0);
      assert.notEqual((await f.run(a)).kind, "questionnaire_answer_attempted");
      assert.equal(f.radioChanges(), 1);
    } finally {
      f.close();
    }
  });

for (const mode of ["radio", "text"])
  test(`${mode} never clicks Save after its permit expires during the input handler`, async () => {
    const f =
      mode === "radio" ? await radioFixture() : await fixture({ text: true });
    try {
      const target =
        mode === "radio"
          ? f.panel.querySelector('input[value="No"]')
          : f.w.document.querySelector(".textArea");
      target.addEventListener(mode === "radio" ? "change" : "input", () => {
        f.w.Date.now = () => Date.now() + 4000;
      });
      const s = await f.run();
      const a = permit(s, mode === "radio" ? "No" : "Fictional answer");
      assert.equal(
        (await f.run(a)).reason,
        "questionnaire_action_permit_expired",
      );
      assert.equal(f.counts().clicks, 0);
      assert.notEqual((await f.run(a)).kind, "questionnaire_answer_attempted");
      assert.equal(f.counts().clicks, 0);
    } finally {
      f.close();
    }
  });
