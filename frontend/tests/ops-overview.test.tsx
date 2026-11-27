import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { OpsOverview, eventCategory } from "@/features/ops-overview";
import { api, patch, post } from "@/lib/api";
import { telemetry } from "./ops-fixtures";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api).mockImplementation(async (path: string) =>
    path === "v2/portal-rules"
      ? [{ platform: "greenhouse", revision: 7 }]
      : telemetry(),
  );
  vi.mocked(post).mockResolvedValue({});
  vi.mocked(patch).mockResolvedValue({});
});

it("renders KPIs and drives the portal control grid", async () => {
  const user = userEvent.setup();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OpsOverview />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("MEDIAN FIRST-MOVER LAG")).toBeInTheDocument();
  expect(screen.getByText("7m 0s")).toBeInTheDocument();
  expect(screen.getByText("62%")).toBeInTheDocument();
  expect(
    screen.getByText("DOM_CHANGED:ats_submit_control_2"),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: /reset greenhouse circuit breaker/i }),
  );
  expect(post).toHaveBeenCalledWith("v2/portal-rules/greenhouse/breaker/reset");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /pause greenhouse/i }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: /pause greenhouse/i }));
  expect(patch).toHaveBeenCalledWith(
    "v2/portal-rules/greenhouse",
    expect.objectContaining({ revision: 7, paused_until: expect.any(String) }),
  );
});

it("categorizes live events for the feed filters", () => {
  const at = "2026-11-28T09:00:00Z";
  expect(
    eventCategory({ id: null, type: "job.applied", at, payload: {} }),
  ).toBe("applied");
  expect(
    eventCategory({ id: null, type: "hitl.created", at, payload: {} }),
  ).toBe("hitl");
  expect(eventCategory({ id: null, type: "job.failed", at, payload: {} })).toBe(
    "errors",
  );
  expect(
    eventCategory({
      id: null,
      type: "job.discovered",
      at,
      payload: { state: "FILTERED_OUT" },
    }),
  ).toBe("skipped");
});
