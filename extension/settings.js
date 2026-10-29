const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
const ENDPOINT_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
document.querySelector("#identity").textContent =
  `Extension ID: ${chrome.runtime.id}`;
document.querySelector("#version").textContent =
  `Version: ${chrome.runtime.getManifest().version}`;
async function showGuardPermission() {
  const status = document.querySelector("#guard-permission");
  try {
    const granted = await chrome.permissions.contains({
      permissions: ["declarativeNetRequest"],
    });
    status.textContent = granted
      ? "Network-blocking permission: granted. Website access and exact field approval are still required separately."
      : "Network-blocking permission: missing. Filling is blocked; review the extension update in Chrome.";
  } catch {
    status.textContent =
      "Network-blocking permission: unverified. Filling must remain blocked until Chrome verifies the permission.";
  }
}
void showGuardPermission();
let checkBusy = false;
document.querySelector("#check").addEventListener("click", async () => {
  if (checkBusy) return;
  checkBusy = true;
  await showGuardPermission();
  const element = document.querySelector("#endpoint");
  const request = {
    version: 1,
    request_id: crypto.randomUUID(),
    command: "health",
  };
  let timer;
  try {
    const result = await Promise.race([
      chrome.runtime.sendNativeMessage("com.automated_apply.agent", request),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("timeout")), 45000);
      }),
    ]);
    if (
      result?.version !== 1 ||
      typeof result?.ok !== "boolean" ||
      (result.request_id && result.request_id !== request.request_id)
    ) {
      element.textContent = "Connection pending: native_protocol_error";
      return;
    }
    if (
      result.ok &&
      result.request_id === request.request_id &&
      ENDPOINT_PATTERN.test(result?.data?.endpoint || "")
    ) {
      element.textContent = `Active endpoint: ${result.data.endpoint}`;
      return;
    }
    const code =
      typeof result?.error_code === "string" &&
      ERROR_CODE_PATTERN.test(result.error_code)
        ? result.error_code
        : "backend not ready";
    element.textContent = `Connection pending: ${code}`;
  } catch {
    element.textContent =
      "Native host unavailable. Check local installation and backend.";
  } finally {
    clearTimeout(timer);
    checkBusy = false;
  }
});

async function profileAction(action, extra = {}) {
  const target = document.querySelector("#profile-status");
  try {
    const result = await chrome.runtime.sendMessage({
      command: "chrome_profile",
      action,
      ...extra,
    });
    if (!result?.ok) throw Error(result?.error_code || "profile_unavailable");
    target.textContent = result.connected
      ? `${result.label} · ${result.id} · ${result.profile?.selected ? "selected" : "select in dashboard"} · ${result.profile?.status || "unverified"} · last heartbeat ${result.profile?.last_heartbeat || "unknown"}`
      : "Disconnected";
    document.querySelector("#profile-commands").checked =
      result.commandsEnabled === true;
  } catch (error) {
    target.textContent = `Connection pending: ${/^[A-Za-z][A-Za-z0-9_]{1,63}$/.test(error.message) ? error.message : "profile_unavailable"}`;
    document.querySelector("#profile-commands").checked = false;
  }
}
document.querySelector("#profile-connect").addEventListener("click", () =>
  profileAction("connect", {
    label: document.querySelector("#profile-label").value,
  }),
);
document
  .querySelector("#profile-disconnect")
  .addEventListener("click", () => profileAction("disconnect"));
document
  .querySelector("#profile-commands")
  .addEventListener("change", (event) =>
    profileAction("commands", { enabled: event.target.checked }),
  );
void profileAction("status");
