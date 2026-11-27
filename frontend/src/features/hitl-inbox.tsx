"use client";
// HITL Action Inbox (spec 3.3): prioritized split pane, bidirectionally synced with Telegram —
// resolving here closes the Telegram card through the same v2/hitl resolve/skip endpoints.
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, SkipForward, Zap } from "lucide-react";
import { api, externalUrl, post, readable, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Input,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { stamp } from "@/features/autopilot-forms";
import { HITL_KEY, HITL_PATH } from "@/features/autopilot-hitl";
import { TELEMETRY_KEY, type HitlItem } from "@/lib/ops-types";

type Resolution = Schema<"HitlResolutionRead">;
type HitlPage = { items: HitlItem[]; total: number };
export const INBOX_KEY = ["v2-hitl-inbox"] as const;

export type Lane = "p0" | "fast" | "standard";
export const LANE_LABEL: Record<Lane, string> = {
  p0: "P0 · OTP / CAPTCHA / login",
  fast: "Fresh fast-lane jobs",
  standard: "Standard",
};

export function laneOf(item: HitlItem): Lane {
  if (item.kind === "OTP" || item.kind === "CAPTCHA" || item.kind === "AUTH")
    return "p0";
  if (
    (item.priority != null && item.priority <= 1) ||
    (item.posted_age_days != null && item.posted_age_days <= 0)
  )
    return "fast";
  return "standard";
}

const LANE_ORDER: Lane[] = ["p0", "fast", "standard"];
export function prioritize(items: HitlItem[]) {
  return [...items].sort(
    (a, b) =>
      LANE_ORDER.indexOf(laneOf(a)) - LANE_ORDER.indexOf(laneOf(b)) ||
      (a.created_at ?? "").localeCompare(b.created_at ?? ""),
  );
}

// Mirrors backend ai_v2/semantic_cache/policy.py: MOTIVATION / CUSTOM_PROMPT / COVER_LETTER.
const MOTIVATION =
  /\bwhy (?:do you want|are you (?:interested|applying|excited)|would you like|should we hire|us\b|this (?:company|role|position|team)|join|work (?:here|with us|for us|at))|\bwhat (?:excites|interests|attracts|draws) you\b|\binterest(?:ed)? in (?:joining|working at|this company)\b|\bcover (?:letter|note)\b|\bwhat do you know about (?:us|our)\b|\bour (?:mission|product|company)\b/i;
const CUSTOM_PROMPT =
  /\b(?:write (?:a |an )?(?:function|program|query|code|sql)|solve|implement|case study|take.?home|assignment|how would you (?:design|build|architect|implement)|system design|leetcode)\b/i;

/** Why the answer must stay one-time (null = it may be promoted to the semantic cache). */
export function cacheBlockReason(item: HitlItem): string | null {
  if (item.kind !== "QUESTION") return "Only screening questions are cached";
  if (
    item.cache_policy === "never_cache" ||
    item.intent === "role_specific_custom"
  )
    return "never_cache: custom prompt";
  if (item.intent === "company_motivation" || MOTIVATION.test(item.question))
    return "company_motivation: answer is specific to this company";
  if (
    CUSTOM_PROMPT.test(item.question) ||
    /cover (?:letter|note)/i.test(item.question)
  )
    return "never_cache: custom prompt";
  return null;
}

function Detail({
  item,
  onDone,
}: {
  item: HitlItem;
  onDone: (message: string) => void;
}) {
  const client = useQueryClient();
  const [answer, setAnswer] = useState("");
  const blocked = cacheBlockReason(item);
  const [cache, setCache] = useState(!blocked);
  useEffect(() => {
    setAnswer(item.suggested_answer ?? "");
    setCache(!cacheBlockReason(item));
  }, [item]);
  const resolve = useMutation({
    mutationFn: async (action: "answer" | "skip" | "retry") => {
      const path =
        action === "answer"
          ? `v2/hitl/${item.id}/resolve`
          : `v2/hitl/${item.id}/${action}`;
      const body =
        action === "answer"
          ? { answer: answer.trim(), cache_answer: !blocked && cache }
          : {};
      return (await post<Resolution>(path, body)).message;
    },
    onSuccess: (message) => {
      client.invalidateQueries({ queryKey: INBOX_KEY });
      client.invalidateQueries({ queryKey: HITL_KEY });
      client.invalidateQueries({ queryKey: TELEMETRY_KEY });
      onDone(message);
    },
  });
  const answerable = item.kind === "QUESTION" || item.kind === "OTP";
  const url = externalUrl(item.job_url);
  const shot = item.screenshot ? externalUrl(item.screenshot) : undefined;
  const submit = () => {
    if (answerable && answer.trim() && !resolve.isPending)
      resolve.mutate("answer");
  };
  const submitRef = useRef(submit);
  submitRef.current = submit;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.key !== "Enter" ||
        (target &&
          ["INPUT", "TEXTAREA", "BUTTON", "A", "SELECT"].includes(
            target.tagName,
          ))
      )
        return;
      submitRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <article className="hitl-detail stack" aria-labelledby="hitl-detail-h">
      <div className="split">
        <div>
          <div className="eyebrow">{LANE_LABEL[laneOf(item)]}</div>
          <h2 id="hitl-detail-h">
            {[item.company, item.title].filter(Boolean).join(" — ") ||
              readable(item.platform)}
          </h2>
          <p className="muted small-print">
            {readable(item.platform)} · {readable(item.kind)} · ref{" "}
            <code>{item.ref}</code> · {stamp(item.created_at)}
          </p>
        </div>
        <Badge tone={item.telegram_msg_id ? "green" : "neutral"}>
          {item.telegram_msg_id ? "Synced to Telegram" : "Dashboard only"}
        </Badge>
      </div>
      <p className="hitl-question">{item.question}</p>
      <div className="tag-list">
        {item.field_kind || item.input_kind ? (
          <Badge>Field: {readable(item.field_kind || item.input_kind)}</Badge>
        ) : null}
        {item.resolver_reason && (
          <Badge tone="amber">{readable(item.resolver_reason)}</Badge>
        )}
        {item.fit_score != null && (
          <Badge>Fit {Math.round(item.fit_score)}</Badge>
        )}
      </div>
      {shot && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="hitl-shot"
          src={shot}
          alt="Screenshot of the form when it paused"
        />
      )}
      {item.suggested_answer && (
        <Notice>
          AI suggestion: <strong>{item.suggested_answer}</strong>
          {item.judge_score != null &&
            ` · judge groundedness ${Math.round(item.judge_score * 100)}%`}
        </Notice>
      )}
      {item.options.length > 0 && answerable ? (
        <div
          className="hitl-options"
          role="radiogroup"
          aria-label="Answer options"
        >
          {item.options.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={answer === option}
              className={`state-tab ${answer === option ? "active" : ""}`}
              onClick={() => setAnswer(option)}
            >
              {option}
            </button>
          ))}
        </div>
      ) : answerable ? (
        <label className="field">
          <span>{item.kind === "OTP" ? "OTP code" : "Your answer"}</span>
          <Input
            value={answer}
            maxLength={1000}
            autoComplete={item.kind === "OTP" ? "one-time-code" : "off"}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submit();
              }
            }}
          />
        </label>
      ) : null}
      {item.kind === "QUESTION" && (
        <div className="stack">
          <label className="check-label">
            <input
              type="checkbox"
              checked={!blocked && cache}
              disabled={!!blocked}
              onChange={(event) => setCache(event.target.checked)}
            />
            Promote to Semantic Cache
          </label>
          {blocked && (
            <span className="small-print">
              <Badge tone="amber">One-time answer</Badge> {blocked}
            </span>
          )}
        </div>
      )}
      <div className="actions">
        {answerable && (
          <Button
            variant="primary"
            busy={resolve.isPending}
            disabled={!answer.trim()}
            onClick={submit}
          >
            <Zap size={14} /> Submit &amp; resume
          </Button>
        )}
        {(item.kind === "CAPTCHA" || item.kind === "ERROR") && (
          <Button
            variant="primary"
            busy={resolve.isPending}
            onClick={() => resolve.mutate("retry")}
          >
            Solved — retry
          </Button>
        )}
        <Button
          variant="ghost"
          busy={resolve.isPending}
          onClick={() => resolve.mutate("skip")}
        >
          <SkipForward size={14} /> Skip job
        </Button>
        {url && (
          <a
            className="button ghost"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={14} /> Open apply URL
          </a>
        )}
      </div>
      {resolve.isError && <ErrorState error={resolve.error} />}
    </article>
  );
}

