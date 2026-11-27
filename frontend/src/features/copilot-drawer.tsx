"use client";
// Agent Copilot drawer (spec 3.6): the audited agent_v2 control chat with tool-call trace pills and
// explicit confirmation cards. Risky writes are only executed after a "confirm" turn (backend guardrail).
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Send, ShieldAlert, X } from "lucide-react";
import { post, readable, type Schema } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui";
import { TELEMETRY_KEY } from "@/lib/ops-types";

type AgentReply = Schema<"AgentChatRead">;
type Turn = {
  id: number;
  text: string;
  reply?: AgentReply;
  error?: string;
  settled?: "confirmed" | "cancelled";
};

const READ_PREFIX = /^(?:query_|get_|list_|read_|explain_|help)/;
/** True when the tool can change state (rules, queue, profile, HITL). */
export function isMutatingTool(tool: string | null | undefined) {
  return !!tool && !READ_PREFIX.test(tool);
}

function TracePill({ reply }: { reply: AgentReply }) {
  if (!reply.tool && !reply.source) return null;
  const mutating = isMutatingTool(reply.tool);
  return (
    <details className="copilot-trace">
      <summary>
        <Badge tone={mutating ? "amber" : "neutral"}>
          {reply.tool ? readable(reply.tool) : "no tool"}
          {mutating ? " · write" : " · read"}
        </Badge>
      </summary>
      <dl className="small-print">
        <dt>Tool</dt>
        <dd>
          <code>{reply.tool ?? "—"}</code>
        </dd>
        <dt>Planner</dt>
        <dd>{reply.source ?? "—"}</dd>
        <dt>Verdict</dt>
        <dd>{reply.verdict ?? (reply.ok ? "ok" : "not ok")}</dd>
        <dt>Audit</dt>
        <dd>Recorded in agent_audit_log (source api)</dd>
      </dl>
    </details>
  );
}

export function CopilotDrawer({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const send = useMutation({
    mutationFn: (message: string) =>
      post<AgentReply>("v2/agent/chat", { text: message }),
    onSuccess: (reply, message) => {
      setTurns((rows) =>
        [...rows, { id: Date.now(), text: message, reply }].slice(-20),
      );
      if (reply.ok && isMutatingTool(reply.tool)) client.invalidateQueries();
      else client.invalidateQueries({ queryKey: TELEMETRY_KEY });
    },
    onError: (error, message) =>
      setTurns((rows) => [
        ...rows,
        {
          id: Date.now(),
          text: message,
          error: error instanceof Error ? error.message : "Request failed",
        },
      ]),
  });
  const submit = (message: string) => {
    const value = message.trim();
    if (!value || send.isPending) return;
    setText("");
    send.mutate(value);
  };
  const settle = (turn: Turn, how: "confirmed" | "cancelled") => {
    setTurns((rows) =>
      rows.map((r) => (r.id === turn.id ? { ...r, settled: how } : r)),
    );
    submit(how === "confirmed" ? "confirm" : "cancel");
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="copilot-drawer">
          <div className="split">
            <Dialog.Title className="dialog-title">
              <Bot size={18} /> Agent copilot
            </Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="Close copilot">
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted small-print">
            Same audited agent as Telegram. It can never send email, delete data
            or re-apply; risky changes wait for your confirmation.
          </Dialog.Description>
          <ol className="copilot-log" aria-live="polite">
            {turns.length === 0 && (
              <li className="muted small-print">
                Try “how many applied today?” or “pause Internshala for 3
                hours”.
              </li>
            )}
            {turns.map((turn) => (
              <li key={turn.id} className="copilot-turn">
                <p className="copilot-you">{turn.text}</p>
                {turn.error && (
                  <p className="form-error" role="alert">
                    {turn.error}
                  </p>
                )}
                {turn.reply && (
                  <div className="copilot-reply">
                    <p>{turn.reply.reply}</p>
                    <TracePill reply={turn.reply} />
                    {turn.reply.verdict === "confirm" && (
                      <div
                        className="copilot-confirm"
                        role="group"
                        aria-label="Confirmation required"
                      >
                        <p>
                          <ShieldAlert size={14} /> This changes live automation
                          settings.
                        </p>
                        {turn.settled ? (
                          <Badge
                            tone={
                              turn.settled === "confirmed" ? "green" : "neutral"
                            }
                          >
                            {readable(turn.settled)}
                          </Badge>
                        ) : (
                          <div className="actions">
                            <Button
                              variant="primary"
                              onClick={() => settle(turn, "confirmed")}
                            >
                              Confirm
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => settle(turn, "cancelled")}
                            >
                              Cancel
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
          <form
            className="copilot-form"
            onSubmit={(event) => {
              event.preventDefault();
              submit(text);
            }}
          >
            <Input
              aria-label="Message the agent"
              placeholder="Ask or instruct the agent…"
              maxLength={2000}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
            <Button
              type="submit"
              variant="primary"
              busy={send.isPending}
              aria-label="Send"
            >
              <Send size={14} />
            </Button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
