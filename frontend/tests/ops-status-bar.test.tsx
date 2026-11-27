import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  OpsStatusBar,
  durationLabel,
  telegramLabel,
} from "@/features/ops-status-bar";
import { api, post } from "@/lib/api";
import { telemetry } from "./ops-fixtures";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

function wrap(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Tooltip.Provider>{node}</Tooltip.Provider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(post).mockReset();
});

it("requires typing LIVE before disabling dry-run", async () => {
  vi.mocked(api).mockResolvedValue(telemetry());
  vi.mocked(post).mockResolvedValue({});
  const user = userEvent.setup();
  wrap(<OpsStatusBar />);
  const toggle = await screen.findByRole("switch", { name: "Dry-run mode" });
  expect(toggle).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByRole("status", { name: "Worker Dry-run" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      /Applying: Stripe — Backend Engineer \(Step: Filling form · 14s\)/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "4 pending HITL requests" }),
  ).toHaveAttribute("href", "/hitl");

  await user.click(toggle);
  const dialog = await screen.findByRole("dialog", { name: "Go live?" });
  const disable = within(dialog).getByRole("button", {
    name: "Disable dry-run",
  });
  expect(disable).toBeDisabled();
  await user.type(
    within(dialog).getByLabelText(/Type LIVE to confirm/),
    "live",
  );
  expect(disable).toBeDisabled();
  await user.clear(within(dialog).getByLabelText(/Type LIVE to confirm/));
  await user.type(
    within(dialog).getByLabelText(/Type LIVE to confirm/),
    "LIVE",
  );
  expect(disable).toBeEnabled();
  await user.click(disable);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/worker/dry-run", {
      dry_run: false,
      confirm: "LIVE",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});

it("enables dry-run immediately and mutes Telegram", async () => {
  vi.mocked(api).mockResolvedValue(
    telemetry({
      status: "RUNNING",
      worker: { ...telemetry().worker, dry_run: false },
    }),
  );
  vi.mocked(post).mockResolvedValue({});
  const user = userEvent.setup();
  wrap(<OpsStatusBar />);
  await user.click(await screen.findByRole("switch", { name: "Dry-run mode" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(post).toHaveBeenCalledWith("v2/worker/dry-run", { dry_run: true });
  await user.click(screen.getByRole("button", { name: "Mute 1h" }));
  expect(post).toHaveBeenCalledWith("v2/telegram/mute", { minutes: 60 });
  await user.click(screen.getByRole("button", { name: "Pause worker" }));
  expect(post).toHaveBeenCalledWith("v2/worker/pause", {});
});

it("shows offline when telemetry fails", async () => {
  vi.mocked(api).mockRejectedValue(new Error("down"));
  wrap(<OpsStatusBar />);
  expect(await screen.findByText("Worker offline")).toBeInTheDocument();
});

it("formats Telegram and duration labels", () => {
  const t = telemetry().telegram;
  expect(telegramLabel(t).label).toBe("Telegram active");
  expect(telegramLabel({ ...t, quiet_hours_active: true }).label).toBe(
    "Quiet hours",
  );
  expect(
    telegramLabel({ ...t, muted_until: "2099-01-01T10:30:00Z" }).label,
  ).toMatch(/^Muted until \d\d:\d\d$/);
  expect(telegramLabel({ ...t, configured: false }).label).toBe("Telegram off");
  expect(durationLabel(14)).toBe("14s");
  expect(durationLabel(125)).toBe("2m 5s");
  expect(durationLabel(null)).toBe("");
});
