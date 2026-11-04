// A settings-page continuation can load an updated adapter without invalidating
// the original extension session/document by reloading the whole extension.
// Every browser action still goes through the normal native queue admissions.
import {
  profileAlarm,
  profileContext,
  profileNative,
} from "./chrome-profile.js";
import { NaukriQueue } from "./naukri-queue.js";
import { naukriChatbot } from "./naukri-chatbot.js";

let busy = false;
let heldHeartbeat = null;

// A fresh trusted settings module can continue an existing form while the
// cached worker uses an older parser. Keep that worker's queue alarm suspended;
// ordinary connection-status requests still provide authenticated heartbeats.
export async function configureRetainedHeartbeat(
  api = chrome,
  identity = null,
) {
  if (!identity) {
    if (heldHeartbeat) {
      await api.alarms.create(profileAlarm, {
        periodInMinutes: heldHeartbeat.periodInMinutes,
      });
      heldHeartbeat = null;
    }
    return { held: false };
  }
  const context = await profileContext(api);
  const forms =
    (await api.storage.session.get("naukriParkedQuestionnairesV1"))
      .naukriParkedQuestionnairesV1 || {};
  const form = forms[identity];
  if (
    !form?.form_pending ||
    form.ownerAdopted ||
    (heldHeartbeat && heldHeartbeat.identity !== identity) ||
    ["profile_binding_id", "browser_session_id", "window_id"].some(
      (k) => form.binding?.[k] !== context[k],
    )
  )
    throw Error("retained_work_context_changed");
  const tab = await api.tabs.get(form.ownedTabId);
  if (tab.active || tab.windowId !== context.window_id || tab.url !== form.url)
    throw Error("questionnaire_original_tab_unavailable");
  if (!heldHeartbeat) {
    const alarm = await api.alarms.get(profileAlarm);
    heldHeartbeat = {
      identity,
      periodInMinutes: alarm?.periodInMinutes || 0.5,
    };
  }
  await api.alarms.clear(profileAlarm);
  return { held: true };
}
const permitted = new Set([
  "inspect_questionnaire",
  "refresh_questionnaire_profile",
  "refresh_questionnaire_job",
  "answer_questionnaire",
  "reconcile_application",
  "verify_account",
]);

// Read-only recovery of the exact first unanswered form. The backend must
// separately accept this observation against its durable original-tab ledger.
// This grants no browser write and never creates/navigates a provider tab.
export async function inspectUnansweredRetainedForm(envelope, api = chrome) {
  const context = await profileContext(api);
  if (
    !/^[a-f0-9-]{36}$/.test(envelope.id || "") ||
    !/^[0-9]{10,20}$/.test(envelope.requisition || "") ||
    new URL(envelope.url).origin !== "https://www.naukri.com" ||
    !new URL(envelope.url).pathname.endsWith("-" + envelope.requisition) ||
    ["profile_binding_id", "window_id"].some(
      (k) => envelope.original_binding?.[k] !== context[k],
    )
  )
    throw Error("retained_recovery_context_changed");
  const id = envelope.original_binding.tab_id;
  const tab = await api.tabs.get(id);
  if (
    tab.active ||
    tab.windowId !== context.window_id ||
    tab.url !== envelope.url
  )
    throw Error("questionnaire_original_tab_unavailable");
  const observed = (
    await api.scripting.executeScript({
      target: { tabId: id, frameIds: [0] },
      world: "ISOLATED",
      func: naukriChatbot,
      args: [
        {
          operation: "inspect",
          url: envelope.url,
          requisition: envelope.requisition,
        },
      ],
    })
  )[0]?.result;
  if (
    observed?.kind !== "questionnaire" ||
    observed.question !== envelope.question
  )
    throw Error("retained_original_question_changed");
  const empty = (
    await api.scripting.executeScript({
      target: { tabId: id, frameIds: [0] },
      world: "ISOLATED",
      func: () => {
        const visible = (e) =>
          e.getClientRects().length &&
          getComputedStyle(e).visibility !== "hidden";
        const drawers = [
          ...document.querySelectorAll(".chatbot_DrawerContentWrapper"),
        ].filter(visible);
        if (document.visibilityState !== "hidden" || drawers.length !== 1)
          return false;
        const drawer = drawers[0];
        const editors = [
          ...drawer.querySelectorAll('.textArea[contenteditable="true"]'),
        ].filter(visible);
        const panels = [
          ...drawer.querySelectorAll(".singleselect-radiobutton"),
        ].filter(visible);
        const radios =
          panels.length === 1
            ? [...panels[0].querySelectorAll('input.ssrc__radio[type="radio"]')]
            : [];
        const emptyControl =
          (editors.length === 1 &&
            !editors[0].textContent.trim() &&
            !panels.length) ||
          (editors.length === 0 &&
            panels.length === 1 &&
            radios.length > 0 &&
            radios.every((e) => !e.checked && !e.disabled));
        return (
          emptyControl &&
          [...drawer.querySelectorAll(".botItem .botMsg")].filter(visible)
            .length === 2 &&
          ![...drawer.querySelectorAll(".userItem,.userMsg")].some(visible)
        );
      },
    })
  )[0]?.result;
  if (!empty) throw Error("retained_form_has_answer_or_unknown_progress");
  let applyDocument;
  if (envelope.apply_document_id) {
    applyDocument = (
      await api.scripting.executeScript({
        target: { tabId: id, frameIds: [0] },
        world: "ISOLATED",
        func: () => {
          const s = globalThis.__automatedApplyNaukriExecutionV1;
          return document.visibilityState === "hidden" &&
            s?.used === true &&
            !s.adopted
            ? s.documentId
            : null;
        },
      })
    )[0]?.result;
    if (
      applyDocument !== envelope.apply_document_id ||
      observed.answer_kind !== "choice"
    )
      throw Error("retained_original_apply_document_required");
  }
  const binding = { ...context, tab_id: id };
  delete binding.profile_secret;
  const proof = {
    work_id: envelope.id,
    url: envelope.url,
    requisition: envelope.requisition,
    binding,
    questionnaire: observed,
    empty_first_question: true,
    observed_at: new Date().toISOString(),
    ...(applyDocument
      ? {
          apply_document_id: applyDocument,
          control_kind: "naukri_single_select_radio",
        }
      : {}),
  };
  // Keep ownership in the same volatile browser session; the backend still
  // rejects writes until its original-form/session fence is safely recovered.
  const saved =
    (await api.storage.session.get("naukriParkedQuestionnairesV1"))
      .naukriParkedQuestionnairesV1 || {};
  await api.storage.session.set({
    naukriParkedQuestionnairesV1: {
      ...saved,
      [envelope.id]: {
        id: envelope.id,
        url: envelope.url,
        requisition: envelope.requisition,
        form_pending: true,
        ownerAdopted: false,
        ownedTabId: id,
        binding,
        operation: "inspect_questionnaire",
        recovery_proof: proof,
      },
    },
  });
  return proof;
}

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
