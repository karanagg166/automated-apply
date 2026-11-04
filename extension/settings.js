import {
  continueRetainedQuestionnaire,
  inspectUnansweredRetainedForm,
  configureRetainedHeartbeat,
} from "./naukri-retained.js";

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
async function showNaukriAccess() {
  const status = document.querySelector("#naukri-access");
  if (!status) return;
  try {
    const allowed = await chrome.permissions.contains({
      origins: ["https://www.naukri.com/*"],
    });
    status.textContent = allowed
      ? "Naukri website access: granted. Dashboard policy is still required."
      : "Naukri website access: missing. Background discovery is paused.";
  } catch {
    status.textContent = "Naukri website access: unverified.";
  }
}
document
  .querySelector("#naukri-access-enable")
  ?.addEventListener("click", async () => {
    try {
      await chrome.permissions.request({
        origins: ["https://www.naukri.com/*"],
      });
    } finally {
      await showNaukriAccess();
    }
  });
void showNaukriAccess();
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
    await configureRetainedHeartbeat(
      chrome,
      action === "status"
        ? document.documentElement.dataset.retainedExclusive || null
        : null,
    );
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
document
  .querySelector("#profile-refresh")
  ?.addEventListener("click", () => profileAction("status"));
window.addEventListener("pagehide", () => {
  void configureRetainedHeartbeat(chrome, null).catch(() => {});
});

async function retainedChoices() {
  const select = document.querySelector("#retained-work");
  if (!select) return;
  const forms =
    (await chrome.storage.session.get("naukriParkedQuestionnairesV1"))
      .naukriParkedQuestionnairesV1 || {};
  select.replaceChildren();
  for (const form of Object.values(forms)) {
    if (!form.form_pending || form.ownerAdopted) continue;
    const option = document.createElement("option");
    option.value = form.id;
    option.textContent = `${form.title || "Existing application"} · ${form.id}`;
    select.append(option);
  }
}
void retainedChoices();

document
  .querySelector("#inspect-retained-recovery")
  ?.addEventListener("click", async () => {
    const status = document.querySelector("#retained-recovery-status");
    try {
      const envelope = JSON.parse(
        document.querySelector("#retained-recovery-envelope").value,
      );
      const proof = await inspectUnansweredRetainedForm(envelope);
      status.textContent = JSON.stringify(proof);
      await retainedChoices();
    } catch (error) {
      status.textContent = JSON.stringify({
        error: ERROR_CODE_PATTERN.test(error.message)
          ? error.message
          : "retained_recovery_unavailable",
        detail: String(error.message || error.name).slice(0, 240),
      });
    }
  });

document
  .querySelector("#continue-retained")
  ?.addEventListener("click", async () => {
    const button = document.querySelector("#continue-retained");
    const status = document.querySelector("#retained-status");
    if (button.disabled) return;
    button.disabled = true;
    status.textContent = "Checking the existing application…";
    try {
      const identity = document.querySelector("#retained-work")?.value;
      if (!identity) throw Error("retained_application_required");
      const exclusive = document.documentElement.dataset.retainedExclusive;
      if (exclusive) {
        if (exclusive !== identity)
          throw Error("retained_work_context_changed");
        await configureRetainedHeartbeat(chrome, identity);
      }
      await continueRetainedQuestionnaire(
        chrome,
        undefined,
        undefined,
        identity,
      );
      status.textContent =
        "Existing application checked. See the dashboard for its outcome or next question.";
    } catch (error) {
      status.textContent = `Waiting: ${ERROR_CODE_PATTERN.test(error.message) ? error.message : "retained_application_unavailable"}`;
    } finally {
      button.disabled = false;
    }
  });
