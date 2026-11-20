import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Discover } from "@/features/discover";

vi.mock("@/features/automation", () => ({
  Automation: () => <h2>Discovery automation</h2>,
}));
vi.mock("@/features/job-discovery", () => ({ JobDiscovery: () => null }));
vi.mock("@/features/search-preferences", () => ({
  SearchPreferencesEditor: () => null,
}));

afterEach(() => vi.unstubAllGlobals());

it("reads the native discovery schedule without dispatching work", async () => {
  const fetch = vi.fn().mockResolvedValue(
    Response.json({
      policy: { revision: 3, enabled: ["himalayas"] },
      last_status: null,
      application_dispatch: false,
    }),
  );
  vi.stubGlobal("fetch", fetch);

  render(<Discover nativeRuntime />);

  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Himalayas" })).toBeChecked(),
  );
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "/api/workflow/discovery/schedule",
    expect.objectContaining({ method: "GET", credentials: "same-origin" }),
  );
  expect(
    screen.queryByRole("heading", { name: "Discovery automation" }),
  ).not.toBeInTheDocument();
});

it("keeps the discovery automation panel for the compatibility runtime", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);

  render(<Discover nativeRuntime={false} />);

  expect(
    screen.getByRole("heading", { name: "Discovery automation" }),
  ).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
