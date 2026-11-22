// Isolated, headless fixture selection. Never attach to a personal browser profile.
import { randomUUID } from "node:crypto";
import {
  cpSync,
  existsSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

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

export function fixtureBundle() {
  const directory = fixtureEngine() === "edge" ? "dist-edge" : "dist";
  return fileURLToPath(new URL(`../${directory}`, import.meta.url));
}

export async function enableFixtureExtensionDeveloperMode(context) {
  const page = await context.newPage();
  try {
    await page.goto("chrome://extensions/");
    const enabled = await page.evaluate(async () => {
      const settings = chrome.developerPrivate;
      await settings.updateProfileConfiguration({ inDeveloperMode: true });
      return (await settings.getProfileConfiguration()).inDeveloperMode;
    });
    if (!enabled) throw new Error("fixture_extension_developer_mode_unavailable");
  } finally {
    await page.close();
  }
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

export function copyNativeFixtureExtension(source, destination) {
  const configuredHost = fixtureNativeHost(source);
  const fixtureHost = `com.automated_apply.fixture_${randomUUID().replaceAll("-", "")}`;
  cpSync(source, destination, {
    recursive: true,
    force: false,
    errorOnExist: true,
  });
  for (const file of readdirSync(destination)) {
    if (!/\.(?:js|html)$/.test(file)) continue;
    const path = join(destination, file);
    const contents = readFileSync(path, "utf8");
    if (contents.includes(configuredHost))
      writeFileSync(path, contents.replaceAll(configuredHost, fixtureHost));
  }
  return fixtureHost;
}

export function nativeFixtureRegistry(profile, environment = process.env) {
  if (process.platform === "darwin" && fixtureEngine() === "brave") {
    // Brave resolves the macOS Application Support directory independently of
    // --user-data-dir. Give this child process its own Foundation home.
    const fixtureHome = join(profile, "fixture-home");
    return {
      directory: join(
        fixtureHome,
        "Library",
        "Application Support",
        "Google",
        "Chrome",
        "NativeMessagingHosts",
      ),
      env: { ...environment, CFFIXED_USER_HOME: fixtureHome },
    };
  }
  return { directory: join(profile, "NativeMessagingHosts"), env: environment };
}
