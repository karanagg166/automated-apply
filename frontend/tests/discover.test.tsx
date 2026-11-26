import { render, screen } from "@testing-library/react";
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

it("shows the discovery automation panel without dispatching work", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);

  render(<Discover />);

  expect(
    screen.getByRole("heading", { name: "Discovery automation" }),
  ).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
