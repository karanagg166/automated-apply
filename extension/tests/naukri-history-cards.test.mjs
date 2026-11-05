import test from "node:test";
import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { executeNaukri } from "../naukri-execution.js";

const id = "291026123456",
  url = "https://www.naukri.com/myapply/historypage";
const email = "verified@fictional.example";
const digest = createHash("sha256").update(email).digest("hex");
function fixture(change = {}) {
  const card = `<div class="ot__jdTupleContainer jdTupleContainer select"${change.hidden ? " hidden" : ""}><div class="jdTitle">${change.title || "Backend Developer"}</div><div class="subheading"><span class="company">${change.company || "Fictional Employer"}</span></div><section class="apply-status ${change.negative ? "red-text" : "green-text"}"><span class="title">${change.status || "Application sent 5 days ago"}</span></section><div class="mock-interview-prep"><a class="mip__mock" href="/mock-interview-questions/test?flowType=${change.badFlowType ? "Role" : "JD"}&flowId=${change.conflict ? "291026999999" : id}">Mock</a>${change.missing ? "" : `<a class="mip__qa" href="${change.foreign ? "https://foreign.invalid" : ""}/ai-interview-questions/question-bank?jobId=${id}${change.duplicateParam ? "&jobId=" + id : ""}">Q&A</a>`}</div></div>`;
  const legacy = `<article><a href="https://www.naukri.com/job-listings-fictional-${id}">Backend Developer</a><span class="company">Fictional Employer</span><span>Application Sent</span></article>`;
  const dom = new JSDOM(
    `<header><span class="email">${change.account || email}</span></header>${change.legacy ? legacy : `<div class="jdTuplesContainer">${card}${change.duplicate ? card : ""}</div>`}`,
    { url, runScripts: "outside-only" },
  );
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder;
  Object.defineProperty(w.document, "visibilityState", {
    value: change.active ? "visible" : "hidden",
  });
  Object.defineProperty(w.document.body, "innerText", {
    get() {
      return this.textContent;
    },
  });
  w.Element.prototype.getClientRects = function () {
    return this.closest("[hidden]") ? [] : [1];
  };
  let clicks = 0,
    opens = 0;
  w.document.addEventListener("click", () => clicks++);
  w.open = () => {
    opens++;
  };
  return {
    close: () => w.close(),
    counts: () => ({ clicks, opens }),
    run: async () =>
      JSON.parse(
        JSON.stringify(
          await w.eval(
            `(${executeNaukri.toString()})(${JSON.stringify({ id: "fictional-work", operation: "reconcile_application", url, requisition: change.req || id, execution: { expected_account_sha256: digest, expected_title: "Backend Developer", expected_company: "Fictional Employer" } })})`,
          ),
        ),
      ),
  };
}
for (const change of [
  {},
  { legacy: true },
  { status: "Application sent just now" },
  { status: "Application sent today" },
])
  test(`recognized ${JSON.stringify(change)} history produces a read-only observation`, async () => {
    const f = fixture(change);
    try {
      const v = await f.run();
      assert.equal(v.execution?.state, "APPLICATION_SENT");
      assert.equal(v.requisition, id);
      assert.match(v.execution.evidence_sha256, /^[a-f0-9]{64}$/);
      assert.deepEqual(f.counts(), { clicks: 0, opens: 0 });
    } finally {
      f.close();
    }
  });
for (const change of [
  { req: "291026999999" },
  { title: "Different role" },
  { company: "Different employer" },
  { conflict: true },
  { missing: true },
  { duplicate: true },
  { foreign: true },
  { duplicateParam: true },
  { negative: true },
  { status: "Application sent unsuccessful" },
  { status: "Application pending" },
  { hidden: true },
  { account: "different@fictional.example" },
  { active: true },
  { badFlowType: true },
])
  test(`history refuses ${JSON.stringify(change)} without a click`, async () => {
    const f = fixture(change);
    try {
      const v = await f.run();
      assert.equal(v.kind, "needs_input");
      assert.equal(v.execution, undefined);
      assert.deepEqual(f.counts(), { clicks: 0, opens: 0 });
    } finally {
      f.close();
    }
  });
test("modern history evidence includes the actual provider status text", async () => {
  const a = fixture(),
    b = fixture({ status: "Application sent today" });
  try {
    const x = await a.run(),
      y = await b.run();
    assert.notEqual(x.execution.evidence_sha256, y.execution.evidence_sha256);
  } finally {
    a.close();
    b.close();
  }
});
