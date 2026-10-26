import { formDOM } from "./form-dom.js";
import { supportedUrl } from "./preview.js";
const host = "com.automated_apply.agent";
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
let current;
function sanitizeInspection(raw) {
  if (!raw || typeof raw !== "object") return raw;
  const { unsupported_controls, manual_reason, ...inspection } = raw;
  return inspection;
}
function throwInspectionStateError(observationResult) {
  const err = Error(
    observationResult?.state === "login_required"
      ? "login_required"
      : "unsupported_application_form",
  );
  if (observationResult?.manual_reason) {
    err.manual_reason = observationResult.manual_reason;
  }
  if (Array.isArray(observationResult?.unsupported_controls)) {
    err.unsupported_controls = observationResult.unsupported_controls;
  }
  throw err;
}
async function native(command, extra) {
  const request = {
    version: 1,
    request_id: crypto.randomUUID(),
    command,
    ...extra,
  };
  let timer;
  try {
    const result = await Promise.race([
      chrome.runtime.sendNativeMessage(host, request),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error("timeout")), 45000);
      }),
    ]);
    if (
      result?.version === 1 &&
      result.request_id === request.request_id &&
      result.ok === false &&
      ERROR_CODE_PATTERN.test(result.error_code)
    )
      throw Error(result.error_code);
    if (
      result?.version !== 1 ||
      result.request_id !== request.request_id ||
      !result.ok ||
      result.data?.submitted !== false
    )
      throw Error("form_request_rejected");
    return result.data;
  } finally {
    clearTimeout(timer);
  }
}
async function active() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!Number.isInteger(tab?.id) || !supportedUrl(tab.url))
    throw Error("supported_application_page_required");
  return tab;
}
export async function inspectForm(applicationId) {
  current = null;
  if (!/^[a-f0-9-]{36}$/.test(applicationId))
    throw Error("application_id_required");
  const tab = await active();
  const [observation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [{ operation: "inspect", only_empty: true }],
  });
  const after = await active();
  if (after.id !== tab.id || after.url !== tab.url) throw Error("page_changed");
  if (
    observation?.result?.state &&
    !["ready", "validation_errors"].includes(observation.result.state)
  ) {
    throwInspectionStateError(observation.result);
  }
  const data = await native("inspect_form", {
    application_id: applicationId,
    inspection: sanitizeInspection(observation.result),
  });
  if (
    Array.isArray(observation.result?.unsupported_controls) &&
    observation.result.unsupported_controls.length &&
    data.plan
  ) {
    data.plan.unsupported_controls = observation.result.unsupported_controls;
  }
  current = { tabId: tab.id, url: tab.url, plan: data.plan };
  return data.plan;
}
export async function prepareAnswers(tab) {
  current = null;
  tab = tab || (await active());
  if (!Number.isInteger(tab?.id) || !supportedUrl(tab.url))
    throw Error("supported_application_page_required");
  const before = await active();
  if (before.id !== tab.id || before.url !== tab.url)
    throw Error("page_changed");
  const [observation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [{ operation: "inspect", only_empty: true }],
  });
  const after = await active();
  if (
    after.id !== tab.id ||
    after.url !== tab.url ||
    observation?.result?.url !== tab.url
  )
    throw Error("page_changed");
  if (!["ready", "validation_errors"].includes(observation.result.state)) {
    throwInspectionStateError(observation.result);
  }
  const data = await native("prepare_form_answers", {
    title: String(tab.title || "").slice(0, 250),
    inspection: sanitizeInspection(observation.result),
  });
  if (
    !data.plan?.inspection ||
    !Array.isArray(data.plan.actions) ||
    data.plan.target_url !== tab.url
  )
    throw Error("form_request_rejected");
  if (
    Array.isArray(observation.result?.unsupported_controls) &&
    observation.result.unsupported_controls.length
  ) {
    data.plan.unsupported_controls = observation.result.unsupported_controls;
  }
  current = { tabId: tab.id, url: tab.url, plan: data.plan };
  return data.plan;
}
export async function fillForm() {
  if (!current) throw Error("inspect_and_review_first");
  const snapshot = current;
  current = null; // One click/plan, including native transport failures.
  const tab = await active();
  if (tab.id !== snapshot.tabId || tab.url !== snapshot.url)
    throw Error("page_changed");
  if (
    snapshot.plan?.expires_at &&
    Number.isFinite(Date.parse(snapshot.plan.expires_at)) &&
    Date.parse(snapshot.plan.expires_at) <= Date.now()
  )
    throw Error("fill_plan_stale");
  const fieldIds = snapshot.plan.actions
    .filter((a) => !a.needs_input && a.kind !== "file")
    .map((a) => a.field_id);
  const { plan } = await native("authorize_form", {
    plan_id: snapshot.plan.id,
    field_ids: fieldIds,
  });
  const after = await active();
  if (after.id !== tab.id || after.url !== tab.url) throw Error("page_changed");
  const actions = plan.actions.filter((a) =>
    plan.approved_fields.includes(a.field_id),
  );
  const [filled] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [
      {
        operation: "fill",
        document_id: plan.inspection.document_id,
        actions,
        only_empty: true,
      },
    ],
  });
  const result = filled.result;
  await native("record_form_fill", {
    receipt: {
      plan_id: plan.id,
      results: result.results,
      state: result.state,
      submitted: false,
    },
  });
  return result;
}
