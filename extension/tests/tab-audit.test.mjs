import test from "node:test";
import assert from "node:assert/strict";
import { auditTab } from "../tab-audit.js";
function fixture(audit) {
  const data = { tabLifecycleAudit: audit };
  return { storage: { session: {
    async get() { return data; },
    async set(value) { Object.assign(data, value); },
  }}, data };
}
test("tab audit is disabled by default and cannot run beyond ten minutes", async () => {
  for (const config of [undefined, { until: Date.now() - 1, salt: "test" },
    { until: Date.now() + 700000, salt: "test" }]) {
    const api = fixture(config);
    await auditTab(api, "created", { id: 7, url: "https://private.example/secret" });
    assert.equal(api.data.tabLifecycleAudit, config);
  }
});
test("tab audit hashes identifiers/origins, bounds storage and leaves external sources unattributed", async () => {
  const api = fixture({ until: Date.now() + 10000, salt: "fixture", events: Array(512).fill({ event: "fixture" }) });
  await Promise.all([
    auditTab(api, "created", { id: 7, windowId: 9, url: "https://private.example/secret?token=private" }),
    auditTab(api, "created_result", { id: 7, windowId: 9 }, "automated_apply"),
  ]);
  const audit = api.data.tabLifecycleAudit;
  assert.equal(audit.events.length, 512);
  assert.equal(audit.truncated, true);
  const [observed, own] = audit.events.slice(-2);
  assert.equal(observed.source, "unattributed");
  assert.equal(own.source, "automated_apply");
  assert.equal(observed.tab, own.tab);
  assert.equal(observed.origin.length, 64);
  assert.doesNotMatch(JSON.stringify(audit), /private|secret|token/);
});
