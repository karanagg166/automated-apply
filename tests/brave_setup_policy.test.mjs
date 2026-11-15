import assert from "node:assert/strict";
import test from "node:test";
import {
  assertSetupProfile,
  assertSetupTabs,
  inactiveNaukriLoginPlan,
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
test("login preparation requires an existing neutral window and never plans a window launch", () => {
  const windows = [{ id: 7, type: "normal", incognito: false }];
  const tabs = [{ id: 9, windowId: 7, active: true, url: "about:blank" }];
  assert.deepEqual(inactiveNaukriLoginPlan(windows, tabs), {
    windowId: 7,
    url: "https://www.naukri.com/nlogin/login",
    active: false,
  });
  assert.throws(
    () => inactiveNaukriLoginPlan([], []),
    /owner_brave_window_required/,
  );
  assert.throws(
    () =>
      inactiveNaukriLoginPlan(windows, [
        { ...tabs[0], pendingUrl: "https://owner.example/" },
      ]),
    /neutral_window_required/,
  );
  assert.throws(
    () =>
      inactiveNaukriLoginPlan(windows, [
        { ...tabs[0], pendingUrl: "https://www.naukri.com/nlogin/login" },
      ]),
    /existing_naukri_tab_preserved/,
  );
  for (const url of [
    "https://owner.example/",
    "brave://extensions",
    "chrome://extensions",
    undefined,
  ])
    assert.throws(
      () => inactiveNaukriLoginPlan(windows, [{ ...tabs[0], url }]),
      /neutral_window_required/,
    );
});
test("login preparation preserves existing portal work and refuses incognito or ambiguous windows", () => {
  const window = { id: 7, type: "normal", incognito: false };
  const tab = { id: 9, windowId: 7, active: true, url: "about:blank" };
  for (const url of [
    "https://www.naukri.com/nlogin/login",
    "https://naukri.com/",
    "https://login.naukri.com/unknown",
  ])
    assert.throws(
      () =>
        inactiveNaukriLoginPlan(
          [window],
          [tab, { id: 10, windowId: 7, active: false, url }],
        ),
      /existing_naukri_tab_preserved/,
    );
  assert.throws(
    () => inactiveNaukriLoginPlan([{ ...window, incognito: true }], [tab]),
    /neutral_window_required/,
  );
  assert.throws(
    () =>
      inactiveNaukriLoginPlan(
        [window, { ...window, id: 8 }],
        [tab, { ...tab, id: 11, windowId: 8 }],
      ),
    /neutral_window_required/,
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
