import { naukriFormUrl } from "./naukri.js";
import { formDOM } from "./form-dom.js";
import { supportedUrl } from "./preview.js";
const host = "com.automated_apply.agent";
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
let current;
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
    (observation?.state === "manual_required" && observation.fields?.length > 0)
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
  if (!Number.isInteger(tab?.id) || !permittedFormUrl(tab.url))
    throw Error("supported_application_page_required");
  return tab;
}
export async function inspectForm(applicationId) {
  cancelPreparedForm();
  const expected = generation;
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
  if (!canPreview(observation?.result)) {
    throwInspectionStateError(observation.result);
  }
  const data = await native("inspect_form", {
    application_id: applicationId,
    inspection: sanitizeInspection(observation.result),
  });
  requireCurrentGeneration(expected);
  attachPreview(data, observation.result);
  current = { tabId: tab.id, url: tab.url, plan: data.plan };
  return data.plan;
}
export async function prepareAnswers(tab) {
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
    args: [{ operation: "inspect", only_empty: true }],
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
    inspection: sanitizeInspection(observation.result),
  });
  requireCurrentGeneration(expected);
  attachPreview(data, observation.result);
  current = { tabId: tab.id, url: tab.url, plan: data.plan };
  return data.plan;
}
export async function fillForm() {
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
  const fieldIds = snapshot.plan.actions
    .filter((a) => !a.needs_input && !a.preview_only && a.kind !== "file")
    .map((a) => a.field_id);
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
  const { plan } = await native("authorize_form", {
    plan_id: snapshot.plan.id,
    field_ids: fieldIds,
  });
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
  try {
    const finalTab = await active();
    if (finalTab.id !== tab.id || finalTab.url !== tab.url)
      throw Error("page_changed");
  } catch {
    result.state = "manual_required";
    result.reason = "step_changed";
  }
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
