// Owner-invoked interactive setup only. The agent must not run this to change foreground focus.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, lstatSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../", import.meta.url));
const profile = join(root, ".local/browser-profiles/brave-automation");
assert(existsSync(profile), "owned_brave_profile_required");
let locked = false;
try {
  lstatSync(join(profile, "SingletonLock"));
  locked = true;
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
assert(!locked, "close_owned_brave_profile_before_setup");
const release = JSON.parse(
  readFileSync(
    join(root, ".local/runtime-support/brave-extension-current.json"),
  ),
);
const extension = resolve(release.extension_path);
assert(
  extension.startsWith(join(root, ".local/runtime-support/brave-extension/")),
  "owned_brave_release_required",
);
const result = spawnSync(
  "/usr/bin/open",
  [
    "-na",
    "/Applications/Brave Browser.app",
    "--args",
    `--user-data-dir=${profile}`,
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "about:blank",
  ],
  { stdio: "ignore", timeout: 10000 },
);
assert.equal(result.status, 0, "owner_brave_launch_failed");
console.log(
  "In this Brave window, open chrome-extension://gdjbmkffcpicbpiikcohlmokkmcpipgp/settings.html and click ‘Allow Naukri background page access’. Sign in to Naukri normally, leave queue commands disabled, then close this Brave window and report that setup is done.",
);
