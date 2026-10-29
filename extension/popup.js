import { observationMessage } from "./observation.js";
import {
  formErrorMessage,
  formPlanText,
  missingInputLinks,
} from "./form-messages.js";
const $ = (selector) => document.querySelector(selector);
let approvedFieldIds = [];
let selectedTask = null,
  reviewed = false,
  plan = null,
  busy = false;
const codePattern = /^[a-z][a-z0-9_]{1,63}$/;
function text(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}
function disable(selector, value) {
  const element = $(selector);
  if (element) element.disabled = value;
}
function status(value) {
  text("#answer-status", value);
}
async function assistant(action, extra = {}) {
  const result = await chrome.runtime.sendMessage({
    command: "application_assistant",
    action,
    task_id: selectedTask?.id,
    ...extra,
  });
  if (!result?.ok)
    throw Error(
      codePattern.test(result?.error_code)
        ? result.error_code
        : "assistant_unavailable",
    );
  if (result.task) renderTask(result.task);
  return result;
}
function renderTask(task) {
  selectedTask = task;
  if ($("#task-list")) $("#task-list").value = task.id;
  text(
    "#application-title",
    `${task.company_name || "Application"} · ${task.job_title || "Saved role"}`,
  );
  if ($("#application-id"))
    $("#application-id").value = task.application_id || "";
  text(
    "#packet-status",
    `${task.application_id || "Unknown"} · revision ${task.packet_revision ?? "?"} · profile ${task.profile_version ?? "?"}`,
  );
  text(
    "#tab-status",
    task.tab_id == null
      ? "Closed or unbound — Open Application"
      : `Tab ${task.tab_id} · ${task.state} · ${task.current_url || task.target_url || ""}`,
  );
  text("#step-status", task.step || "Fresh inspection required");
  text("#challenge-status", task.challenge_state || "UNKNOWN");
  text(
    "#next-action",
    task.next_action ||
      "Inspect the current step, then prepare and review answers.",
  );
  text("#connection-status", "Local agent connected · submission disabled");
  text(
    "#network-guard-status",
    task.network_guard_active
      ? "Application tab networking is blocked. Review the page, then explicitly return browser control for manual use."
      : "No active network guard reported for this task.",
  );
  disable("#return-control", !task.network_guard_active);
}
function resetReview() {
  reviewed = false;
  disable("#fill-form", true);
  disable("#review-answers", true);
  text("#review-status", "A preview does not authorize a fill.");
}
function renderPlan(value) {
  plan = value;
  resetReview();
  text("#form-plan", formPlanText(plan));
  const choices = $("#approved-fields");
  choices?.replaceChildren();
  approvedFieldIds = [];
  for (const action of plan.actions || []) {
    if (
      action.needs_input ||
      action.preview_only ||
      action.kind === "file" ||
      !action.evidence?.length ||
      plan.state === "read_only"
    )
      continue;
    const field = plan.inspection?.fields?.find(
      (item) => item.field_id === action.field_id,
    );
    const label = document.createElement("label"),
      checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.fieldId = action.field_id;
    checkbox.addEventListener("change", () => {
      reviewed = false;
      disable("#fill-form", true);
      text(
        "#review-status",
        "Selected fields changed. Review these answers again.",
      );
    });
    label.className = "check";
    label.append(
      checkbox,
      document.createTextNode(
        `${field?.section ? `${field.section} · ` : ""}${field?.label || action.field_id}`,
      ),
    );
    choices?.append(label);
  }
  if (choices && !choices.children.length)
    choices.textContent = "No executable fields in this preview.";
  const ready = (plan.actions || []).filter(
    (a) =>
      !a.needs_input &&
      !a.preview_only &&
      a.kind !== "file" &&
      a.evidence?.length,
  ).length;
  const missing = (plan.actions || []).filter((a) => a.needs_input).length;
  const manual =
    (plan.actions || []).filter((a) => a.preview_only || a.kind === "file")
      .length + (plan.unsupported_controls || []).length;
  text(
    "#field-summary",
    `${ready} ready · ${plan.inspection?.completed_count || 0} already completed · ${missing} missing answers · ${manual} manual-only`,
  );
  text(
    "#challenge-status",
    plan.inspection?.challenge_state ||
      plan.challenge_state ||
      (plan.security_status === "none" ? "NONE" : "UNKNOWN"),
  );
  text("#step-status", plan.inspection?.page_step || "Current form step");
  const questions = $("#missing-answers");
  questions?.replaceChildren();
  for (const question of missingInputLinks(plan)) {
    const item = document.createElement("li"),
      link = document.createElement("a");
    link.href = question.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    link.textContent = `Review saved question: ${question.label}`;
    item.append(link);
    questions?.append(item);
  }
  disable("#review-answers", !ready || plan.state === "read_only");
  disable("#ask-telegram", !selectedTask || !missingInputLinks(plan).length);
  status(
    plan.state === "read_only"
      ? plan.manual_reason === "background_network_scope_unverified"
        ? "Read-only preview generated. This website uses background networking outside the tab guard; complete it manually."
        : ["security_widget", "security_challenge"].includes(
              plan.manual_reason,
            ) ||
            [
              "WIDGET_PRESENT_UNVERIFIED",
              "CHALLENGE_BLOCKING",
              "UNKNOWN",
            ].includes(plan.inspection?.challenge_state)
          ? "Read-only preview generated. Complete the security challenge yourself. Fresh inspection and review are required before any fill."
          : "Read-only preview generated. This page requires manual attention. Fresh inspection and review are required before any fill."
      : `${ready} answers prepared. Review every proposed value, destination and packet before authorizing fields.`,
  );
}
async function run(action, extra = {}) {
  if (busy) return;
  busy = true;
  try {
    const result = await assistant(action, extra);
    if (result.plan) renderPlan(result.plan);
    if (result.inspection) {
      resetReview();
      plan = null;
      const observation = result.inspection;
      text(
        "#form-plan",
        (observation.fields || [])
          .map(
            (f) =>
              `${f.section ? `${f.section} · ` : ""}${f.label}${f.required ? " (required)" : ""}${f.manual_reason ? ` — ${f.manual_reason}` : ""}`,
          )
          .join("\n"),
      );
      text("#challenge-status", observation.challenge_state || "UNKNOWN");
      text("#step-status", observation.page_step || "Current form step");
      text(
        "#field-summary",
        `${observation.fields?.length || 0} unanswered controls · ${observation.completed_count || 0} already completed`,
      );
      status(
        "Inspection complete. Prepare Answers to create a packet-bound preview. No fields changed.",
      );
    }
    if (result.result) {
      const receipts = result.result.results || [];
      const verified = receipts.filter((r) => r.status === "filled").length;
      const errors = receipts.filter((r) =>
        ["failed", "validation_error"].includes(r.status),
      ).length;
      status(
        `${verified} fields ${result.result.verification === "retained_after_blur" ? "retained after blur and a delayed website check" : "verified by value readback"}; ${errors} errors. ${result.result.reason ? "The page changed or filling stopped; inspect again. " : ""}Review the website and complete remaining manual fields. No application submitted.`,
      );
      resetReview();
    }
    if (action === "return_control") {
      resetReview();
      plan = null;
      status(
        result.synchronized === false
          ? "Website networking restored locally. Backend status could not synchronize; reconnect before using the assistant."
          : "Extension execution paused. Website networking restored for your manual control.",
      );
    }
    if (action === "ask") {
      resetReview();
      plan = null;
      status(
        "Correlated questions saved and queued for the owner on Telegram. Reply to the specific prompt; then prepare and review fresh answers here.",
      );
    }
    if (["pause", "resume", "cancel"].includes(action)) {
      resetReview();
      plan = null;
      status(
        action === "resume"
          ? "Task resumed. Inspect and review the current step before filling."
          : `Application ${action === "pause" ? "paused" : "cancelled"}. Values already delivered to the website remain for your review.`,
      );
    }
    return result;
  } catch (error) {
    status(formErrorMessage(error));
    text(
      "#connection-status",
      "Check local agent connection or the application task",
    );
  } finally {
    busy = false;
  }
}
function click(id, fn) {
  $(id)?.addEventListener("click", (event) => {
    if (event.isTrusted) return fn();
  });
}
click("#inspect-form", () =>
  run("inspect", {
    interactions_allowed: $("#allow-interactions")?.checked === true,
  }),
);
click("#prepare-answers", () =>
  run("prepare", {
    interactions_allowed: $("#allow-interactions")?.checked === true,
  }),
);
click("#open-application", async () => {
  const applicationId = $("#application-id").value.trim();
  if (!selectedTask || selectedTask.application_id !== applicationId) {
    const data = await run("destination", { application_id: applicationId });
    if (data?.task) {
      text(
        "#open-application",
        `Allow ${new URL(data.task.target_url).hostname} and open`,
      );
      status(
        `Destination: ${data.task.target_url}. Click again to request Chrome permission only for this origin and open the application. No fields will be changed.`,
      );
    }
    return;
  }
  try {
    const origin = new URL(selectedTask.target_url).origin;
    // Must begin in this explicit popup click, before awaiting any native request.
    const granted = await chrome.permissions.request({
      origins: [origin + "/*"],
    });
    if (!granted) {
      status(
        "Origin permission declined. Use the toolbar on the employer page for gesture-only access.",
      );
      return;
    }
    await run("open", { application_id: applicationId });
    text("#open-application", "Open Application");
  } catch {
    status(
      "Chrome origin permission could not be requested. Open the application page and use the toolbar.",
    );
  }
});
click("#review-answers", () => {
  approvedFieldIds = [
    ...document.querySelectorAll("#approved-fields input:checked"),
  ].map((input) => input.dataset.fieldId);
  if (!approvedFieldIds.length) {
    status("Select at least one ready field to review and authorize.");
    return;
  }
  reviewed = true;
  text(
    "#review-status",
    `Reviewed packet ${plan?.application_id || selectedTask?.application_id || ""}, revision ${plan?.packet_revision ?? "?"}. Fill Approved Fields separately authorizes these exact values.`,
  );
  disable("#fill-form", !plan || plan.state === "read_only");
});
click("#fill-form", async () => {
  if (!reviewed) return;
  try {
    // Chrome requires the block-only API permission at installation. Guard activation
    // is still a separate explicit fill action; no request bodies are inspected.
    const granted = await chrome.permissions.contains({
      permissions: ["declarativeNetRequest"],
    });
    if (!granted) {
      status(
        "The installed extension lacks its submission guard permission. Review the installation upgrade; no fields were changed.",
      );
      return;
    }
  } catch {
    status(
      "Chrome could not activate the submission guard. No fields were changed.",
    );
    return;
  }
  disable("#fill-form", true);
  await run("fill", {
    interaction_authorized: $("#allow-interactions")?.checked === true,
  });
});
click("#ask-telegram", () => run("ask"));
click("#return-control", () => {
  if (
    !confirm(
      "Restore this application's website networking for manual control? Any page-scheduled autosave or requests may then resume. This pauses extension execution; review the site yourself.",
    )
  )
    return;
  return run("return_control");
});
for (const action of ["pause", "resume", "cancel"])
  click(`#${action}-form`, () => {
    // Cancellation must reach the worker even while another action awaits a reply.
    if (["pause", "cancel"].includes(action) && busy) {
      resetReview();
      void assistant(action).catch((error) => status(formErrorMessage(error)));
      return;
    }
    return run(action);
  });
