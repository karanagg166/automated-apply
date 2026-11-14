import { readFileSync, writeFileSync, cpSync, mkdirSync } from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
const arguments_ = process.argv.slice(2);
assert(arguments_.length <= 1, "One explicit browser target is permitted");
const browser = arguments_[0]?.replace(/^--browser=/, "") || "chrome";
assert(
  ["chrome", "brave", "edge"].includes(browser),
  "Unsupported browser target",
);
assert(
  !arguments_.length || arguments_[0] === `--browser=${browser}`,
  "Explicit browser flag required",
);
const nativeHost =
  browser === "chrome"
    ? "com.automated_apply.agent"
    : `com.automated_apply.${browser}`;
const manifest = JSON.parse(
  readFileSync(new URL("manifest.json", import.meta.url)),
);
assert.equal(manifest.manifest_version, 3);
assert.deepEqual(
  new Set(manifest.permissions),
  new Set([
    "contextMenus",
    "activeTab",
    "nativeMessaging",
    "storage",
    "scripting",
    "declarativeNetRequest",
    "alarms",
    "background",
  ]),
);
assert.equal(manifest.host_permissions, undefined);
assert.equal(manifest.optional_permissions, undefined);
assert.deepEqual(manifest.optional_host_permissions, ["https://*/*"]);
assert.equal(manifest.content_scripts, undefined);
assert.equal(manifest.externally_connectable, undefined);
assert.ok(
  manifest.key,
  "A committed public manifest key is required for stable installation identity.",
);
const hash = createHash("sha256")
  .update(Buffer.from(manifest.key, "base64"))
  .digest("hex")
  .slice(0, 32);
const id = [...hash]
  .map((c) => String.fromCharCode(97 + Number.parseInt(c, 16)))
  .join("");
mkdirSync(new URL("dist/", import.meta.url), { recursive: true });
for (const file of [
  "manifest.json",
  "form-dom.js",
  "naukri.js",
  "naukri-observation.js",
  "naukri-queue.js",
  "naukri-chatbot.js",
  "naukri-retained.js",
  "naukri-maintenance.js",
  "naukri-execution.js",
  "naukri-profile-skills.js",
  "naukri-resume-download.js",
  "form-bridge.js",
  "form-messages.js",
  "background.js",
  "tab-audit.js",
  "task-coordinator.js",
  "chrome-profile.js",
  "network-guard.js",
  "preview.js",
  "session-indicator.js",
  "observation.js",
  "popup.html",
  "popup.js",
  "settings.html",
  "settings.js",
  "style.css",
]) {
  cpSync(
    new URL(file, import.meta.url),
    new URL(`dist/${file}`, import.meta.url),
  );
  // Brave deliberately searches Chrome's native-host registry on macOS. Use a
  // browser-specific fixed name so installing Brave never enables the disabled
  // Chrome host. Only these application-owned literals differ between bundles.
  if (browser !== "chrome" && /\.(?:js|html)$/.test(file)) {
    const target = new URL(`dist/${file}`, import.meta.url);
    const text = readFileSync(target, "utf8");
    writeFileSync(
      target,
      text.replaceAll("com.automated_apply.agent", nativeHost),
    );
  }
}
writeFileSync(
  new URL("dist/build-info.json", import.meta.url),
  JSON.stringify(
    {
      browser,
      native_host: nativeHost,
      extension_id: id,
      version: manifest.version,
    },
    null,
    2,
  ) + "\n",
);
console.log(
  `MV3 extension built for ${browser}; stable ID ${id}; host ${nativeHost}; optional per-origin access and guarded application filling.`,
);
