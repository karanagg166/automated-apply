import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import {
  PublicDiscovery,
  type WorkflowRequest,
} from "../src/features/public-discovery";
const initial = {
  policy: { revision: 3, enabled: [] },
  last_status: null,
  application_dispatch: false,
};
describe("public discovery controls", () => {
  it("loads without enabling work and saves only explicit revisioned settings", async () => {
    const user = userEvent.setup();
    const request = vi.fn(
      async (path: string, method = "GET", body?: unknown) =>
        method === "PUT"
          ? { ...initial, policy: { revision: 4, enabled: ["himalayas"] } }
          : initial,
    );
    render(<PublicDiscovery request={request as WorkflowRequest} />);
    await screen.findByText("Find remote jobs");
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Himalayas" })).toBeEnabled(),
    );
    expect(request).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("checkbox", { name: "Himalayas" }));
    expect(request).toHaveBeenCalledTimes(1);
    await user.click(
      screen.getByRole("button", { name: "Save discovery settings" }),
    );
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith("discovery/schedule", "PUT", {
        expected_revision: 3,
        enabled: ["himalayas"],
      }),
    );
  });
  it("preserves original provider link and explicitly saves only the returned batch token", async () => {
    const user = userEvent.setup();
    const link = "https://himalayas.app/jobs/role?ref=original#apply";
    const request = vi.fn(async (path: string) =>
      path.endsWith("/discover")
        ? {
            batch_token: "fixture-token",
            jobs: [
              {
                source_id: "fixture",
                title: "Rust Engineer",
                company_name: "Example",
                application_url: link,
                source_url: "https://himalayas.app/jobs/role",
                description: "<script>untrusted source text</script>",
                description_truncated: true,
              },
            ],
          }
        : path.endsWith("/ingest")
          ? { inserted_count: 1, duplicate_count: 0, expired_count: 0 }
          : initial,
    );
    render(<PublicDiscovery request={request as WorkflowRequest} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Find jobs on Himalayas" }),
      ).toBeEnabled(),
    );
    await user.click(
      screen.getByRole("button", { name: "Find jobs on Himalayas" }),
    );
    expect(
      await screen.findByRole("link", { name: "Rust Engineer" }),
    ).toHaveAttribute("href", link);
    expect(request.mock.calls.some(([path]) => path.endsWith("/ingest"))).toBe(
      false,
    );
    await user.click(
      screen.getByRole("button", {
        name: "Save Himalayas listings for review",
      }),
    );
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        "platforms/himalayas/ingest",
        "POST",
        { batch_token: "fixture-token" },
      ),
    );
    expect(
      await screen.findByText(
        "Saved 1 new listings; 0 already saved; 0 expired.",
      ),
    ).toBeVisible();
  });
  it("does not retry a failed save or fabricate success", async () => {
    const user = userEvent.setup();
    const request = vi.fn(async (_path: string, method = "GET") => {
      if (method === "PUT")
        throw Error("The saved state changed. Refresh first.");
      return initial;
    });
    render(<PublicDiscovery request={request as WorkflowRequest} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save discovery settings" }),
      ).toBeEnabled(),
    );
    await user.click(
      screen.getByRole("button", { name: "Save discovery settings" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh first");
    expect(
      request.mock.calls.filter(([, method]) => method === "PUT"),
    ).toHaveLength(1);
    expect(
      screen.queryByText("Discovery settings saved."),
    ).not.toBeInTheDocument();
  });
});
