// MV3 session rules, scoped to one exact application tab. Request contents are
// never intercepted or inspected. Rules deliberately survive worker suspension.
const firstId = 52000,
  lastId = 52999;
const owned = (rule) =>
  Number.isInteger(rule.id) && rule.id >= firstId && rule.id <= lastId;
export async function guardActive(api, tabId) {
  if (
    !Number.isInteger(tabId) ||
    !(await api.permissions.contains({
      permissions: ["declarativeNetRequest"],
    }))
  )
    return false;
  const rules = (await api.declarativeNetRequest.getSessionRules()).filter(
    (rule) =>
      owned(rule) &&
      rule.condition?.tabIds?.length === 1 &&
      rule.condition.tabIds[0] === tabId &&
      rule.action?.type === "block",
  );
  return (
    rules.some(
      (rule) =>
        !rule.condition.resourceTypes &&
        !rule.condition.excludedResourceTypes &&
        !rule.condition.urlFilter &&
        !rule.condition.requestMethods,
    ) &&
    rules.some(
      (rule) =>
        rule.condition.resourceTypes?.length === 1 &&
        rule.condition.resourceTypes[0] === "main_frame" &&
        !rule.condition.urlFilter &&
        !rule.condition.requestMethods,
    )
  );
}
export async function installGuard(api, tabId) {
  if (!Number.isInteger(tabId) || tabId < 0)
    throw Error("application_tab_required");
  if (
    !(await api.permissions.contains({
      permissions: ["declarativeNetRequest"],
    }))
  )
    throw Error("network_guard_permission_required");
  if (await guardActive(api, tabId)) return;
  const all = await api.declarativeNetRequest.getSessionRules();
  const existing = all
    .filter((rule) => owned(rule) && rule.condition?.tabIds?.includes(tabId))
    .map((rule) => rule.id);
  const used = new Set(
    all.filter((rule) => !existing.includes(rule.id)).map((rule) => rule.id),
  );
  const ids = [];
  for (let id = firstId; id <= lastId && ids.length < 2; id++)
    if (!used.has(id)) ids.push(id);
  if (ids.length !== 2) throw Error("network_guard_capacity");
  await api.declarativeNetRequest.updateSessionRules({
    removeRuleIds: existing,
    addRules: [
      {
        id: ids[0],
        priority: 1,
        action: { type: "block" },
        condition: { tabIds: [tabId] },
      },
      {
        id: ids[1],
        priority: 1,
        action: { type: "block" },
        condition: { tabIds: [tabId], resourceTypes: ["main_frame"] },
      },
    ],
  });
  if (!(await guardActive(api, tabId))) throw Error("network_guard_unverified");
}
export async function releaseGuard(api, tabId) {
  if (
    !Number.isInteger(tabId) ||
    !(await api.permissions.contains({
      permissions: ["declarativeNetRequest"],
    }))
  )
    return;
  const rules = await api.declarativeNetRequest.getSessionRules();
  const ids = rules
    .filter(
      (rule) =>
        owned(rule) &&
        rule.condition?.tabIds?.length === 1 &&
        rule.condition.tabIds[0] === tabId,
    )
    .map((rule) => rule.id);
  if (ids.length)
    await api.declarativeNetRequest.updateSessionRules({ removeRuleIds: ids });
}
