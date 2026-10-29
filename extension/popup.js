import { observationMessage } from "./observation.js";
import {
  inspectForm,
  prepareAnswers,
  fillForm,
  cancelPreparedForm,
} from "./form-bridge.js";
import {
  formErrorMessage,
  formPlanText,
  missingInputLinks,
} from "./form-messages.js";

const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;

async function show() {
  const { lastResult, menuStatus, lastObservation } =
    await chrome.storage.session.get([
      "lastResult",
      "menuStatus",
      "lastObservation",
    ]);
  const errorCode =
    typeof lastResult?.error_code === "string" &&
    ERROR_CODE_PATTERN.test(lastResult.error_code)
      ? lastResult.error_code
      : "native_protocol_error";
  document.querySelector("#status").textContent = lastResult
    ? lastResult.ok
      ? "URL preview saved. Use Prepare answers to answer the form. No application submitted."
      : errorCode
    : "No connection verified yet.";
  document.querySelector("#result").textContent = lastResult
    ? JSON.stringify(lastResult.data || {}, null, 2)
    : "";
  document.querySelector("#menu-status").textContent = menuStatus?.registered
    ? "Right-click menu registered for HTTPS pages."
    : "Menu registration unverified. Reload the extension or repair the menu.";
  if (lastObservation)
    document.querySelector("#observation").textContent =
      observationMessage(lastObservation);
}
document.querySelector("#repair").addEventListener("click", async () => {
  try {
    const result = await chrome.runtime.sendMessage({
      command: "repair_context_menu",
    });
    document.querySelector("#menu-status").textContent = result?.registered
      ? "Right-click menu registered for HTTPS pages."
      : "Registration failed. Reload this extension in chrome://extensions.";
  } catch {
    document.querySelector("#menu-status").textContent =
      "Reload this extension in chrome://extensions, then try repair again.";
  }
});
let previewBusy = false;
document.querySelector("#preview").addEventListener("click", async () => {
  if (previewBusy) return;
  previewBusy = true;
  document.querySelector("#status").textContent = "Connecting…";
  try {
    await chrome.runtime.sendMessage({ command: "preview_active_tab" });
    await show();
  } catch {
    document.querySelector("#status").textContent =
      "Extension worker unavailable. Reload the extension, then retry the preview.";
  } finally {
    previewBusy = false;
  }
});
let observeBusy = false;
document.querySelector("#observe").addEventListener("click", async () => {
  if (observeBusy) return;
  observeBusy = true;
  document.querySelector("#observation").textContent =
    "Checking visible session indicators…";
  try {
    const result = await chrome.runtime.sendMessage({
      command: "observe_portal_session",
    });
    document.querySelector("#observation").textContent =
      observationMessage(result);
  } catch {
    document.querySelector("#observation").textContent =
      "Observation unavailable. Reload the extension and check the local backend.";
  } finally {
    observeBusy = false;
  }
});
chrome.storage.onChanged.addListener(show);
await show();

let formBusy = false;
document.querySelector("#cancel-form")?.addEventListener("click", (event) => {
  if (!event.isTrusted) return;
  cancelPreparedForm();
  document.querySelector("#fill-form").disabled = true;
  document.querySelector("#form-plan").textContent = "";
  document.querySelector("#answer-status").textContent =
    "Preparation cancelled. Check the page, then prepare fresh answers to continue.";
});
async function prepare(useSavedApplication = false) {
  if (formBusy) return;
  formBusy = true;
  document.querySelector("#fill-form").disabled = true;
  document.querySelector("#form-plan").textContent = "";
  document.querySelector("#missing-answers")?.replaceChildren();
  document.querySelector("#answer-status").textContent =
    "Reading unanswered fields and preparing answers from your reviewed facts…";
  try {
    const plan = useSavedApplication
      ? await inspectForm(
          document.querySelector("#application-id").value.trim(),
        )
      : await prepareAnswers();
    document.querySelector("#form-plan").textContent = formPlanText(plan);
    const questions = document.querySelector("#missing-answers");
    for (const question of missingInputLinks(plan)) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = question.url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = `Review saved question: ${question.label}`;
      item.append(link);
      questions?.append(item);
    }
    const ready = plan.actions.filter(
      (action) =>
        !action.needs_input &&
        !action.preview_only &&
        action.kind !== "file" &&
        action.evidence.length,
    ).length;
    document.querySelector("#answer-status").textContent =
      plan.state === "read_only"
        ? "Read-only answers prepared. Filling is disabled. Complete security checks yourself, then prepare and review fresh answers."
        : ready
          ? `${ready} answer${ready === 1 ? "" : "s"} ready. Review the proposed answers below before filling.`
          : plan.actions.some(
                (action) => !action.needs_input && action.preview_only,
              )
            ? "Proposed answers are shown for manual entry or further answer review. No fields were changed."
            : "No supported answers are ready. Review missing facts in Profile; no fields were changed.";
    document.querySelector("#fill-form").disabled =
      plan.state === "read_only" || !ready;
  } catch (error) {
    if (
      Array.isArray(error?.unsupported_controls) &&
      error.unsupported_controls.length
    ) {
      document.querySelector("#form-plan").textContent = formPlanText({
        inspection: { fields: [] },
        actions: [],
        unsupported_controls: error.unsupported_controls,
      });
    }
    document.querySelector("#answer-status").textContent =
      formErrorMessage(error);
  } finally {
    formBusy = false;
  }
}
document
  .querySelector("#prepare-answers")
  .addEventListener("click", async (event) => {
    if (event.isTrusted) await prepare();
  });
document
  .querySelector("#inspect-form")
  .addEventListener("click", async (event) => {
    if (event.isTrusted) await prepare(true);
  });
document
  .querySelector("#fill-form")
  .addEventListener("click", async (event) => {
    if (!event.isTrusted || formBusy) return;
    formBusy = true;
    document.querySelector("#fill-form").disabled = true;
    try {
      const result = await fillForm();
      if (result.state === "manual_required" || result.state === "failed") {
        document.querySelector("#form-plan").textContent = "";
        document.querySelector("#answer-status").textContent = formErrorMessage(
          Error(
            result.reason === "step_changed" ? "step_changed" : "dom_changed",
          ),
        );
        return;
      }
      const filled = result.results.filter(
        (item) => item.status === "filled",
      ).length;
      const validationErrors = result.results.filter(
        (item) => item.status === "validation_error",
      ).length;
      document.querySelector("#answer-status").textContent = validationErrors
        ? `${filled} field${filled === 1 ? "" : "s"} filled (${validationErrors} validation error${validationErrors === 1 ? "" : "s"} — review highlighted fields on the page). Existing answers were preserved. No application submitted.`
        : `${filled} field${filled === 1 ? "" : "s"} filled. Review the page and any remaining questions. Existing answers were preserved. No application submitted.`;
    } catch (error) {
      document.querySelector("#answer-status").textContent =
        formErrorMessage(error);
    } finally {
      formBusy = false;
    }
  });
// A context-menu gesture requests preparation, never authorization or a fill.
const { answerRequested } = await chrome.storage.session.get([
  "answerRequested",
]);
if (answerRequested) {
  await chrome.storage.session.remove("answerRequested");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === answerRequested.tabId && tab?.url === answerRequested.url)
    await prepare();
  else
    document.querySelector("#answer-status").textContent = formErrorMessage(
      Error("page_changed"),
    );
}