$("#allow-interactions")?.addEventListener("change", () => {
  resetReview();
  plan = null;
  status("Interaction permission changed. Prepare and review fresh answers.");
});
$("#task-list")?.addEventListener("change", async (event) => {
  resetReview();
  plan = null;
  selectedTask = tasks.find((task) => task.id === event.target.value) || null;
  if (selectedTask) renderTask(selectedTask);
});
let tasks = [];
async function refreshTasks() {
  try {
    const response = await assistant("list");
    tasks = response.tasks || [];
    const select = $("#task-list");
    if (select) {
      select.replaceChildren(new Option("Current active form", ""));
      for (const task of tasks)
        select.append(
          new Option(
            `${task.company_name || "Application"} · ${task.job_title || task.id} · ${task.state}`,
            task.id,
          ),
        );
      select.value = selectedTask?.id || "";
    }
    const updated = tasks.find((task) => task.id === selectedTask?.id);
    if (updated) renderTask(updated);
    text(
      "#connection-status",
      "Local agent connection checked · application tasks restored",
    );
  } catch {
    text(
      "#connection-status",
      "Local agent unavailable. Open connection settings to check the native host.",
    );
  }
}
async function show() {
  const { lastResult, menuStatus, lastObservation } =
    await chrome.storage.session.get([
      "lastResult",
      "menuStatus",
      "lastObservation",
    ]);
  text(
    "#status",
    lastResult
      ? lastResult.ok
        ? "URL preview saved. Prepare Answers to inspect the form. No application submitted."
        : codePattern.test(lastResult.error_code)
          ? lastResult.error_code
          : "native_protocol_error"
      : "No connection verified yet.",
  );
  text(
    "#menu-status",
    menuStatus?.registered
      ? "Right-click menu registered for HTTPS pages."
      : "Menu registration unverified. Reload the extension or repair the menu.",
  );
  if (lastObservation)
    text("#observation", observationMessage(lastObservation));
}
let previewBusy = false,
  observeBusy = false;
