import assert from "node:assert/strict";
import test from "node:test";
import {
  assertSetupProfile,
  assertSetupTabs,
} from "../scripts/brave_setup_policy.mjs";
const id = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const path = "/owned/brave-extension/pinned";
const entry = { path, disable_reasons: [] };
const queue = { state: "STOPPED", revision: 162 };
test("setup requires a stopped queue and never clears browser disable decisions", () => {
  assert.doesNotThrow(() => assertSetupProfile(queue, entry, path));
  for (const state of ["RUNNING", "PAUSED", null])
    assert.throws(
      () => assertSetupProfile({ ...queue, state }, entry, path),
      /stopped_queue/,
    );
  for (const revision of [0, -1, 1.5, null])
    assert.throws(
      () => assertSetupProfile({ ...queue, revision }, entry, path),
      /stopped_queue/,
    );
  for (const disable_reasons of [[1], [2], [4], [4, 16], [256], null])
    assert.throws(
      () => assertSetupProfile(queue, { ...entry, disable_reasons }, path),
      /owner_brave_extension_enable/,
    );
  assert.throws(
    () => assertSetupProfile(queue, { ...entry, path: "/foreign" }, path),
    /install_required/,
  );
});
test("setup preserves portal and foreign extension tabs", () => {
  assert.doesNotThrow(() =>
    assertSetupTabs(
      [{ url: "about:blank" }, { url: `chrome-extension://${id}/popup.html` }],
      id,
    ),
  );
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
    assert.throws(() => assertSetupTabs(tabs, id), /original_tabs_preserved/);
});
