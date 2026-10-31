import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { sortNaukriSearchDate } from "../naukri-queue.js";
const url = "https://www.naukri.com/backend-developer-jobs";
async function sort(options = {}) {
  const expectedUrl = options.page ? url + "-" + options.page : url;
  const dom = new JSDOM(
    `<button id="filter-sort" type="button" aria-controls="filter-sort-menu">${options.sorted ? "Date" : "Recommended"}</button><ul id="filter-sort-menu" style="visibility:hidden"><li role="option" title="Date"><a${options.href ? ` href="${options.href}"` : ""}>Date</a></li></ul><a href="/job-listings-fictional-311026123456">Fictional job</a>`,
    { url: options.actual || expectedUrl, runScripts: "outside-only" },
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
    selected = 0,
    advanced = 0;
  const showPage = (page) => {
    let nav = w.document.querySelector('nav[aria-label="Pagination"]');
    if (!nav) {
      nav = w.document.createElement("nav");
      nav.setAttribute("aria-label", "Pagination");
      w.document.body.append(nav);
    }
    const path = new URL(url).pathname;
    const currentPath = path + (page > 1 ? "-" + page : "");
    nav.innerHTML = `<a href="${currentPath}" aria-current="page">${page}</a><a href="${options.nextDestination || path + "-" + (page + 1)}"${options.newWindow ? ' target="_blank"' : ""}>Next</a>`;
    nav.lastElementChild.onclick = (e) => {
      e.preventDefault();
      advanced++;
      w.history.replaceState(null, "", path + "-" + (page + 1));
      showPage(page + 1);
      if (!options.staleCards)
        w.document.querySelector('a[href*="job-listings-"]').href =
          `/job-listings-page-${page + 1}-31102612345${page + 1}`;
      if (options.adoptNext) {
        visibility = "visible";
        w.document.dispatchEvent(new w.Event("visibilitychange"));
        visibility = "hidden";
        w.document.dispatchEvent(new w.Event("visibilitychange"));
      }
    };
  };
  if (options.page) showPage(options.page);
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
    if (options.page) {
      w.history.replaceState(null, "", new URL(url).pathname);
      showPage(1);
    }
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
            `(${sortNaukriSearchDate.toString()})(${JSON.stringify(expectedUrl)})`,
          ),
        ),
      ),
      opened,
      selected,
      ...(options.page ? { advanced } : {}),
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
for (const page of [2, 3]) {
  test(`Date resets to page one, then ordinary Next retains Date through page ${page}`, async () => {
    const r = await sort({ page });
    assert.equal(r.report.kind, "date_sort");
    assert.equal(r.report.state, "selected");
    assert.equal(r.selected, 1);
    assert.equal(r.advanced, page - 1);
  });
}
test("an already Date-sorted page two requires no click", async () => {
  const r = await sort({ page: 2, sorted: true });
  assert.equal(r.report.kind, "date_sort");
  assert.equal(r.advanced + r.selected + r.opened, 0);
});
for (const options of [
  { nextDestination: "https://example.org/backend-developer-jobs-2" },
  { nextDestination: "/backend-developer-jobs-2?redirect=1" },
  { newWindow: true },
]) {
  test(`unsupported Next destination is not clicked: ${JSON.stringify(options)}`, async () => {
    const r = await sort({ page: 2, ...options });
    assert.equal(r.report.reason, "search_next_page_control_unsupported");
    assert.equal(r.advanced, 0);
  });
}
test("unchanged cards cannot confirm a new page", async () => {
  const r = await sort({ page: 2, staleCards: true });
  assert.equal(r.report.kind, "needs_input");
  assert.equal(r.advanced, 1);
});
test("owner adoption during Next remains fenced after hiding the tab again", async () => {
  const r = await sort({ page: 2, adoptNext: true });
  assert.equal(r.report.reason, "owner_tab_active");
  assert.equal(r.advanced, 1);
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
