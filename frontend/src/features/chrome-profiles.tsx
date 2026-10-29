"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, ErrorState, Notice } from "@/components/ui";
import { api, post, type Schema } from "@/lib/api";

type Profiles = Schema<"ChromeProfiles">;
type Task = Schema<"ExtensionTask">;
export function ChromeProfiles({
  packet,
  hasUnsavedAnswers = false,
}: {
  packet?: Schema<"PacketRead">;
  hasUnsavedAnswers?: boolean;
}) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const query = useQuery({
    queryKey: ["chrome-profiles"],
    queryFn: ({ signal }) =>
      api<Profiles>("browser/chrome-profiles", { signal }),
    retry: false,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const taskQuery = useQuery({
    queryKey: ["extension-task", packet?.id],
    queryFn: ({ signal }) =>
      api<Task | null>(`browser/extension-tasks/application/${packet!.id}`, {
        signal,
      }),
    enabled: Boolean(packet),
    retry: false,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const state =
    query.data &&
    Array.isArray(query.data.profiles) &&
    Array.isArray(query.data.commands)
      ? query.data
      : undefined;
  const selected = state?.profiles.find((profile) => profile.selected);
  const task = taskQuery.data;
  const terminal =
    packet &&
    [
      "submitting",
      "submission_unknown",
      "provider_confirmed_submitted",
      "user_reported_submitted",
      "withdrawn",
      "abandoned",
    ].includes(packet.lifecycle_state);
  const canCommand =
    selected?.status === "CONNECTED" &&
    selected.commands_enabled &&
    state?.channel_available;
  async function run(path: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      await post(path, body);
      await client.invalidateQueries({ queryKey: ["chrome-profiles"] });
      await client.invalidateQueries({
        queryKey: ["extension-task", packet?.id],
      });
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }
  function command(action: "open" | "prepare") {
    if (!selected || !state || !packet) return;
    void run("browser/chrome-profiles/commands", {
      request_id: crypto.randomUUID(),
      action,
      profile_binding_id: selected.id,
      selection_version: state.selection.version,
      expected_profile_version: selected.version,
      application_id: packet.id,
      packet_revision: packet.revision,
      task_id: task?.id,
      expected_task_version: task?.version,
    });
  }
  return (
    <section
      className="panel panel-body"
      aria-label="Connected Chrome profiles"
    >
      <h2>Connected Chrome profiles</h2>
      <p>
        In your personal or job-application Chrome profile, open Automated Apply
        → Settings → Connect this Chrome profile. Select one profile here for
        all applications. Signing in remains owner-operated.
      </p>
      {query.isError && <ErrorState error={query.error} />}
      {state?.profiles.length === 0 && (
        <Notice>
          PROFILE_OFFLINE: no connected profile. Connect and select your Chrome
          profile to continue.
        </Notice>
      )}
      {state?.profiles.map((profile) => (
        <div key={profile.id} className="panel panel-body">
          <strong>{profile.label}</strong>{" "}
          <Badge tone={profile.status === "CONNECTED" ? "green" : "amber"}>
            {profile.status}
          </Badge>
          {profile.selected && <Badge tone="green">Selected</Badge>}
          <p>Binding: {profile.id}</p>
          <p>
            Last heartbeat:{" "}
            <time dateTime={profile.last_heartbeat}>
              {profile.last_heartbeat}
            </time>
          </p>
          <Button
            disabled={busy || profile.selected || !profile.connected}
            onClick={() =>
              void run("browser/chrome-profiles/select", {
                profile_binding_id: profile.id,
                expected_version: state.selection.version,
              })
            }
          >
            Use {profile.label}
          </Button>{" "}
          <Button
            disabled={busy || !profile.connected}
            onClick={() =>
              void run(`browser/chrome-profiles/${profile.id}/disconnect`, {
                expected_version: profile.version,
              })
            }
          >
            Disconnect {profile.label}
          </Button>
        </div>
      ))}
      {selected && selected.status !== "CONNECTED" && (
        <Notice>
          PROFILE_OFFLINE: {selected.label} has no fresh heartbeat. Work is
          paused; open that Chrome profile and check the extension connection.
        </Notice>
      )}
      {selected && !canCommand && (
        <Notice>
          Dashboard and Telegram commands are disabled. A separate server opt-in
          and this profile’s extension opt-in are required. You can use the
          selected profile’s toolbar assistant.
        </Notice>
      )}
      {packet && (
        <>
          <p>
            <span>{packet.snapshot?.company_name}</span> ·{" "}
            <span>{packet.snapshot?.job_title}</span>
          </p>
          <p>
            Destination:{" "}
            {packet.snapshot?.destination?.application_url ||
              "No approved destination"}{" "}
            · packet {packet.id} · revision {packet.revision}
          </p>
          <Button
            disabled={
              busy || !canCommand || hasUnsavedAnswers || Boolean(terminal)
            }
            onClick={() => command("open")}
          >
            Open in selected Chrome profile
          </Button>{" "}
          <Button
            disabled={
              busy ||
              !canCommand ||
              hasUnsavedAnswers ||
              Boolean(terminal) ||
              !task ||
              task.profile_binding_id !== selected?.id ||
              (task.state === "PAUSED" &&
                !["focus_lost", "active_tab_changed"].includes(
                  task.reason || "",
                )) ||
              task.packet_revision !== packet.revision
            }
            onClick={() => command("prepare")}
          >
            Inspect and prepare answers
          </Button>
          <p className="muted">
            Chrome extension attachments remain manual. Isolated testing can
            attach an approved canonical PDF after upload checks.
          </p>
          <p>
            Opening and inspection do not authorize filling. Review the exact
            fields, values and sources in the extension, then approve the
            selected fields there. Submit manually after reviewing retained
            values.
          </p>
        </>
      )}
      {state?.commands
        .filter((item) => !packet || item.application_id === packet.id)
        .slice(-5)
        .map((item) => (
          <p key={String(item.id)}>
            Command {String(item.action)}: {String(item.state)}
            {item.reason ? ` · ${String(item.reason)}` : ""}
          </p>
        ))}
      {state?.receipts
        ?.filter((receipt) => !packet || receipt.application_id === packet.id)
        .slice(-5)
        .map((receipt) => {
          const verified =
            receipt.verification_method === "retained_after_blur";
          const results = Array.isArray(receipt.results) ? receipt.results : [];
          const count = verified
            ? results.filter((result) => result.status === "filled").length
            : 0;
          return (
            <p key={String(receipt.plan_id)}>
              Receipt · profile {String(receipt.profile_binding_id)} · packet
              revision {String(receipt.packet_revision)} ·{" "}
              {String(receipt.verification_method)} · {count} retained fields ·{" "}
              {receipt.profile_binding_id === selected?.id
                ? "selected profile"
                : "historical profile"}
              . Submission unconfirmed.
            </p>
          );
        })}
      {error && <ErrorState error={error} />}
    </section>
  );
}
