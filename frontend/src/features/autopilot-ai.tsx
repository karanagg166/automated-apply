"use client";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, del, post, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Skeleton,
} from "@/components/ui";
import { QuotaBar } from "@/features/autopilot-status";
import { stamp } from "@/features/autopilot-forms";

type AIStatus = Schema<"AIStatusRead">;
type Provider = Schema<"ProviderStatusRead">;
type CachePage = Schema<"SemanticCachePage">;
type CacheEntry = Schema<"SemanticCacheEntryRead">;

export const AI_STATUS_KEY = ["v2-ai-status"] as const;
export const CACHE_KEY = ["v2-semantic-cache"] as const;
export const CACHE_LIMIT = 25;

const STATUS_LABEL: Record<Provider["status"], string> = {
  unconfigured: "Not configured",
  healthy: "Healthy",
  cooldown: "Cooling down",
  circuit_open: "Circuit open",
};

export function providerTone(status: Provider["status"]) {
  if (status === "healthy") return "green" as const;
  if (status === "cooldown") return "amber" as const;
  if (status === "circuit_open") return "red" as const;
  return "neutral" as const;
}

export function cachePath(query: string, offset = 0) {
  const params = new URLSearchParams({
    kind: "screening_qa",
    limit: String(CACHE_LIMIT),
    offset: String(offset),
  });
  if (query.trim()) params.set("q", query.trim());
  return `v2/semantic-cache?${params}`;
}

const SOURCE_LABEL: Record<CacheEntry["source"], string> = {
  user: "You",
  profile: "Profile",
  llm: "LLM",
};

function ProviderCard({ provider }: { provider: Provider }) {
  const configured = provider.status !== "unconfigured";
  return (
    <div className="portal-status" aria-label={`${provider.label} status`}>
      <div className="split">
        <h3>{provider.label}</h3>
        <Badge tone={providerTone(provider.status)}>
          {STATUS_LABEL[provider.status]}
        </Badge>
      </div>
      <p className="muted small-print provider-model">{provider.model}</p>
      {configured ? (
        <>
          <QuotaBar
            label="Requests today"
            used={provider.requests_today}
            max={provider.rpd_limit}
            hit={provider.requests_today >= provider.rpd_limit}
          />
          <QuotaBar
            label="Requests this minute"
            used={provider.requests_this_minute}
            max={provider.rpm_limit}
            hit={provider.requests_this_minute >= provider.rpm_limit}
          />
          {provider.tpd_limit ? (
            <QuotaBar
              label="Tokens today"
              used={provider.tokens_today}
              max={provider.tpd_limit}
              hit={provider.tokens_today >= provider.tpd_limit}
            />
          ) : (
            <p className="muted small-print">
              {provider.tokens_today.toLocaleString("en-IN")} tokens today
            </p>
          )}
          {provider.circuit_open_until && provider.status !== "healthy" && (
            <p className="portal-hint">
              Skipped until {stamp(provider.circuit_open_until)}
              {provider.last_error ? ` · ${provider.last_error}` : ""}
            </p>
          )}
        </>
      ) : (
        <p className="muted small-print">
          Add <code>{provider.key_envs.join(" + ")}</code> to the private env
          file to enable. {provider.problem}
        </p>
      )}
    </div>
  );
}

export function AIRouterPanel() {
  const status = useQuery({
    queryKey: AI_STATUS_KEY,
    queryFn: () => api<AIStatus>("v2/ai/status"),
    refetchInterval: 30000,
  });
  if (status.isPending) return <Skeleton />;
  if (status.isError)
    return <ErrorState error={status.error} retry={() => status.refetch()} />;
  const { providers, chains, semantic_cache: cache } = status.data;
  const configured = providers.filter((p) => p.status !== "unconfigured");
  return (
    <section className="panel" aria-labelledby="ai-heading">
      <div className="panel-header">
        <div>
          <h2 id="ai-heading">AI router &amp; semantic cache</h2>
          <p>
            Profile facts answer first, then cached answers, then free external
            LLMs in failover order. Anything uncertain comes to you.
          </p>
        </div>
        <div className="tag-list">
          <Badge tone={configured.length ? "green" : "amber"}>
            {configured.length} of {providers.length} providers configured
          </Badge>
          <Badge tone="neutral">Local generative LLM: disabled</Badge>
        </div>
      </div>
      <div className="panel-body stack">
        {configured.length === 0 && (
          <div className="notice warn" role="status">
            No free LLM keys found. The worker still runs on profile facts and
            the semantic cache; unanswered questions come to you.
          </div>
        )}
        <dl className="worker-facts">
          <div>
            <dt>Cached answers</dt>
            <dd>{cache.total_entries.toLocaleString("en-IN")}</dd>
          </div>
          <div>
            <dt>Cache hits (LLM calls saved)</dt>
            <dd>{cache.total_hits.toLocaleString("en-IN")}</dd>
          </div>
          <div>
            <dt>Match threshold</dt>
            <dd>cosine ≥ {cache.threshold}</dd>
          </div>
          <div>
            <dt>Embedding model</dt>
            <dd>
              {cache.embedding_model}
              {cache.embedding_ready ? " · loaded" : " · loads on first use"}
            </dd>
          </div>
          <div>
            <dt>Cache storage</dt>
            <dd>
              {cache.backend === "postgres"
                ? "Supabase pgvector"
                : "In memory (apply migration 004)"}
            </dd>
          </div>
        </dl>
        <p className="muted small-print">
          Screening questions:{" "}
          {(chains.screening_qa ?? []).join(" → ") || "none"} · JD scoring:{" "}
          {(chains.jd_scoring ?? []).join(" → ") || "none"}
        </p>
        <div className="portal-grid">
          {providers.map((provider) => (
            <ProviderCard key={provider.provider} provider={provider} />
          ))}
        </div>
      </div>
    </section>
  );
}

