import test from "node:test";
import assert from "node:assert/strict";
import { naukriFormUrl } from "../naukri.js";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { formDOM } from "../form-dom.js";

test("Naukri local assistance accepts a selected clean posting only", () => {
  assert.equal(
    naukriFormUrl(
      "https://www.naukri.com/job-listings-fictional-backend-281026123456",
    ),
    true,
  );
  for (const url of [
    "https://www.naukri.com/login",
    "https://www.naukri.com/mnjuser/profile",
    "https://www.naukri.com/job-listings-fictional-281026123456?token=x",
    "https://www.naukri.com/job-listings-fictional-281026123456#login",
    "https://naukri.com.attacker.example/job-listings-fictional-281026123456",
    "https://u:p@www.naukri.com/job-listings-fictional-281026123456",
    "http://www.naukri.com/job-listings-fictional-281026123456",
    "https://www.naukri.com:8443/job-listings-fictional-281026123456",
  ])
    assert.equal(naukriFormUrl(url), false, url);
});

function pageFixture(html) {
  const dom = new JSDOM(html, {
    url: "https://www.naukri.com/job-listings-fictional-291026123456",
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
  return {
    w,
    inspect: () =>
      w.eval(`(${formDOM.toString()})({operation:"inspect",only_empty:true})`),
    close: () => w.close(),
  };
}

test("Naukri global search and Apply teaser are never application fields or completed values", () => {
  const f = pageFixture(
    '<header><form role="search"><label>Location<input value="India"></label><label>Keyword<input></label><button>Search</button></form></header><h1>Backend Engineer</h1><button>Apply</button>',
  );
  try {
    const view = f.inspect();
    assert.deepEqual(Array.from(view.fields), []);
    assert.equal(view.completed_count, 0);
    assert.equal(view.has_submit, false);
    assert.equal(view.state, "manual_required");
    assert.equal(view.manual_reason, "verified_application_form_not_present");
  } finally {
    f.close();
  }
});

test("Naukri inspection separates explicit application questions from global navigation", () => {
  const f = pageFixture(
    '<div class="nI-gNb-header"><label>Location<input value="India"></label></div><div role="dialog" aria-label="Application questions"><form><label>Email<input type="email"></label><label>Phone<input value="owner-entered"></label></form></div>',
  );
  try {
    const view = f.inspect();
    assert.equal(view.fields.length, 1);
    assert.equal(view.fields[0].label, "Email");
    assert.equal(view.completed_count, 1);
  } finally {
    f.close();
  }
});

test("unverified Naukri drawer boundaries stay manual and login is never ignored", () => {
  const f = pageFixture(
    '<div class="application-drawer"><label>Email<input type="email"></label></div>',
  );
  try {
    assert.equal(f.inspect().fields.length, 0);
  } finally {
    f.close();
  }
  const login = pageFixture(
    '<header><input type="password"></header><form><label>Email<input type="email"></label></form>',
  );
  try {
    assert.equal(login.inspect().state, "login_required");
  } finally {
    login.close();
  }
});
