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

import { inspectForm, fillForm } from './form-bridge.js';
let formBusy=false;
document.querySelector('#inspect-form').addEventListener('click',async event=>{
  if(!event.isTrusted || formBusy) return;
  formBusy=true;
  document.querySelector('#fill-form').disabled=true;
  try {
    const plan=await inspectForm(document.querySelector('#application-id').value.trim());
    document.querySelector('#form-plan').textContent=plan.actions.map(a=>`${a.field_id} ${plan.inspection.fields.find(f=>f.field_id===a.field_id)?.label}: ${a.needs_input ? 'Needs input' : a.kind==='file' ? 'Upload canonical PDF manually' : a.value}\nEvidence: ${a.evidence.join(', ')}`).join('\n\n');
    document.querySelector('#fill-form').disabled=false;
  } catch {document.querySelector('#form-plan').textContent='Inspection unavailable. Check saved application ID, page, owner authorization and current profile.';}
  finally {formBusy=false;}
});
document.querySelector('#fill-form').addEventListener('click',async event=>{
  if(!event.isTrusted || formBusy) return;
  formBusy=true; document.querySelector('#fill-form').disabled=true;
  try {const result=await fillForm();document.querySelector('#form-plan').textContent=`${result.state}. Inspect values and upload the canonical PDF manually. Submission not performed.`;}
  catch {document.querySelector('#form-plan').textContent='Manual intervention required. Reinspect the page before retrying. Submission not performed.';}
  finally {formBusy=false;}
});