function AddAnswerForm({ onSaved }: { onSaved: () => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const save = useMutation({
    mutationFn: () =>
      post<CacheEntry>("v2/semantic-cache", {
        kind: "screening_qa",
        question_text: question.trim(),
        answer_text: answer.trim(),
      }),
    onSuccess: () => {
      setQuestion("");
      setAnswer("");
      onSaved();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (question.trim().length >= 3 && answer.trim()) save.mutate();
  };
  return (
    <form className="cache-form" onSubmit={submit} aria-label="Add Q&A">
      <Field label="Question">
        <Input
          value={question}
          maxLength={1000}
          placeholder="e.g. Are you willing to work night shifts?"
          onChange={(e) => setQuestion(e.target.value)}
        />
      </Field>
      <Field label="Answer">
        <Input
          value={answer}
          maxLength={4000}
          placeholder="Exactly what should be filled in"
          onChange={(e) => setAnswer(e.target.value)}
        />
      </Field>
      <Button
        type="submit"
        variant="primary"
        busy={save.isPending}
        disabled={question.trim().length < 3 || !answer.trim()}
      >
        Add Q&amp;A
      </Button>
      <p
        className={save.isError ? "notice warn" : "notice"}
        role="status"
        aria-live="polite"
      >
        {save.isError
          ? save.error.message
          : save.isSuccess
            ? "Saved. Your answer outranks profile and LLM answers."
            : ""}
      </p>
    </form>
  );
}

function CacheRow({ entry }: { entry: CacheEntry }) {
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: () => del(`v2/semantic-cache/${entry.id}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: CACHE_KEY });
      client.invalidateQueries({ queryKey: AI_STATUS_KEY });
    },
  });
  return (
    <tr>
      <td className="reason-cell">{entry.question_text}</td>
      <td className="reason-cell">{entry.answer_text}</td>
      <td>
        <Badge tone={entry.source === "llm" ? "amber" : "green"}>
          {SOURCE_LABEL[entry.source]}
        </Badge>
      </td>
      <td>{entry.hits}</td>
      <td>
        <small>{stamp(entry.updated_at, "—")}</small>
      </td>
      <td>
        <Button
          variant="danger"
          busy={remove.isPending}
          aria-label={`Delete cached answer: ${entry.question_text}`}
          onClick={() => remove.mutate()}
        >
          Delete
        </Button>
        {remove.isError && (
          <small className="portal-hint" role="alert">
            {remove.error.message}
          </small>
        )}
      </td>
    </tr>
  );
}

export function SemanticCacheTable() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const page = useQuery({
    queryKey: [...CACHE_KEY, query, offset],
    queryFn: () => api<CachePage>(cachePath(query, offset)),
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: CACHE_KEY });
    client.invalidateQueries({ queryKey: AI_STATUS_KEY });
  };
  const total = page.data?.total ?? 0;
  return (
    <section className="spaced" aria-labelledby="cache-heading">
      <div className="split log-toolbar">
        <div className="section-heading">
          <h2 id="cache-heading">Cached screening answers</h2>
          <p className="muted">
            Reused for similar questions at zero tokens. Delete anything wrong;
            it is asked again next time.
          </p>
        </div>
        <div className="actions">
          <Field label="Search">
            <Input
              type="search"
              value={query}
              placeholder="Question or answer"
              onChange={(e) => {
                setQuery(e.target.value);
                setOffset(0);
              }}
            />
          </Field>
        </div>
      </div>
      <AddAnswerForm onSaved={refresh} />
      {page.isPending ? (
        <Skeleton />
      ) : page.isError ? (
        <ErrorState error={page.error} retry={() => page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <p className="muted spaced">
          {query
            ? "No cached answers match this search."
            : "No cached answers yet. Run seed-cache, add one above, or let the worker learn."}
        </p>
      ) : (
        <>
          <div className="table-wrap spaced">
            <table>
              <caption className="visually-hidden">
                Cached screening answers with source and hit count
              </caption>
              <thead>
                <tr>
                  <th scope="col">QUESTION</th>
                  <th scope="col">ANSWER</th>
                  <th scope="col">SOURCE</th>
                  <th scope="col">HITS</th>
                  <th scope="col">UPDATED</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.data.items.map((entry) => (
                  <CacheRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
          {total > CACHE_LIMIT && (
            <div className="actions spaced">
              <Button
                variant="ghost"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - CACHE_LIMIT))}
              >
                Previous
              </Button>
              <span className="muted small-print">
                {offset + 1}–{Math.min(offset + CACHE_LIMIT, total)} of {total}
              </span>
              <Button
                variant="ghost"
                disabled={offset + CACHE_LIMIT >= total}
                onClick={() => setOffset(offset + CACHE_LIMIT)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