$("#preview")?.addEventListener("click", async () => {
  if (previewBusy) return;
  previewBusy = true;
  try {
    await chrome.runtime.sendMessage({ command: "preview_active_tab" });
    await show();
  } catch {
    text("#status", "Extension worker unavailable. Reload the extension.");
  } finally {
    previewBusy = false;
  }
});
$("#observe")?.addEventListener("click", async () => {
  if (observeBusy) return;
  observeBusy = true;
  try {
    text(
      "#observation",
      observationMessage(
        await chrome.runtime.sendMessage({ command: "observe_portal_session" }),
      ),
    );
  } catch {
    text("#observation", "Check the local backend connection.");
  } finally {
    observeBusy = false;
  }
});
$("#repair")?.addEventListener("click", async () => {
  try {
    const result = await chrome.runtime.sendMessage({
      command: "repair_context_menu",
    });
    text(
      "#menu-status",
      result?.registered
        ? "Right-click menu registered for HTTPS pages."
        : "Reload this extension in chrome://extensions.",
    );
  } catch {
    text("#menu-status", "Reload this extension in chrome://extensions.");
  }
});
chrome.storage.onChanged.addListener(() => {
  void show();
});
await show();
// Unit mocks do not have a DOM select; real popup restores pending tasks immediately.
if ($("#task-list")) {
  await refreshTasks();
  const { applicationReviewV1, answerRequested } =
    await chrome.storage.session.get([
      "applicationReviewV1",
      "answerRequested",
    ]);
  if (applicationReviewV1) {
    const task = tasks.find((item) => item.id === applicationReviewV1.task_id);
    if (task) {
      renderTask(task);
      renderPlan(applicationReviewV1.plan);
      status(
        "Saved preview restored. Prepare fresh answers after any worker restart, navigation or manual edits.",
      );
    }
  }
  if (answerRequested) {
    await chrome.storage.session.remove("answerRequested");
    const [tab] = await chrome.tabs.query({
      active: true,
      currentWindow: true,
    });
    if (tab?.id === answerRequested.tabId && tab?.url === answerRequested.url)
      await run("prepare");
  }
  setInterval(() => {
    if (!busy) void refreshTasks();
  }, 5000);
}
