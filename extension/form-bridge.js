import { profileContext } from "./chrome-profile.js";
import { naukriFormUrl } from "./naukri.js";
import { formDOM } from "./form-dom.js";
import { supportedUrl } from "./preview.js";
const host = "com.automated_apply.agent";
const ERROR_CODE_PATTERN = /^[A-Za-z][A-Za-z0-9_]{1,63}$/;
let current;
let activeFill;
let generation = 0;
function permittedFormUrl(value) {
  if (!supportedUrl(value)) return false;
  if (naukriFormUrl(value)) return true;
  const host = new URL(value).hostname.toLowerCase();
  return ![
    "simplify.jobs",
    "linkedin.com",
    "naukri.com",
    "wellfound.com",
    "instahyre.com",
    "internshala.com",
    "accounts.google.com",
    "mail.google.com",
  ].some((domain) => host === domain || host.endsWith("." + domain));
}
export function cancelPreparedForm() {
  generation++;
  current = null;
  if (activeFill) {
    const filling = activeFill;
    void chrome.scripting
      .executeScript({
        target: { tabId: filling.tabId, frameIds: [0] },
        world: "ISOLATED",
        func: formDOM,
        args: [{ operation: "cancel_fill", document_id: filling.documentId }],
      })
      .catch(() => {});
  }
}
function requireCurrentGeneration(expected) {
  if (generation !== expected) throw Error("form_cancelled_reprepare_required");
}
function sanitizeInspection(raw) {
  if (!raw || typeof raw !== "object") return raw;
  const {
    unsupported_controls,
    manual_reason,
    security_status,
    ...inspection
  } = raw;
  if (manual_reason)
    inspection.manual_reason = String(manual_reason).slice(0, 160);
  if (Array.isArray(unsupported_controls) && unsupported_controls.length) {
    inspection.manual_controls = unsupported_controls
      .slice(0, 48)
      .map((control, index) => ({
        control_id: /^u[0-9]{1,3}$/.test(control.control_id || "")
          ? control.control_id
          : `u${index}`,
        kind: String(control.kind || "unsupported").slice(0, 160),
        label: String(control.label || "Unlabelled control").slice(0, 160),
        reason: String(control.reason || "Manual completion required").slice(
          0,
          160,
        ),
        context: control.context ? String(control.context).slice(0, 160) : null,
        required: control.required === true,
        invalid: control.invalid === true,
      }));
  }
  return inspection;
}
function attachPreview(data, observation) {
  if (
    !data.plan?.inspection ||
    !Array.isArray(data.plan.actions) ||
    data.plan.target_url !== observation.url ||
    data.plan.inspection.document_id !== observation.document_id
  )
    throw Error("form_request_rejected");
  data.plan.unsupported_controls = observation.unsupported_controls || [];
  data.plan.manual_reason = observation.manual_reason;
  data.plan.security_status = observation.security_status;
  if (observation.state === "manual_required") data.plan.state = "read_only";
  return data.plan;
}
function canPreview(observation) {
  return (
    ["ready", "validation_errors"].includes(observation?.state) ||
    (observation?.state === "manual_required" &&
      (observation.fields?.length > 0 ||
        (observation.manual_reason ===
          "verified_application_form_not_present" &&
          observation.fields?.length === 0 &&
          naukriFormUrl(observation.url))))
  );
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
  const profile = await profileContext();
  const request = {
    version: 1,
    request_id: crypto.randomUUID(),
    command,
    ...extra,
    ...profile,
    ...(extra.window_id !== undefined ? { window_id: extra.window_id } : {}),
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
  if (!Number.isInteger(tab?.id) || !permittedFormUrl(tab.url))
    throw Error("supported_application_page_required");
  return tab;
}
export async function inspectForm(applicationId, options = {}) {
  cancelPreparedForm();
  const expected = generation;
  if (!/^[a-f0-9-]{36}$/.test(applicationId))
    throw Error("application_id_required");
  // Bound preparation resolves only its saved tab, before and after inspection.
  // Unbound toolbar preparation retains its foreground-only behavior.
  const resolveTab = options.resolveTab || active;
  const tab = await resolveTab();
  if (!Number.isInteger(tab?.id) || !permittedFormUrl(tab.url))
    throw Error("supported_application_page_required");
  const [observation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [
      {
        operation: "inspect",
        only_empty: true,
        ...(options.interactions_allowed ? { interactions_allowed: true } : {}),
      },
    ],
  });
  const after = await resolveTab();
  if (
    after.id !== tab.id ||
    after.windowId !== tab.windowId ||
    after.url !== tab.url ||
    observation?.result?.url !== tab.url
  )
    throw Error("page_changed");
  if (!canPreview(observation?.result)) {
    throwInspectionStateError(observation.result);
  }
  const data = await native("inspect_form", {
    application_id: applicationId,
    tab_id: tab.id,
    window_id: tab.windowId,
    ...options.taskContext,
    inspection: sanitizeInspection(observation.result),
  });
  requireCurrentGeneration(expected);
  attachPreview(data, observation.result);
  if (data.task) data.plan.task = data.task;
  current = {
    tabId: tab.id,
    url: tab.url,
    plan: data.plan,
    interactions_allowed: options.interactions_allowed === true,
  };
  return data.plan;
}
export async function prepareAnswers(tab, options = {}) {
  cancelPreparedForm();
  const expected = generation;
  tab = tab || (await active());
  if (!Number.isInteger(tab?.id) || !permittedFormUrl(tab.url))
    throw Error("supported_application_page_required");
  const before = await active();
  if (before.id !== tab.id || before.url !== tab.url)
    throw Error("page_changed");
  const [observation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [
      {
        operation: "inspect",
        only_empty: true,
        ...(options.interactions_allowed ? { interactions_allowed: true } : {}),
      },
    ],
  });
  const after = await active();
  if (
    after.id !== tab.id ||
    after.url !== tab.url ||
    observation?.result?.url !== tab.url
  )
    throw Error("page_changed");
  if (!canPreview(observation.result)) {
    throwInspectionStateError(observation.result);
  }
  const data = await native("prepare_form_answers", {
    title: String(tab.title || "").slice(0, 250),
    tab_id: tab.id,
    window_id: tab.windowId,
    ...options.taskContext,
    inspection: sanitizeInspection(observation.result),
  });
  requireCurrentGeneration(expected);
  attachPreview(data, observation.result);
  if (data.task) data.plan.task = data.task;
  current = {
    tabId: tab.id,
    url: tab.url,
    plan: data.plan,
    interactions_allowed: options.interactions_allowed === true,
  };
  return data.plan;
}
export async function fillForm(options = {}) {
  if (!current) throw Error("inspect_and_review_first");
  const snapshot = current;
  const expected = generation;
  current = null; // One click/plan, including native transport failures.
  if (snapshot.plan.state === "read_only") throw Error("read_only_preview");
  const tab = await active();
  requireCurrentGeneration(expected);
  if (tab.id !== snapshot.tabId || tab.url !== snapshot.url)
    throw Error("page_changed");
  if (
    snapshot.plan?.expires_at &&
    Number.isFinite(Date.parse(snapshot.plan.expires_at)) &&
    Date.parse(snapshot.plan.expires_at) <= Date.now()
  )
    throw Error("fill_plan_stale");
  const availableFieldIds = snapshot.plan.actions
    .filter((a) => !a.needs_input && !a.preview_only && a.kind !== "file")
    .map((a) => a.field_id);
  const fieldIds =
    options.field_ids === undefined ? availableFieldIds : options.field_ids;
  if (
    !Array.isArray(fieldIds) ||
    fieldIds.length > 24 ||
    new Set(fieldIds).size !== fieldIds.length ||
    fieldIds.some((id) => !availableFieldIds.includes(id))
  )
    throw Error("reviewed_field_selection_invalid");
  if (!fieldIds.length) throw Error("inspect_and_review_first");
  const [validation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [
      {
        operation: "validate_fill",
        document_id: snapshot.plan.inspection.document_id,
      },
    ],
  });
  requireCurrentGeneration(expected);
  if (validation?.result?.state !== "ready")
    throw Error(
      validation?.result?.reason === "security_challenge"
        ? "security_challenge"
        : "dom_changed",
    );
  const authorization = await native("authorize_form", {
    ...options.taskContext,
    tab_id: snapshot.tabId,
    plan_id: snapshot.plan.id,
    field_ids: fieldIds,
  });
  const { plan } = authorization;
  requireCurrentGeneration(expected);
  const after = await active();
  requireCurrentGeneration(expected);
  if (after.id !== tab.id || after.url !== tab.url) throw Error("page_changed");
  if (
    plan?.id !== snapshot.plan.id ||
    plan.target_url !== snapshot.url ||
    plan.inspection?.document_id !== snapshot.plan.inspection.document_id ||
    !Array.isArray(plan.actions) ||
    !Array.isArray(plan.approved_fields) ||
    plan.approved_fields.some((id) => !fieldIds.includes(id))
  )
    throw Error("form_request_rejected");
  const actions = plan.actions.filter((a) =>
    plan.approved_fields.includes(a.field_id),
  );
  activeFill = { tabId: tab.id, documentId: plan.inspection.document_id };
  let filled;
  try {
    [filled] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [0] },
      world: "ISOLATED",
      func: formDOM,
      args: [
        {
          operation: "fill",
          document_id: plan.inspection.document_id,
          expires_at: plan.expires_at,
          actions,
          only_empty: true,
          ...(snapshot.interactions_allowed && options.interaction_authorized
            ? { interaction_authorized: true }
            : {}),
        },
      ],
    });
  } catch {
    filled = {
      result: {
        state: "manual_required",
        reason: "tab_unavailable_fill_unknown",
        results: [],
        submitted: false,
      },
    };
  } finally {
    activeFill = null;
  }
  const result = filled.result;
  try {
    const finalTab = await active();
    if (finalTab.id !== tab.id || finalTab.url !== tab.url)
      throw Error("page_changed");
  } catch {
    result.state = "manual_required";
    result.reason = "step_changed";
  }
  const recorded = await native("record_form_fill", {
    ...options.taskContext,
    ...(authorization.task
      ? { expected_task_version: authorization.task.version }
      : {}),
    tab_id: snapshot.tabId,
    receipt: {
      plan_id: plan.id,
      results: result.results,
      state: result.state,
      submitted: false,
      network_guard_active: options.network_guard === true,
      verification_method:
        result.verification === "retained_after_blur"
          ? "retained_after_blur"
          : "dom_assignment",
    },
  });
  if (recorded.task) result.task = recorded.task;
  return result;
}

// Read-only inspection has no packet preparation or authorization side effects.
export async function inspectOnly(options = {}) {
  cancelPreparedForm();
  const expected = generation;
  const tab = await active();
  const [observation] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    world: "ISOLATED",
    func: formDOM,
    args: [
      {
        operation: "inspect",
        only_empty: true,
        ...(options.interactions_allowed ? { interactions_allowed: true } : {}),
      },
    ],
  });
  const after = await active();
  requireCurrentGeneration(expected);
  if (after.id !== tab.id || after.url !== tab.url) throw Error("page_changed");
  return observation.result;
}

// Recovery uses identifiers only; it does not inspect the saved tab's contents.
export async function interruptForm(tabId, documentId, api = chrome) {
  if (!Number.isInteger(tabId) || !/^[a-f0-9-]{36}$/.test(documentId || ""))
    return;
  await api.scripting
    .executeScript({
      target: { tabId, frameIds: [0] },
      world: "ISOLATED",
      func: formDOM,
      args: [{ operation: "cancel_fill", document_id: documentId }],
    })
    .catch(() => {});
}
