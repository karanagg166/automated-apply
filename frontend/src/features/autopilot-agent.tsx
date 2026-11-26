"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  Skeleton,
} from "@/components/ui";
import { stamp } from "@/features/autopilot-forms";
import { RULES_KEY } from "@/features/autopilot-rules";
import { STATUS_KEY } from "@/features/autopilot-status";

type AgentReply = Schema<"AgentChatRead">;
type ReplyPage = Schema<"MailReplyPage">;
type MailEvent = Schema<"MailEventRead">;

export const REPLIES_KEY = ["v2-mail-replies"] as const;

const EXAMPLES = [
  "how many applied today?",
  "pause Internshala for 3 hours",
  "raise Naukri daily limit to 60",
  "blacklist TCS and Infosys",
];

type Turn = { id: number; text: string; reply?: AgentReply; error?: string };

function verdictTone(reply: AgentReply) {
  if (reply.verdict === "rejected") return "red" as const;
  if (reply.verdict === "confirm") return "amber" as const;
  return reply.ok ? ("green" as const) : ("neutral" as const);
}

export function AgentControlChat() {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const send = useMutation({
    mutationFn: (message: string) =>
      post<AgentReply>("v2/agent/chat", { text: message }),
    onSuccess: (reply, message) => {
      setTurns((rows) => [
        { id: Date.now(), text: message, reply },
        ...rows.slice(0, 9),
      ]);
      if (reply.ok && reply.tool !== "query_application_status") {
        client.invalidateQueries({ queryKey: RULES_KEY });
        client.invalidateQueries({ queryKey: STATUS_KEY });
      }
    },
    onError: (error, message) => {
      setTurns((rows) => [
        {
          id: Date.now(),
          text: message,
          error: error instanceof Error ? error.message : "Request failed",
        },
        ...rows.slice(0, 9),
      ]);
    },
  });
  const submit = (message: string) => {
    const value = message.trim();
    if (!value || send.isPending) return;
    setText("");
    send.mutate(value);
  };
  return (
    <section className="panel" aria-labelledby="agent-heading">
      <div className="panel-header">
        <div>
          <h2 id="agent-heading">Agent Control Chat</h2>
          <p>
            The same control agent as Telegram free chat. It changes portal
            rules and preferences, answers status questions and pauses or
            resumes the worker — never mid-application. It cannot send email,
            delete data or re-apply to a job.
          </p>
        </div>
        <Badge tone="neutral">Guardrailed</Badge>
      </div>
      <form
        className="panel-body stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit(text);
        }}
      >
        <Field
          label="Message"
          hint="Add 'confirm' for high-impact changes such as enabling auto-apply."
        >
          <Input
            value={text}
            maxLength={2000}
            autoComplete="off"
            placeholder="e.g. pause Internshala for 3 hours"
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <div className="actions">
          <Button
            type="submit"
            variant="primary"
            busy={send.isPending}
            disabled={!text.trim()}
          >
            Send to agent
          </Button>
          {EXAMPLES.map((example) => (
            <Button
              key={example}
              type="button"
              variant="ghost"
              disabled={send.isPending}
              onClick={() => submit(example)}
            >
              {example}
            </Button>
          ))}
        </div>
        <ol
          className="stack"
          aria-label="Agent conversation"
          aria-live="polite"
        >
          {turns.map((turn) => (
            <li key={turn.id} className="portal-status">
              <p>
                <strong>You:</strong> {turn.text}
              </p>
              {turn.reply ? (
                <>
                  <div className="tag-list">
                    <Badge tone={verdictTone(turn.reply)}>
                      {turn.reply.verdict ?? (turn.reply.ok ? "ok" : "error")}
                    </Badge>
                    {turn.reply.tool && (
                      <Badge tone="neutral">
                        {turn.reply.tool.replaceAll("_", " ")}
                      </Badge>
                    )}
                  </div>
                  <p style={{ whiteSpace: "pre-line" }}>{turn.reply.reply}</p>
                </>
              ) : (
                <p className="notice warn">{turn.error}</p>
              )}
            </li>
          ))}
        </ol>
      </form>
    </section>
  );
}

const KIND_LABEL: Record<MailEvent["kind"], string> = {
  INTERVIEW: "Interview",
  RECRUITER_REPLY: "Recruiter reply",
  JOB_ALERT: "Job alert",
};

export function RecruiterRepliesFeed() {
  const replies = useQuery({
    queryKey: REPLIES_KEY,
    queryFn: () => api<ReplyPage>("v2/mail/replies?limit=20"),
    refetchInterval: 60000,
  });
  const tiers = replies.data
    ? Object.entries(replies.data.tiers)
        .filter(([, on]) => on)
        .map(([name]) => name.replace("_", " "))
    : [];
  return (
    <section className="panel" aria-labelledby="replies-heading">
      <div className="panel-header">
        <div>
          <h2 id="replies-heading">Recruiter Replies &amp; Alerts</h2>
          <p>
            Replies to your drafts and interview / assessment emails, found by
            the read-only inbox watcher every 15 minutes and pushed to Telegram.
          </p>
        </div>
        <div className="tag-list">
          <Badge tone="neutral">Read-only inbox</Badge>
          {replies.data && (
            <Badge tone={replies.data.configured ? "green" : "amber"}>
              {replies.data.configured
                ? `Reading via ${tiers.join(" → ")}`
                : "Inbox not configured"}
            </Badge>
          )}
        </div>
      </div>
      <div className="panel-body">
        {replies.isPending ? (
          <Skeleton />
        ) : replies.isError ? (
          <ErrorState error={replies.error} retry={() => replies.refetch()} />
        ) : replies.data.items.length === 0 ? (
          <Empty
            title="No replies yet"
            description="Recruiter replies and interview invitations appear here once the inbox watcher finds them."
          />
        ) : (
          <ul className="stack" aria-label="Recruiter replies">
            {replies.data.items.map((item) => (
              <li key={item.id ?? item.subject} className="portal-status">
                <div className="split">
                  <strong>
                    {item.company_name ?? item.sender ?? "Unknown sender"}
                  </strong>
                  <Badge tone={item.kind === "INTERVIEW" ? "green" : "neutral"}>
                    {KIND_LABEL[item.kind]}
                  </Badge>
                </div>
                <p>{item.subject ?? "(no subject)"}</p>
                {item.snippet && (
                  <p className="muted small-print">{item.snippet}</p>
                )}
                <small className="muted">
                  {stamp(item.received_at ?? item.created_at, "—")}
                  {item.platform ? ` · ${item.platform}` : ""}
                </small>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
