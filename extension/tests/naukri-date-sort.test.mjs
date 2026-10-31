import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { sortNaukriSearchDate } from "../naukri-queue.js";
const url = "https://www.naukri.com/backend-developer-jobs";
async function sort(options = {}) {
  const dom = new JSDOM(
    `<button id="filter-sort" type="button" aria-controls="filter-sort-menu">${options.sorted ? "Date" : "Recommended"}</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a${options.href ? ` href="${options.href}"` : ""}>Date</a></li></ul><a href="/job-listings-fictional-311026123456">Fictional job</a>`,
    { url: options.actual || url, runScripts: "outside-only" },
  );
  const w = dom.window;
  let visibility = options.active ? "visible" : "hidden";
  Object.defineProperty(w.document, "visibilityState", {
    get: () => visibility,
  });
  Object.defineProperty(w.document.body, "innerText", {
    get() {
      return options.challenge ? "Access denied" : this.textContent;
    },
  });
  w.Element.prototype.getClientRects = function () {
    return [1];
  };
  w.setTimeout = (fn) => setTimeout(fn, 0);
  let opened = 0,
    selected = 0;
  const control = w.document.querySelector("#filter-sort");
  const menu = w.document.querySelector("#filter-sort-menu");
  control.onclick = () => {
    opened++;
    menu.style.visibility = "visible";
    if (options.adopt || options.adoptThenHide) {
      visibility = "visible";
      w.document.dispatchEvent(new w.Event("visibilitychange"));
      if (options.adoptThenHide) {
        visibility = "hidden";
        w.document.dispatchEvent(new w.Event("visibilitychange"));
      }
    }
  };
  menu.querySelector("a").onclick = (e) => {
    e.preventDefault();
    selected++;
    if (!options.unconfirmed) control.textContent = "Date";
  };
  if (options.duplicate) menu.append(menu.firstElementChild.cloneNode(true));
  if (options.missing) control.remove();
  if (options.formButton) control.type = "submit";
  if (options.noResults) w.document.body.textContent = "No jobs found";
  try {
    return {
      report: JSON.parse(
        JSON.stringify(
          await w.eval(
            `(${sortNaukriSearchDate.toString()})(${JSON.stringify(url)})`,
          ),
        ),
      ),
      opened,
      selected,
    };
  } finally {
    w.close();
  }
}
test("selects the observed ordinary Date option once and confirms the SPA label", async () => {
  const result = await sort();
  assert.deepEqual(result, {
    report: { kind: "date_sort", state: "selected" },
    opened: 1,
    selected: 1,
  });
});
test("an already Date-sorted search is left alone", async () => {
  const r = await sort({ sorted: true });
  assert.equal(r.report.state, "selected");
  assert.equal(r.opened + r.selected, 0);
});
for (const [name, options, reason] of [
  ["active owner tab", { active: true }, "owner_tab_active"],
  ["owner activates during menu opening", { adopt: true }, "owner_tab_active"],
  [
    "owner activates then hides the tab",
    { adoptThenHide: true },
    "owner_tab_active",
  ],
  [
    "unexpected form submit control",
    { formButton: true },
    "search_sort_control_unrecognized",
  ],
  [
    "provider access restriction",
    { challenge: true },
    "provider_challenge_requires_owner",
  ],
  [
    "navigation changed",
    { actual: "https://www.naukri.com/other-jobs" },
    "provider_context_changed",
  ],
  [
    "duplicate Date options",
    { duplicate: true },
    "search_date_option_ambiguous",
  ],
  [
    "external Date destination",
    { href: "https://example.com/" },
    "search_date_option_unsupported",
  ],
  [
    "script Date destination",
    { href: "javascript:alert(1)" },
    "search_date_option_unsupported",
  ],
  [
    "missing sort layout",
    { missing: true },
    "search_sort_control_unrecognized",
  ],
])
  test(name + " refuses without selecting Date", async () => {
    const r = await sort(options);
    assert.equal(r.report.reason, reason);
    assert.equal(r.selected, 0);
  });
test("unconfirmed sorting is bounded and never repeats a click", async () => {
  const r = await sort({ unconfirmed: true });
  assert.equal(r.report.reason, "search_date_sort_not_confirmed");
  assert.equal(r.opened, 1);
  assert.equal(r.selected, 1);
});
test("genuine no-results text needs no sort control", async () => {
  const r = await sort({ noResults: true });
  assert.equal(r.report.state, "no_results");
  assert.equal(r.opened + r.selected, 0);
});
