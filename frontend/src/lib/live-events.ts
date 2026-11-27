"use client";
// Realtime ops stream: one EventSource per tab over the authenticated Next proxy, exponential
// backoff reconnect (the server ends each stream after ~75 s by design), Last-Event-ID resume
// and a polling fallback of v2/worker/telemetry while the stream is down.
import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  LIVE_EVENT_TYPES,
  TELEMETRY_KEY,
  TELEMETRY_PATH,
  type LiveConnection,
  type LiveEvent,
  type LiveEventType,
  type WorkerTelemetry,
} from "@/lib/ops-types";

export const STREAM_URL = "/api/backend/v2/events/stream";
export const MAX_EVENTS = 200;
export const BASE_BACKOFF_MS = 1000;
export const MAX_BACKOFF_MS = 30000;
/** Consecutive failures after which the UI says "polling" (it keeps retrying the stream). */
export const POLLING_AFTER_FAILURES = 3;

export const HITL_KEYS: QueryKey[] = [["v2-hitl-open"], ["v2-hitl-inbox"]];
const INVALIDATIONS: Partial<Record<LiveEventType, QueryKey[]>> = {
  "hitl.created": HITL_KEYS,
  "hitl.resolved": HITL_KEYS,
  "job.applied": [["v2-applications"], ["v2-applications-summary"]],
  "job.failed": [["v2-applications"]],
  "mail.reconciled": [["v2-applications"], ["v2-application-proof"]],
  "portal.breaker_changed": [["v2-portal-rules"], ["v2-status"]],
  "cache.decision": [["v2-semantic-cache-stats"]],
};

export function backoffDelay(failures: number) {
  return Math.min(
    BASE_BACKOFF_MS * 2 ** Math.max(failures - 1, 0),
    MAX_BACKOFF_MS,
  );
}

export function parseLiveEvent(
  type: string,
  data: string,
  id: string | null,
): LiveEvent | null {
  let body: { type?: string; at?: string; payload?: unknown };
  try {
    body = JSON.parse(data);
  } catch {
    return null;
  }
  const kind = (body.type || type) as LiveEventType;
  if (!LIVE_EVENT_TYPES.includes(kind)) return null;
  const payload =
    body.payload && typeof body.payload === "object"
      ? (body.payload as Record<string, unknown>)
      : {};
  return { id, type: kind, at: body.at || new Date().toISOString(), payload };
}

type LiveState = {
  connection: LiveConnection;
  events: LiveEvent[];
  lastEventId: string | null;
};
const LiveContext = createContext<LiveState>({
  connection: "polling",
  events: [],
  lastEventId: null,
});

export function LiveEventsProvider({
  children,
  url = STREAM_URL,
}: {
  children: ReactNode;
  url?: string;
}) {
  const client = useQueryClient();
  const [state, setState] = useState<LiveState>({
    connection: "connecting",
    events: [],
    lastEventId: null,
  });
  const lastId = useRef<string | null>(null);
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setState((s) => ({ ...s, connection: "polling" }));
      return;
    }
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let stopped = false;
    const pending = new Set<string>();
    let flush: ReturnType<typeof setTimeout> | undefined;
    const invalidate = (keys: QueryKey[]) => {
      keys.forEach((key) => pending.add(JSON.stringify(key)));
      if (flush) return;
      flush = setTimeout(() => {
        flush = undefined;
        pending.forEach((key) =>
          client.invalidateQueries({ queryKey: JSON.parse(key) as QueryKey }),
        );
        pending.clear();
      }, 300);
    };
    const onEvent = (message: MessageEvent) => {
      const event = parseLiveEvent(
        message.type,
        String(message.data),
        message.lastEventId || null,
      );
      if (!event) return;
      if (event.id) lastId.current = event.id;
      if (event.type === "resync") {
        client.invalidateQueries();
      } else {
        invalidate([TELEMETRY_KEY, ...(INVALIDATIONS[event.type] || [])]);
      }
      setState((s) => ({
        ...s,
        lastEventId: lastId.current,
        events: [event, ...s.events].slice(0, MAX_EVENTS),
      }));
    };
    const connect = () => {
      if (stopped) return;
      const target = lastId.current
        ? `${url}?last_event_id=${encodeURIComponent(lastId.current)}`
        : url;
      source = new EventSource(target, { withCredentials: true });
      source.onopen = () => {
        failures = 0;
        setState((s) => ({ ...s, connection: "live" }));
      };
      source.onmessage = onEvent;
      for (const type of LIVE_EVENT_TYPES)
        source.addEventListener(type, onEvent as EventListener);
      source.onerror = () => {
        source?.close();
        source = null;
        failures += 1;
        setState((s) => ({
          ...s,
          connection:
            failures >= POLLING_AFTER_FAILURES ? "polling" : "reconnecting",
        }));
        timer = setTimeout(connect, backoffDelay(failures));
      };
    };
    connect();
    return () => {
      stopped = true;
      source?.close();
      if (timer) clearTimeout(timer);
      if (flush) clearTimeout(flush);
    };
  }, [client, url]);
  return createElement(LiveContext.Provider, { value: state }, children);
}

export function useLiveEvents() {
  return useContext(LiveContext);
}

/** Telemetry snapshot: slow refresh while the stream is live, fast polling while it is down. */
export function useTelemetry() {
  const { connection } = useLiveEvents();
  return useQuery({
    queryKey: TELEMETRY_KEY,
    queryFn: () => api<WorkerTelemetry>(TELEMETRY_PATH),
    refetchInterval: connection === "live" ? 30000 : 5000,
    staleTime: 2000,
  });
}
