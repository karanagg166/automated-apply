// Isolated, headless fixture browser selection for Playwright configs and scripts.
// Never attaches to a personal browser profile and never falls back to Chrome.
// (Moved from the retired extension/tests/ on 2026-11-26; only the engine helpers remain.)
import { existsSync } from "node:fs";

export function fixtureEngine() {
  const engine = process.env.AUTOMATED_APPLY_TEST_BROWSER || "brave";
  if (!["brave", "edge"].includes(engine))
    throw new Error("fixture_browser_denied_no_chrome_fallback");
  return engine;
}

export function fixtureExecutable(_chromium = null) {
  const engine = fixtureEngine();
  const executable = {
    brave: "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    edge: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  }[engine];
  if (!executable || !existsSync(executable))
    throw new Error("fixture_browser_unavailable_no_fallback");
  return executable;
}
