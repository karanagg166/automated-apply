import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  LiveEventsProvider,
  backoffDelay,
  parseLiveEvent,
  useLiveEvents,
} from "@/lib/live-events";
import { TELEMETRY_KEY } from "@/lib/ops-types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    this.listeners.set(type, handler);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown, id: string) {
    const event = new MessageEvent(type, {
      data: JSON.stringify(data),
      lastEventId: id,
    });
    this.listeners.get(type)?.(event);
  }
}

function Probe() {
  const { connection, events, lastEventId } = useLiveEvents();
  return (
    <div>
      <span data-testid="connection">{connection}</span>
      <span data-testid="count">{events.length}</span>
      <span data-testid="last">{lastEventId ?? ""}</span>
      <span data-testid="first">{events[0]?.type ?? ""}</span>
    </div>
  );
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("connects, records events, invalidates telemetry and reconnects with backoff", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <LiveEventsProvider>
        <Probe />
      </LiveEventsProvider>
    </QueryClientProvider>,
  );
  expect(FakeEventSource.instances).toHaveLength(1);
  const first = FakeEventSource.instances[0];
  expect(first.url).toBe("/api/backend/v2/events/stream");
  act(() => first.onopen?.());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");

  act(() =>
    first.emit(
      "job.applied",
      {
        type: "job.applied",
        at: "2026-11-28T09:00:00Z",
        payload: { company: "Stripe" },
      },
      "41",
    ),
  );
  expect(screen.getByTestId("count")).toHaveTextContent("1");
  expect(screen.getByTestId("first")).toHaveTextContent("job.applied");
  expect(screen.getByTestId("last")).toHaveTextContent("41");
  await act(async () => {
    vi.advanceTimersByTime(400);
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: [...TELEMETRY_KEY] });

  act(() => first.onerror?.());
  expect(first.closed).toBe(true);
  expect(screen.getByTestId("connection")).toHaveTextContent("reconnecting");
  await act(async () => {
    vi.advanceTimersByTime(backoffDelay(1));
  });
  expect(FakeEventSource.instances).toHaveLength(2);
  const second = FakeEventSource.instances[1];
  expect(second.url).toBe("/api/backend/v2/events/stream?last_event_id=41");
  act(() => second.onopen?.());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");
});

it("falls back to polling after repeated failures", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LiveEventsProvider>
        <Probe />
      </LiveEventsProvider>
    </QueryClientProvider>,
  );
  for (let failure = 1; failure <= 3; failure += 1) {
    const source = FakeEventSource.instances.at(-1)!;
    act(() => source.onerror?.());
    await act(async () => {
      vi.advanceTimersByTime(backoffDelay(failure));
    });
  }
  expect(screen.getByTestId("connection")).toHaveTextContent("polling");
  expect(FakeEventSource.instances).toHaveLength(4);
});

it("computes capped backoff and rejects unknown events", () => {
  expect(backoffDelay(1)).toBe(1000);
  expect(backoffDelay(3)).toBe(4000);
  expect(backoffDelay(20)).toBe(30000);
  expect(parseLiveEvent("message", "{not json", null)).toBeNull();
  expect(
    parseLiveEvent("bogus", JSON.stringify({ payload: {} }), null),
  ).toBeNull();
  expect(
    parseLiveEvent(
      "hitl.created",
      JSON.stringify({ payload: { kind: "OTP" } }),
      "7",
    ),
  ).toMatchObject({ id: "7", type: "hitl.created", payload: { kind: "OTP" } });
});
