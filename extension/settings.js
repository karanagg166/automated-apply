const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
const ENDPOINT_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
document.querySelector("#identity").textContent = `Extension ID: ${chrome.runtime.id}`;
let checkBusy = false;
document.querySelector("#check").addEventListener("click", async () => {
  if (checkBusy) return;
  checkBusy = true;
  const element = document.querySelector("#endpoint");
  const request = { version: 1, request_id: crypto.randomUUID(), command: "health" };
  let timer;
  try {
    const result = await Promise.race([
      chrome.runtime.sendNativeMessage("com.automated_apply.agent", request),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 45000); }),
    ]);
    if (result?.version !== 1 || typeof result?.ok !== "boolean" || (result.request_id && result.request_id !== request.request_id)) {
      element.textContent = "Connection pending: native_protocol_error";
      return;
    }
    if (result.ok && result.request_id === request.request_id && ENDPOINT_PATTERN.test(result?.data?.endpoint || "")) {
      element.textContent = `Active endpoint: ${result.data.endpoint}`;
      return;
    }
    const code = typeof result?.error_code === "string" && ERROR_CODE_PATTERN.test(result.error_code) ? result.error_code : "backend not ready";
    element.textContent = `Connection pending: ${code}`;
  } catch {
    element.textContent = "Native host unavailable. Check local installation and backend.";
  } finally {
    clearTimeout(timer);
    checkBusy = false;
  }
});
