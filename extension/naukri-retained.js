// A settings-page continuation can load an updated adapter without invalidating
// the original extension session/document by reloading the whole extension.
// Every browser action still goes through the normal native queue admissions.
import {
  profileAlarm,
  profileContext,
  profileNative,
} from "./chrome-profile.js";
import { NaukriQueue } from "./naukri-queue.js";

let busy = false;
const permitted = new Set([
  "inspect_questionnaire",
  "refresh_questionnaire_profile",
  "refresh_questionnaire_job",
  "answer_questionnaire",
  "reconcile_application",
  "verify_account",
]);

export async function continueRetainedQuestionnaire(
  api = chrome,
  send = profileNative,
  Queue = NaukriQueue,
  identity = null,
) {
  if (busy) throw Error("retained_continuation_busy");
  busy = true;
  let alarm;
  try {
    const forms =
      (await api.storage.session.get("naukriParkedQuestionnairesV1"))
        .naukriParkedQuestionnairesV1 || {};
    const candidates = Object.values(forms).filter(
      (f) =>
        f.form_pending && !f.ownerAdopted && (!identity || f.id === identity),
    );
    if (candidates.length !== 1)
      throw Error("one_retained_questionnaire_required");
    const original = candidates[0];
    const context = await profileContext(api);
    if (
      ["profile_binding_id", "browser_session_id", "window_id"].some(
        (k) => original.binding?.[k] !== context[k],
      )
    )
      throw Error("questionnaire_original_browser_context_required");
    const tab = await api.tabs.get(original.ownedTabId);
    if (
      tab.active ||
      tab.windowId !== context.window_id ||
      tab.url !== original.url
    )
      throw Error("questionnaire_original_tab_unavailable");
    const pending = (await api.storage.session.get("naukriReadInFlightV1"))
      .naukriReadInFlightV1;
    if (pending) throw Error("background_operation_in_flight");
    const queue = new Queue(api, async (client, command, extra) => {
      if (command !== "poll_naukri_work" && extra.work_id !== original.id)
        throw Error("retained_work_context_changed");
      const result = await send(client, command, extra);
      if (
        command === "poll_naukri_work" &&
        result.work &&
        (result.work.id !== original.id ||
          !permitted.has(result.work.operation))
      ) {
        const work = result.work;
        // Poll leases a read; release it without navigating or admitting it.
        await send(client, "abandon_naukri_work", {
          ...context,
          work_id: work.id,
          expected_work_revision: work.revision,
          work_lease_token: work.lease_token,
          tab_id: work.binding.tab_id,
          work_report: {
            kind: "needs_input",
            reason: "retained_continuation_only",
          },
        });
        return { ...result, work: null };
      }
      return result;
    });
    if (await queue.ownerUsingNaukri()) throw Error("owner_using_naukri");
    alarm = await api.alarms.get(profileAlarm);
    await api.alarms.clear(profileAlarm);
    await queue.tick();
  } finally {
    if (alarm)
      await api.alarms.create(profileAlarm, {
        periodInMinutes: alarm.periodInMinutes || 0.5,
      });
    busy = false;
  }
}
