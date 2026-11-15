import assert from "node:assert/strict";
import { request } from "node:http";
import { lstatSync, readFileSync } from "node:fs";

export function assertSetupProfile(queue, entry, path) {
  assert(
    queue?.state === "STOPPED" &&
      Number.isInteger(queue.revision) &&
      queue.revision > 0,
    "brave_setup_stopped_queue_required",
  );
  assert(entry?.path === path, "owner_brave_extension_install_required");
  const reasons = entry.disable_reasons;
  assert(
    reasons === undefined || (Array.isArray(reasons) && reasons.length === 0),
    "owner_brave_extension_enable_required",
  );
}
export function assertSetupTabs(pages, extensionId) {
  assert(
    Array.isArray(pages) &&
      pages.length > 0 &&
      pages.every(
        (tab) =>
          tab.url === "about:blank" ||
          tab.url?.startsWith(`chrome-extension://${extensionId}/`),
      ),
    "brave_setup_original_tabs_preserved",
  );
}

export function inactiveNaukriLoginPlan(windows, tabs) {
  assert(
    Array.isArray(windows) && Array.isArray(tabs),
    "owned_inventory_required",
  );
  assert(windows.length > 0, "owner_brave_window_required");
  assert(
    !tabs.some((tab) =>
      [tab.url, tab.pendingUrl].some((value) => {
        try {
          const host = new URL(value).hostname;
          return host === "naukri.com" || host.endsWith(".naukri.com");
        } catch {
          return false;
        }
      }),
    ),
    "existing_naukri_tab_preserved",
  );
  const eligible = windows.filter(
    (window) =>
      Number.isInteger(window.id) &&
      window.type === "normal" &&
      !window.incognito &&
      tabs.some(
        (tab) =>
          tab.windowId === window.id &&
          tab.active &&
          tab.url === "about:blank" &&
          (!tab.pendingUrl || tab.pendingUrl === "about:blank"),
      ),
  );
  assert(eligible.length === 1, "unique_owned_neutral_window_required");
  return {
    windowId: eligible[0].id,
    url: "https://www.naukri.com/nlogin/login",
    active: false,
  };
}

export async function stoppedQueue(configPath) {
  const metadata = lstatSync(configPath);
  assert(
    metadata.isFile() &&
      metadata.uid === process.getuid() &&
      (metadata.mode & 0o077) === 0 &&
      metadata.size <= 4096,
    "private_native_configuration_required",
  );
  const values = Object.fromEntries(
    readFileSync(configPath, "utf8")
      .trim()
      .split("\n")
      .map((line) => {
        const at = line.indexOf("=");
        assert(at > 0, "private_native_configuration_invalid");
        return [line.slice(0, at), JSON.parse(line.slice(at + 1))];
      }),
  );
  assert(
    values.LOCAL_AGENT_ENDPOINT?.replace(/\/$/, "") === "http://127.0.0.1:8000",
    "fixed_owner_endpoint_required",
  );
  assert(
    typeof values.JOB_AGENT_API_TOKEN === "string" &&
      values.JOB_AGENT_API_TOKEN.length >= 32 &&
      !/[\r\n]/.test(values.JOB_AGENT_API_TOKEN),
    "private_native_configuration_invalid",
  );
  // Explicit node:http loopback connection; no proxy or credential-bearing browser request.
  return new Promise((resolve, reject) => {
    const call = request(
      {
        hostname: "127.0.0.1",
        port: 8000,
        path: "/api/v1/execution/queue?limit=1",
        method: "GET",
        headers: { Authorization: `Bearer ${values.JOB_AGENT_API_TOKEN}` },
      },
      (response) => {
        let size = 0;
        const chunks = [];
        response.on("data", (chunk) => {
          size += chunk.length;
          if (size > 524288) call.destroy(Error("queue_response_limit"));
          else chunks.push(chunk);
        });
        response.on("error", () =>
          reject(Error("queue_preflight_unavailable")),
        );
        response.on("end", () => {
          try {
            assert.equal(
              response.statusCode,
              200,
              "queue_preflight_unavailable",
            );
            const queue = JSON.parse(Buffer.concat(chunks)).configuration;
            assert(
              queue?.state === "STOPPED" && Number.isInteger(queue.revision),
              "brave_reload_stopped_queue_required",
            );
            resolve({ state: queue.state, revision: queue.revision });
          } catch {
            reject(Error("queue_preflight_rejected"));
          }
        });
      },
    );
    const deadline = setTimeout(
      () => call.destroy(Error("queue_preflight_timeout")),
      10000,
    );
    call.once("close", () => clearTimeout(deadline));
    call.on("error", () => reject(Error("queue_preflight_unavailable")));
    call.end();
  });
}
