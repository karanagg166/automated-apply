async function show() {
  const { lastResult, menuStatus } = await chrome.storage.session.get(["lastResult", "menuStatus"]);
  document.querySelector("#status").textContent = lastResult ? (lastResult.ok ? "Local agent returned a preview. No application submitted." : lastResult.error_code) : "No connection verified yet.";
  document.querySelector("#result").textContent = lastResult ? JSON.stringify(lastResult.data || {}, null, 2) : "";
  document.querySelector("#menu-status").textContent = menuStatus?.registered ? "Right-click menu registered for HTTPS pages." : "Menu registration unverified. Reload the extension or repair the menu.";
}
document.querySelector("#repair").addEventListener("click", async () => {
  try {
    const result = await chrome.runtime.sendMessage({ command: "repair_context_menu" });
    document.querySelector("#menu-status").textContent = result?.registered ? "Right-click menu registered for HTTPS pages." : "Registration failed. Reload this extension in chrome://extensions.";
  } catch {
    document.querySelector("#menu-status").textContent = "Reload this extension in chrome://extensions, then try repair again.";
  }
});
document.querySelector("#preview").addEventListener("click", async () => {
  document.querySelector("#status").textContent = "Connecting…";
  await chrome.runtime.sendMessage({ command: "preview_active_tab" });
  await show();
});
document.querySelector("#observe").addEventListener("click", async () => {
  document.querySelector("#observation").textContent = "Checking visible session indicators…";
  try {
    const result = await chrome.runtime.sendMessage({ command: "observe_portal_session" });
    document.querySelector("#observation").textContent = result?.ok ? `${result.data.state}. Account identity and applicant API access remain unverified.` : (result?.error_code || "Observation unavailable");
  } catch {
    document.querySelector("#observation").textContent = "Observation unavailable. Reload the extension and check the local backend.";
  }
});
chrome.storage.onChanged.addListener(show);
await show();
