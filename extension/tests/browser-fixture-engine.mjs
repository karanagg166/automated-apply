// Isolated, headless fixture selection. Never attach to a personal browser profile.
import { existsSync } from "node:fs";

export function fixtureExecutable(chromium) {
  const engine = process.env.AUTOMATED_APPLY_TEST_BROWSER || "chromium";
  const executable = {
    chromium: chromium.executablePath(),
    brave: "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    edge: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  }[engine];
  if (!executable || !existsSync(executable))
    throw new Error("fixture_browser_unavailable_no_fallback");
  return executable;
}
