import test from "node:test";
import assert from "node:assert/strict";
import { installGuard, guardActive, releaseGuard } from "../network-guard.js";
function fixture() {
  let rules = [];
  let granted = true;
  return {
    rules: () => rules,
    grant: (value) => {
      granted = value;
    },
    api: {
      permissions: {
        contains: async (value) => {
          assert.deepEqual(value, { permissions: ["declarativeNetRequest"] });
          return granted;
        },
      },
      declarativeNetRequest: {
        getSessionRules: async () => structuredClone(rules),
        updateSessionRules: async ({ removeRuleIds, addRules = [] }) => {
          rules = [
            ...rules.filter((rule) => !removeRuleIds.includes(rule.id)),
            ...addRules,
          ];
        },
      },
    },
  };
}
test("guard blocks only the exact tab including main-frame navigation without inspecting URLs or bodies", async () => {
  const f = fixture();
  await installGuard(f.api, 17);
  assert.equal(await guardActive(f.api, 17), true);
  assert.equal(await guardActive(f.api, 18), false);
  assert.equal(f.rules().length, 2);
  for (const rule of f.rules()) {
    assert.deepEqual(rule.action, { type: "block" });
    assert.deepEqual(rule.condition.tabIds, [17]);
    assert.equal(rule.condition.urlFilter, undefined);
    assert.equal(rule.condition.requestMethods, undefined);
  }
  await installGuard(f.api, 17);
  assert.equal(f.rules().length, 2);
});
test("two application tabs keep independent rules; release removes only the chosen tab", async () => {
  const f = fixture();
  await installGuard(f.api, 17);
  await installGuard(f.api, 18);
  await releaseGuard(f.api, 17);
  assert.equal(await guardActive(f.api, 17), false);
  assert.equal(await guardActive(f.api, 18), true);
});
test("permission declined or removed cannot be reported as a protected fill", async () => {
  const f = fixture();
  f.grant(false);
  await assert.rejects(
    installGuard(f.api, 17),
    /network_guard_permission_required/,
  );
  assert.equal(f.rules().length, 0);
  f.grant(true);
  await installGuard(f.api, 17);
  f.grant(false);
  assert.equal(await guardActive(f.api, 17), false);
});
test("a rule installation that silently fails is rejected", async () => {
  const f = fixture();
  f.api.declarativeNetRequest.updateSessionRules = async () => {};
  await assert.rejects(installGuard(f.api, 17), /network_guard_unverified/);
});
