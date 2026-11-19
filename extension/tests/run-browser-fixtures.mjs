// Sequential, headless, temporary-profile fixtures only. No live-inspection tool.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fixtureEngine } from "./browser-fixture-engine.mjs";

const cases = [
  "unanswered-fields",
  "popup-answer",
  "assistant-popup",
  "site-forms",
  "react-forms",
  "fill-races",
  "greenhouse-preview",
  "phase52-steps",
  "phase52-combobox",
  "phase52-react",
  "phase53-naukri",
  "network-guard",
  "chrome-profiles",
  "chrome-window-recovery",
  "assistant-native",
  "assistant-stack",
  "naukri-radio",
  "naukri-history-cards",
  "naukri-profile-skills",
  "naukri-profile-readiness",
  "naukri-profile-setup",
  "naukri-maintenance",
  "naukri-retained-auto",
  "naukri-upload-probe",
  "naukri-execution",
  "naukri-queue",
];
if (process.argv.length !== 2)
  throw new Error("fixture_suite_does_not_accept_extra_commands");
const engine = fixtureEngine();
let failed = false;
for (const name of cases) {
  console.log(JSON.stringify({ fixture: name, engine, status: "RUNNING" }));
  const path = fileURLToPath(new URL(`./${name}.browser.mjs`, import.meta.url));
  const child = spawnSync(process.execPath, [path], {
    cwd: fileURLToPath(new URL("../../", import.meta.url)),
    env: process.env,
    stdio: "inherit",
  });
  if (child.error || child.signal || child.status !== 0) {
    console.log(JSON.stringify({ fixture: name, engine, status: "FAIL" }));
    failed = true;
  } else {
    console.log(JSON.stringify({ fixture: name, engine, status: "PASS" }));
  }
}
process.exitCode = failed ? 1 : 0;
