import assert from "node:assert/strict";
import test from "node:test";
import { assertReloadSafe } from "../scripts/brave_setup_policy.mjs";
const id = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const queue = { state: "STOPPED", revision: 162 };
const browser = {
  commandsEnabled: false,
  pendingQuestionnaires: 0,
  readInFlight: false,
  tabs: [
    { url: "about:blank" },
    { url: `chrome-extension://${id}/popup.html` },
  ],
};
test("owned Brave setup reload requires stopped queue, inactive execution and no original form", () => {
  assert.doesNotThrow(() => assertReloadSafe(queue, browser, id));
  for (const state of ["RUNNING", "PAUSED", null])
    assert.throws(
      () => assertReloadSafe({ ...queue, state }, browser, id),
      /stopped_queue/,
    );
  for (const revision of [0, -1, 1.5, null])
    assert.throws(
      () => assertReloadSafe({ ...queue, revision }, browser, id),
      /stopped_queue/,
    );
  for (const change of [
    { commandsEnabled: true },
    { commandsEnabled: null },
    { pendingQuestionnaires: 1 },
    { pendingQuestionnaires: null },
    { readInFlight: true },
  ])
    assert.throws(
      () => assertReloadSafe(queue, { ...browser, ...change }, id),
      /original_context/,
    );
});
test("reload never discards a portal or foreign extension tab", () => {
  for (const tabs of [
    [],
    [{ url: "https://www.naukri.com/job/fictional" }],
    [{ url: "chrome://extensions" }],
    [
      {
        url: "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/settings.html",
      },
    ],
    [{}],
  ])
    assert.throws(
      () => assertReloadSafe(queue, { ...browser, tabs }, id),
      /setup_tabs/,
    );
});
