"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Input,
  Notice,
  Skeleton,
} from "@/components/ui";
import { stamp } from "@/features/autopilot-forms";

type TelegramStatus = Schema<"TelegramStatusRead">;
type Hitl = Schema<"HitlRead">;
type HitlPage = Schema<"HitlPage">;
type Resolution = Schema<"HitlResolutionRead">;
type ResumeAuth = Schema<"ResumeAuthRead">;

export const TELEGRAM_KEY = ["v2-telegram-status"] as const;
export const HITL_KEY = ["v2-hitl-open"] as const;
const STATUS_KEY = ["v2-status"] as const;
export const HITL_PATH = "v2/hitl?status=OPEN&limit=50";
export const LEGACY_POLLER = "com.automated-apply.rust";

type Tone = "neutral" | "green" | "amber" | "red";

/** Badge label + tone for the Autopilot status bar. */
export function telegramBadge(status: TelegramStatus): {
  label: string;
  tone: Tone;
} {
  if (!status.configured)
    return { label: "Telegram: Not configured", tone: "neutral" };
  if (status.polling_state === "conflict")
    return { label: "Telegram: Conflict", tone: "red" };
  if (status.polling_state === "error")
    return { label: "Telegram: Error", tone: "amber" };
  if (status.polling_state === "polling" && !status.stale)
    return { label: "Telegram: Connected", tone: "green" };
  return { label: "Telegram: Offline", tone: "amber" };
}

const KIND_LABEL: Record<Hitl["kind"], string> = {
  QUESTION: "Screening question",
  AUTH: "Session expired",
  CAPTCHA: "CAPTCHA",
  OTP: "OTP needed",
  ERROR: "Apply error",
};

export function TelegramStatusBadge() {
  const status = useQuery({
    queryKey: TELEGRAM_KEY,
    queryFn: () => api<TelegramStatus>("v2/telegram/status"),
    refetchInterval: 15000,
  });
  if (!status.data) return null;
  const { label, tone } = telegramBadge(status.data);
  return (
    <span title={status.data.last_error ?? undefined}>
      <Badge tone={tone}>{label}</Badge>
    </span>
  );
}

function useResolve(item: Hitl, onDone: (message: string) => void) {
  const client = useQueryClient();
  const refresh = (message: string) => {
    client.invalidateQueries({ queryKey: HITL_KEY });
    client.invalidateQueries({ queryKey: STATUS_KEY });
    client.invalidateQueries({ queryKey: TELEGRAM_KEY });
    onDone(message);
  };
  return useMutation({
    mutationFn: async (
      action:
        | { kind: "answer"; answer: string; cache: boolean }
        | { kind: "skip" | "retry" | "resume" },
    ) => {
      if (action.kind === "resume") {
        const result = await post<ResumeAuth>(
          `v2/portal-rules/${item.platform}/resume-auth`,
        );
        return result.message;
      }
      if (action.kind === "answer") {
        const result = await post<Resolution>(`v2/hitl/${item.id}/resolve`, {
          answer: action.answer,
          cache_answer: action.cache,
        });
        return result.message;
      }
      const result = await post<Resolution>(
        `v2/hitl/${item.id}/${action.kind}`,
      );
      return result.message;
    },
    onSuccess: refresh,
  });
}