export function HitlInboxPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const inbox = useQuery({
    queryKey: INBOX_KEY,
    queryFn: () => api<HitlPage>(HITL_PATH),
    refetchInterval: 15000,
  });
  const items = useMemo(
    () => prioritize(inbox.data?.items ?? []),
    [inbox.data],
  );
  const current = items.find((i) => i.id === selected) ?? items[0];
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
        return;
      if (event.key !== "j" && event.key !== "k") return;
      const index = items.findIndex((i) => i.id === current?.id);
      const next = items[index + (event.key === "j" ? 1 : -1)];
      if (next) setSelected(next.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, current]);
  return (
    <>
      <PageTitle
        eyebrow="HUMAN IN THE LOOP"
        title="Action inbox"
        description="Everything the worker could not answer safely. Same queue as Telegram — answer in either place. j / k to move, Enter to submit."
        actions={
          <Badge tone={items.length ? "amber" : "green"}>
            {items.length} open
          </Badge>
        }
      />
      {done && <Notice>{done}</Notice>}
      {inbox.isPending ? (
        <Skeleton />
      ) : inbox.isError ? (
        <ErrorState error={inbox.error} retry={() => inbox.refetch()} />
      ) : items.length === 0 || !current ? (
        <Empty
          title="Nothing needs you"
          description="Unseen screening questions, OTPs, CAPTCHAs and expired sessions appear here and on Telegram."
        />
      ) : (
        <div className="hitl-split">
          <ul className="hitl-queue" aria-label="Open requests">
            {items.map((item) => {
              const lane = laneOf(item);
              return (
                <li key={item.id}>
                  <button
                    className={`hitl-row ${item.id === current.id ? "active" : ""}`}
                    aria-current={item.id === current.id ? "true" : undefined}
                    onClick={() => setSelected(item.id)}
                  >
                    <span className="split">
                      <strong>{item.company || readable(item.platform)}</strong>
                      <Badge
                        tone={
                          lane === "p0"
                            ? "red"
                            : lane === "fast"
                              ? "amber"
                              : "neutral"
                        }
                      >
                        {lane === "p0"
                          ? "P0"
                          : lane === "fast"
                            ? "Fast lane"
                            : readable(item.kind)}
                      </Badge>
                    </span>
                    <span className="hitl-row-q">{item.question}</span>
                    <span className="muted small-print">
                      {stamp(item.created_at)}
                      {item.posted_age_days != null &&
                        ` · posted ${item.posted_age_days}d ago`}
                      {item.fit_score != null &&
                        ` · fit ${Math.round(item.fit_score)}`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <Detail key={current.id} item={current} onDone={setDone} />
        </div>
      )}
    </>
  );
}
