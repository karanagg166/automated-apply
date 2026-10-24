document.querySelector("#identity").textContent = `Extension ID: ${chrome.runtime.id}`;
document.querySelector("#check").addEventListener("click", async () => {
  const element = document.querySelector("#endpoint");
  try {
    const result = await chrome.runtime.sendNativeMessage("com.automated_apply.agent", { version: 1, request_id: crypto.randomUUID(), command: "health" });
    element.textContent = result.ok && result.data.endpoint ? `Active endpoint: ${result.data.endpoint}` : `Connection pending: ${result.error_code || "backend not ready"}`;
  } catch {
    element.textContent = "Native host unavailable. Check local installation and backend.";
  }
});
