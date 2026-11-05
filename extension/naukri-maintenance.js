import { profileContext, profileNative } from "./chrome-profile.js";

const intentKey = "naukriMaintenanceReloadV1";

// Operator maintenance in an existing owned inactive settings document only.
// No tabs/windows are opened, selected or navigated by this function.
export async function guardedNaukriReload(request, api = chrome) {
  const valid = () => {
    const remaining = Date.parse(request.expiresAt) - Date.now();
    if (
      !/^[a-f0-9-]{36}$/.test(request.requestId || "") ||
      !/^[a-f0-9]{40}$/.test(request.targetSha || "") ||
      !Number.isInteger(request.expectedRevision) ||
      request.expectedRevision < 1 ||
      !(remaining > 0 && remaining <= 120000) ||
      location.href !== api.runtime.getURL("settings.html") ||
      document.visibilityState !== "hidden"
    )
      throw Error("maintenance_context_invalid");
  };
  valid();
  const original = await profileContext(api);
  const tab = await api.tabs.getCurrent();
  const current = async () => {
    valid();
    const now = await profileContext(api);
    const owned = await api.tabs.getCurrent();
    const setup = (await api.storage.session.get("naukriProfileSetupTabV1"))
      .naukriProfileSetupTabV1;
    if (
      original.profile_binding_id !== request.profileBindingId ||
      now.profile_binding_id !== original.profile_binding_id ||
      now.browser_session_id !== original.browser_session_id ||
      now.window_id !== original.window_id ||
      !Number.isInteger(tab?.id) ||
      owned?.id !== tab.id ||
      owned.active ||
      owned.windowId !== original.window_id ||
      setup?.status !== "opened" ||
      setup.tab_id !== tab.id ||
      setup.ownerAdopted !== false ||
      setup.profile_binding_id !== original.profile_binding_id ||
      setup.browser_session_id !== original.browser_session_id ||
      setup.window_id !== original.window_id
    )
      throw Error("maintenance_owner_or_binding_changed");
  };
  await current();
  const { queue } = await profileNative(api, "naukri_queue_status", original);
  if (queue?.state !== "STOPPED" || queue.revision !== request.expectedRevision)
    throw Error("maintenance_stopped_queue_required");
  const saved = await api.storage.session.get([
    "naukriParkedQuestionnairesV1",
    "naukriReadInFlightV1",
  ]);
  if (
    Object.keys(saved.naukriParkedQuestionnairesV1 || {}).length ||
    saved.naukriReadInFlightV1
  )
    throw Error("maintenance_original_context_pending");
  const requestKey = intentKey + ":" + request.requestId;
  const previous = (await api.storage.local.get(requestKey))[requestKey];
  if (previous?.requestId === request.requestId)
    throw Error("maintenance_reload_intent_consumed");
  await current();
  // Consume before dispatch: an uncertain reload response is never replayed.
  const intent = { ...request, consumedAt: new Date().toISOString() };
  await api.storage.local.set({ [intentKey]: intent, [requestKey]: intent });
  await current();
  api.runtime.reload();
  return { reloadRequested: true };
}