function HitlCard({
  item,
  onDone,
}: {
  item: Hitl;
  onDone: (message: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [cache, setCache] = useState(true);
  const resolve = useResolve(item, onDone);
  const busy = resolve.isPending;
  const job = [item.company, item.title].filter(Boolean).join(" · ");
  const answerable = item.kind === "QUESTION" || item.kind === "OTP";
  return (
    <article
      className="portal-status hitl-item"
      aria-label={`HITL ${item.ref}`}
    >
      <div className="split">
        <div>
          <h3>{KIND_LABEL[item.kind]}</h3>
          <p className="muted small-print">
            {readable(item.platform)}
            {job ? ` · ${job}` : ""} · ref <code>{item.ref}</code> ·{" "}
            {stamp(item.created_at)}
          </p>
        </div>
        <Badge
          tone={item.kind === "AUTH" || item.kind === "ERROR" ? "red" : "amber"}
        >
          {item.telegram_msg_id ? "Sent to Telegram" : "Not yet on Telegram"}
        </Badge>
      </div>
      <p className="hitl-question">{item.question}</p>
      {item.resolver_reason && (
        <p className="muted small-print">
          Why it needs you: {readable(item.resolver_reason)}
        </p>
      )}
      {item.kind === "QUESTION" && item.options.length > 0 && (
        <div className="hitl-options" role="group" aria-label="Options">
          {item.options.map((option, index) => (
            <Button
              key={option}
              variant={answer === option ? "primary" : "secondary"}
              aria-pressed={answer === option}
              disabled={busy}
              onClick={() => setAnswer(option)}
            >
              {index + 1}. {option}
            </Button>
          ))}
        </div>
      )}
      {answerable && item.options.length === 0 && (
        <Field label={item.kind === "OTP" ? "OTP code" : "Your answer"}>
          <Input
            value={answer}
            maxLength={1000}
            autoComplete={item.kind === "OTP" ? "one-time-code" : "off"}
            onChange={(event) => setAnswer(event.target.value)}
          />
        </Field>
      )}
      {item.kind === "QUESTION" && (
        <label className="check-label">
          <input
            type="checkbox"
            checked={cache}
            onChange={(event) => setCache(event.target.checked)}
          />
          Save to semantic cache (reuse for similar questions)
        </label>
      )}
      {item.kind === "AUTH" && (
        <p className="portal-hint">
          Run{" "}
          <code>
            backend/venv/bin/python -m backend.app.browser_v2.cli login-setup
            --portal {item.platform}
          </code>{" "}
          on the Mac, then resume. Other portals keep running.
        </p>
      )}
      <div className="actions">
        {answerable && (
          <Button
            variant="primary"
            busy={busy}
            disabled={!answer.trim()}
            onClick={() =>
              resolve.mutate({
                kind: "answer",
                answer: answer.trim(),
                cache: item.kind === "QUESTION" && cache,
              })
            }
          >
            Answer &amp; resume
          </Button>
        )}
        {(item.kind === "CAPTCHA" || item.kind === "ERROR") && (
          <Button
            variant="primary"
            busy={busy}
            onClick={() => resolve.mutate({ kind: "retry" })}
          >
            {item.kind === "CAPTCHA" ? "Solved — retry" : "Retry job"}
          </Button>
        )}
        {item.kind === "AUTH" ? (
          <Button
            variant="primary"
            busy={busy}
            onClick={() => resolve.mutate({ kind: "resume" })}
          >
            I&apos;ve logged in — resume portal
          </Button>
        ) : (
          <Button
            variant="ghost"
            busy={busy}
            onClick={() => resolve.mutate({ kind: "skip" })}
          >
            Skip job
          </Button>
        )}
      </div>
      {resolve.isError && <ErrorState error={resolve.error} />}
    </article>
  );
}

export function HitlInbox() {
  const [done, setDone] = useState<string | null>(null);
  const inbox = useQuery({
    queryKey: HITL_KEY,
    queryFn: () => api<HitlPage>(HITL_PATH),
    refetchInterval: 10000,
  });
  const telegram = useQuery({
    queryKey: TELEGRAM_KEY,
    queryFn: () => api<TelegramStatus>("v2/telegram/status"),
    refetchInterval: 15000,
  });
  return (
    <section className="panel" aria-labelledby="hitl-heading">
      <div className="panel-header">
        <div>
          <h2 id="hitl-heading">Needs your input (HITL inbox)</h2>
          <p>
            Same queue as Telegram: answer here or reply to the bot. Answers
            re-queue the job ahead of new discoveries.
          </p>
        </div>
        <div className="tag-list">
          {inbox.data && (
            <Badge tone={inbox.data.total ? "amber" : "green"}>
              {inbox.data.total} open
            </Badge>
          )}
        </div>
      </div>
      <div className="panel-body stack">
        {telegram.data?.polling_state === "conflict" && (
          <div className="notice warn" role="alert">
            Another poller — likely legacy <code>{LEGACY_POLLER}</code> — is
            using this bot token, so Telegram replies may not reach this worker.
            Answer here, or stop it with{" "}
            <code>launchctl bootout gui/$(id -u)/{LEGACY_POLLER}</code>.
          </div>
        )}
        {telegram.data && !telegram.data.configured && (
          <p className="muted small-print">
            Telegram is not configured (add <code>TELEGRAM_BOT_TOKEN</code> +{" "}
            <code>TELEGRAM_OWNER_CHAT_ID</code> to the private env file). The
            inbox below still works.
          </p>
        )}
        {done && <Notice>{done}</Notice>}
        {inbox.isPending ? (
          <Skeleton />
        ) : inbox.isError ? (
          <ErrorState error={inbox.error} retry={() => inbox.refetch()} />
        ) : inbox.data.items.length === 0 ? (
          <Empty
            title="Nothing needs you"
            description="Unseen screening questions, OTPs, CAPTCHAs and expired sessions appear here and on Telegram."
          />
        ) : (
          <div className="hitl-list">
            {inbox.data.items.map((item) => (
              <HitlCard key={item.id} item={item} onDone={setDone} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
