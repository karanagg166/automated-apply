import { observationMessage } from "./observation.js";

const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;

async function show() {
  const { lastResult, menuStatus, lastObservation } = await chrome.storage.session.get(["lastResult", "menuStatus", "lastObservation"]);
  const errorCode = typeof lastResult?.error_code === "string" && ERROR_CODE_PATTERN.test(lastResult.error_code)
    ? lastResult.error_code
    : "native_protocol_error";
  document.querySelector("#status").textContent = lastResult ? (lastResult.ok ? "Local agent returned a preview. No application submitted." : errorCode) : "No connection verified yet.";
  document.querySelector("#result").textContent = lastResult ? JSON.stringify(lastResult.data || {}, null, 2) : "";
  document.querySelector("#menu-status").textContent = menuStatus?.registered ? "Right-click menu registered for HTTPS pages." : "Menu registration unverified. Reload the extension or repair the menu.";
  if (lastObservation) document.querySelector("#observation").textContent = observationMessage(lastObservation);
}
document.querySelector("#repair").addEventListener("click", async () => {
  try {
    const result = await chrome.runtime.sendMessage({ command: "repair_context_menu" });
    document.querySelector("#menu-status").textContent = result?.registered ? "Right-click menu registered for HTTPS pages." : "Registration failed. Reload this extension in chrome://extensions.";
  } catch {
    document.querySelector("#menu-status").textContent = "Reload this extension in chrome://extensions, then try repair again.";
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
    document.querySelector("#status").textContent = "Extension worker unavailable. Reload the extension, then retry the preview.";
  } finally {
    previewBusy = false;
  }
});
let observeBusy = false;
document.querySelector("#observe").addEventListener("click", async () => {
  if (observeBusy) return;
  observeBusy = true;
  document.querySelector("#observation").textContent = "Checking visible session indicators…";
  try {
    const result = await chrome.runtime.sendMessage({ command: "observe_portal_session" });
    document.querySelector("#observation").textContent = observationMessage(result);
  } catch {
    document.querySelector("#observation").textContent = "Observation unavailable. Reload the extension and check the local backend.";
  } finally {
    observeBusy = false;
  }
});
chrome.storage.onChanged.addListener(show);
await show();
