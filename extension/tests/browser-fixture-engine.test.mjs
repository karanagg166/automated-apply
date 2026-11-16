import assert from "node:assert/strict";
import { test } from "node:test";
import { fixtureEngine } from "./browser-fixture-engine.mjs";

test("fixture defaults to Brave and Chrome cannot become an implicit fallback", () => {
  const saved = process.env.AUTOMATED_APPLY_TEST_BROWSER;
  try {
    delete process.env.AUTOMATED_APPLY_TEST_BROWSER;
    assert.equal(fixtureEngine(), "brave");
    process.env.AUTOMATED_APPLY_TEST_BROWSER = "edge";
    assert.equal(fixtureEngine(), "edge");
    for (const value of ["chrome", "chromium", "safari", "arbitrary-browser"]) {
      process.env.AUTOMATED_APPLY_TEST_BROWSER = value;
      assert.throws(fixtureEngine, /fixture_browser_denied_no_chrome_fallback/);
    }
  } finally {
    if (saved === undefined) delete process.env.AUTOMATED_APPLY_TEST_BROWSER;
    else process.env.AUTOMATED_APPLY_TEST_BROWSER = saved;
  }
});
