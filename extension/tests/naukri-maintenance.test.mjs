import assert from "node:assert/strict";
import test from "node:test";
import { guardedNaukriReload } from "../naukri-maintenance.js";

function fixture(change = {}) {
  const local = {
    connectedChromeProfileV1: {
      connected: true,
      id: "fixture-profile",
      secret: "fictional-only",
      windowId: 10,
    },
  };
  const session = { applicationBrowserSessionV1: "fixture-session" };
  let active = false;
  let reloads = 0;
  const area = (value) => ({
    get: async () => value,
    set: async (input) => Object.assign(value, input),
  });
  const url = "chrome-extension://fictional/settings.html";
  globalThis.location = { href: url };
  globalThis.document = { visibilityState: "hidden" };
  const api = {
    storage: { local: area(local), session: area(session) },
    tabs: { getCurrent: async () => ({ id: 22, windowId: 10, active }) },
    runtime: {
      getURL: () => url,
      reload: () => reloads++,
      sendNativeMessage: async (_, input) => {
        assert.equal(input.command, "naukri_queue_status");
        if (change.adoptDuringNative) active = true;
        return {
          version: 1,
          request_id: input.request_id,
          ok: true,
          data: {
            submitted: false,
            queue: { state: change.state || "STOPPED", revision: 157 },
          },
        };
      },
    },
  };
  const request = {
    requestId: "11111111-1111-4111-8111-111111111111",
    targetSha: "a".repeat(40),
    profileBindingId: "fixture-profile",
    expectedRevision: 157,
    expiresAt: new Date(Date.now() + 60000).toISOString(),
  };
  return { api, request, local, session, reloads: () => reloads };
}

test("authenticated stopped reload occurs once without tab or window actions", async () => {
  const f = fixture();
  assert.deepEqual(await guardedNaukriReload(f.request, f.api), {
    reloadRequested: true,
  });
  await assert.rejects(
    guardedNaukriReload(f.request, f.api),
    /maintenance_reload_intent_consumed/,
  );
  assert.equal(f.reloads(), 1);
});

for (const fault of [
  "running",
  "revision",
  "adopt",
  "form",
  "inflight",
  "binding",
  "expired",
]) {
  test(`reload refuses ${fault} with no reload or consumed intent`, async () => {
    const f = fixture({
      state: fault === "running" ? "RUNNING" : "STOPPED",
      adoptDuringNative: fault === "adopt",
    });
    if (fault === "revision") f.request.expectedRevision++;
    if (fault === "form")
      f.session.naukriParkedQuestionnairesV1 = {
        fixture: { form_pending: true },
      };
    if (fault === "inflight")
      f.session.naukriReadInFlightV1 = { operation: "inspect_job" };
    if (fault === "binding") f.request.profileBindingId = "different-profile";
    if (fault === "expired")
      f.request.expiresAt = new Date(Date.now() - 1).toISOString();
    await assert.rejects(guardedNaukriReload(f.request, f.api), /maintenance_/);
    assert.equal(f.reloads(), 0);
    assert.equal(f.local.naukriMaintenanceReloadV1, undefined);
  });
}
