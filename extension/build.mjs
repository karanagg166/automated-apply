import { readFileSync, cpSync, mkdirSync } from "node:fs";
import assert from "node:assert/strict";
const manifest = JSON.parse(readFileSync(new URL("manifest.json", import.meta.url)));
assert.equal(manifest.manifest_version, 3);
assert.deepEqual(new Set(manifest.permissions), new Set(["contextMenus", "activeTab", "nativeMessaging", "storage", "scripting"]));
assert.equal(manifest.host_permissions, undefined);
assert.equal(manifest.content_scripts, undefined);
assert.equal(manifest.externally_connectable, undefined);
mkdirSync(new URL("dist/", import.meta.url), { recursive: true });
for (const file of ["manifest.json", "background.js", "popup.html", "popup.js", "settings.html", "settings.js", "style.css"]) {
  cpSync(new URL(file, import.meta.url), new URL(`dist/${file}`, import.meta.url));
}
console.log("MV3 extension built; gesture-only isolated observation; no persistent host permissions or content scripts.");
