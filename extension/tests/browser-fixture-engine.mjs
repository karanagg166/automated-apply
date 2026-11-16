// Isolated, headless fixture selection. Never attach to a personal browser profile.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

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

export function fixtureNativeHost(extension) {
  const metadata = JSON.parse(
    readFileSync(join(extension, "build-info.json"), "utf8"),
  );
  const name = `com.automated_apply.${fixtureEngine()}`;
  if (
    metadata.browser !== fixtureEngine() ||
    metadata.native_host !== name ||
    metadata.extension_id !== "gdjbmkffcpicbpiikcohlmokkmcpipgp"
  )
    throw new Error("fixture_extension_browser_build_mismatch");
  return name;
}
