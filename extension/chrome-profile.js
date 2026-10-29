// Trusted extension contexts only. The binding UUID is public; its credential is not.
const key = "connectedChromeProfileV1";
const sessionKey = "applicationBrowserSessionV1";
export const profileAlarm = "connected-chrome-heartbeat";
const host = "com.automated_apply.agent";
const codePattern = /^[A-Za-z][A-Za-z0-9_]{1,63}$/;
export async function profileContext(api = chrome) {
  const value = (await api.storage.local.get(key))[key];
  const session = (await api.storage.session.get(sessionKey))[sessionKey];
  if (!value?.connected || !session) throw Error("PROFILE_OFFLINE");
  return {
    profile_binding_id: value.id,
    profile_secret: value.secret,
    browser_session_id: session,
    window_id: value.windowId,
  };
}
export async function profileNative(api, command, extra = {}) {
  const request = {
    version: 1,
    request_id: crypto.randomUUID(),
    command,
    ...extra,
  };
  let timer;
  try {
    const result = await Promise.race([
      api.runtime.sendNativeMessage(host, request),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error("backend_timeout")), 45000);
      }),
    ]);
    if (
      result?.version !== 1 ||
      result.request_id !== request.request_id ||
      typeof result.ok !== "boolean"
    )
      throw Error("native_protocol_error");
    if (!result.ok)
      throw Error(
        codePattern.test(result.error_code)
          ? result.error_code
          : "native_protocol_error",
      );
    if (result.data?.submitted !== false) throw Error("native_protocol_error");
    return result.data;
  } finally {
    clearTimeout(timer);
  }
}
export class ChromeProfileConnection {
  constructor(api = chrome) {
    this.api = api;
    this.ready = this.initialize();
  }
  async initialize() {
    await this.api.storage.local.setAccessLevel?.({
      accessLevel: "TRUSTED_CONTEXTS",
    });
    await this.api.storage.session.setAccessLevel?.({
      accessLevel: "TRUSTED_CONTEXTS",
    });
    let session = (await this.api.storage.session.get(sessionKey))[sessionKey];
    if (!session) {
      session = crypto.randomUUID();
      await this.api.storage.session.set({ [sessionKey]: session });
    }
    this.sessionId = session;
    this.value = (await this.api.storage.local.get(key))[key];
    // A browser restart invalidates numeric tab/window IDs. A worker restart does not.
    if (this.value?.connected && this.value.sessionId !== session) {
      this.value.windowId = null;
      this.value.sessionId = session;
      await this.save();
    }
    if (this.value?.connected)
      await this.api.alarms.create(profileAlarm, { periodInMinutes: 0.5 });
  }
  async save() {
    await this.api.storage.local.set({ [key]: this.value });
  }
  async window() {
    if (Number.isInteger(this.value?.windowId)) {
      try {
        const window = await this.api.windows.get(this.value.windowId);
        if (window.type === "normal" && window.incognito !== true)
          return window.id;
      } catch {
        /* Closed windows are never reopened as a browser process. */
      }
    }
    const window = await this.api.windows.getLastFocused({
      windowTypes: ["normal"],
    });
    if (
      !Number.isInteger(window?.id) ||
      window.type !== "normal" ||
      window.incognito === true
    )
      throw Error("PROFILE_OFFLINE");
    this.value.windowId = window.id;
    await this.save();
    return window.id;
  }
  async connect(label) {
    await this.ready;
    if (!label?.trim() || label.trim().length > 80)
      throw Error("profile_label_required");
    this.value = {
      ...this.value,
      id: this.value?.id || crypto.randomUUID(),
      secret:
        this.value?.secret ||
        [...crypto.getRandomValues(new Uint8Array(32))]
          .map((v) => v.toString(16).padStart(2, "0"))
          .join(""),
      label: label.trim(),
      connected: false,
      commandsEnabled: false,
      sessionId: this.sessionId,
    };
    await this.window();
    // Keep identity on a failed connection; do not mint duplicates on retries.
    await this.save();
    const data = await profileNative(this.api, "connect_chrome_profile", {
      profile_binding_id: this.value.id,
      profile_secret: this.value.secret,
      browser_session_id: this.sessionId,
      window_id: this.value.windowId,
      profile_label: this.value.label,
    });
    this.value.connected = true;
    this.value.profile = data.profile;
    await this.save();
    await this.api.alarms.create(profileAlarm, { periodInMinutes: 0.5 });
    return this.status();
  }
  status() {
    // Never expose the binding credential to a popup response, DOM or dashboard.
    return {
      id: this.value?.id,
      label: this.value?.label,
      connected: this.value?.connected === true,
      commandsEnabled: this.value?.commandsEnabled === true,
      profile: this.value?.profile || null,
    };
  }
  heartbeat() {
    const run = (this.heartbeatQueue || Promise.resolve()).then(() =>
      this.sendHeartbeat(),
    );
    this.heartbeatQueue = run.catch(() => {});
    return run;
  }
  async sendHeartbeat() {
    await this.ready;
    if (!this.value?.connected) throw Error("PROFILE_OFFLINE");
    await this.window();
    const data = await profileNative(this.api, "heartbeat_chrome_profile", {
      ...(await profileContext(this.api)),
      profile_commands_enabled: this.value.commandsEnabled === true,
    });
    this.value.profile = data.profile;
    if (!data.profile.connected) this.value.connected = false;
    await this.save();
    return data.profile;
  }
  async verify() {
    const profile = await this.heartbeat();
    if (!profile.selected) throw Error("PROFILE_NOT_SELECTED");
    if (profile.status !== "CONNECTED") throw Error("PROFILE_OFFLINE");
    return profile;
  }
  async disconnect() {
    await this.ready;
    try {
      const profile = await this.heartbeat();
      await profileNative(this.api, "disconnect_chrome_profile", {
        ...(await profileContext(this.api)),
        expected_profile_version: profile.version,
      });
    } finally {
      if (this.value) {
        this.value.connected = false;
        this.value.commandsEnabled = false;
        await this.save();
      }
      await this.api.alarms.clear(profileAlarm);
    }
    return this.status();
  }
  async setCommands(enabled) {
    await this.ready;
    if (!this.value?.connected) throw Error("PROFILE_OFFLINE");
    this.value.commandsEnabled = enabled === true;
    await this.save();
    const profile = await this.heartbeat();
    if (enabled && !profile.commands_enabled) {
      this.value.commandsEnabled = false;
      await this.save();
      throw Error("PROFILE_COMMANDS_DISABLED");
    }
    return this.status();
  }
  async tick(execute) {
    if (this.ticking) return;
    this.ticking = true;
    try {
      const profile = await this.heartbeat();
      if (
        !profile.selected ||
        !profile.commands_enabled ||
        !this.value.commandsEnabled
      )
        return;
      // Persist before executing. Worker/browser restart never replays an uncertain action.
      const pending = (
        await this.api.storage.local.get("chromeCommandInFlightV1")
      ).chromeCommandInFlightV1;
      if (pending) {
        try {
          await this.ack(pending, "outcome_unknown", "worker_restart");
        } catch (error) {
          if (
            ![
              "profile_command_revision_conflict",
              "profile_command_expired",
            ].includes(error.message)
          )
            throw error;
        }
        await this.api.storage.local.remove("chromeCommandInFlightV1");
      }
      const data = await profileNative(
        this.api,
        "poll_chrome_command",
        await profileContext(this.api),
      );
      if (!data.command) return;
      let command = data.command;
      await this.api.storage.local.set({ chromeCommandInFlightV1: command });
      try {
        const started = await profileNative(this.api, "start_chrome_command", {
          ...(await profileContext(this.api)),
          ...this.commandContext(command),
        });
        command = started.command;
        await this.api.storage.local.set({ chromeCommandInFlightV1: command });
        await execute({
          action: command.action,
          application_id: command.application_id,
          task_id: command.task_id,
          expected_task_version: command.expected_task_version,
          expected_packet_revision: command.packet_revision,
          expected_destination: command.destination,
          expected_profile_binding_id: command.profile_binding_id,
          expected_browser_session_id: command.browser_session_id,
          remote_expires_at: command.expires_at,
          remote_command: true,
        });
        await this.ack(command, "completed");
      } catch (error) {
        await this.ack(
          command,
          /permission_required|revision_conflict|context_stale|PROFILE_|command_expired|paused_or_cancelled|unsupported_application_form/.test(
            error.message,
          )
            ? "failed"
            : "outcome_unknown",
          codePattern.test(error.message)
            ? error.message
            : "profile_command_failed",
        );
      }
      await this.api.storage.local.remove("chromeCommandInFlightV1");
    } catch (error) {
      // No background retries beyond the next bounded alarm; no browser fallback.
      if (this.value) {
        this.value.profile = {
          ...this.value.profile,
          status: "PROFILE_OFFLINE",
          reason: codePattern.test(error.message)
            ? error.message
            : "backend_offline",
        };
        await this.save();
      }
    } finally {
      this.ticking = false;
    }
  }
  commandContext(command) {
    return {
      chrome_command_id: command.id,
      expected_command_version: command.version,
      command_lease_token: command.lease_token,
    };
  }
  async ack(command, outcome, error = null) {
    return profileNative(this.api, "ack_chrome_command", {
      ...(await profileContext(this.api)),
      ...this.commandContext(command),
      command_outcome: outcome,
      command_error: error,
    });
  }
}
