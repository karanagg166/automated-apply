async function show() {
  const { lastResult } = await chrome.storage.session.get("lastResult");
  document.querySelector("#status").textContent = lastResult ? (lastResult.ok ? "Local agent returned a preview. No application submitted." : lastResult.error_code) : "No connection verified yet.";
  document.querySelector("#result").textContent = lastResult ? JSON.stringify(lastResult.data || {}, null, 2) : "";
}
document.querySelector("#preview").addEventListener("click", async () => {
  document.querySelector("#status").textContent = "Connecting…";
  await chrome.runtime.sendMessage({ command: "preview_active_tab" });
  await show();
});
chrome.storage.onChanged.addListener(show);
await show();
