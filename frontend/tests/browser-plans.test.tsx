import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { BrowserPlans } from "@/features/browser-plans";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
it("requires field selection and keeps missing facts untouched", async () => {
  vi.mocked(api).mockResolvedValue([
    {
      id: "plan",
      mode: "local_automation",
      state: "preview",
      expires_at: "2026-10-26T12:00:00Z",
      target_url: "https://jobs.lever.co/example/fictional",
      inspection: {
        fields: [
          { field_id: "f0", label: "Email" },
          { field_id: "f1", label: "Salary" },
        ],
      },
      actions: [
        {
          field_id: "f0",
          value: "alex@example.com",
          evidence: ["candidate_profile:fictional"],
          candidate_version: 2,
          needs_input: false,
          requires_review: true,
        },
        {
          field_id: "f1",
          value: null,
          evidence: [],
          candidate_version: 2,
          needs_input: true,
          requires_review: false,
        },
      ],
    },
  ]);
  vi.mocked(post).mockResolvedValue({});
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <BrowserPlans />
    </QueryClientProvider>,
  );
  const email = await screen.findByRole("checkbox", { name: "Email" });
  expect(screen.getByRole("checkbox", { name: "Salary" })).toBeDisabled();
  expect(email).not.toBeChecked();
  await userEvent.click(email);
  await userEvent.click(
    screen.getByRole("button", { name: "Approve selected fields for filling" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("browser/plans/plan/review", {
      field_ids: ["f0"],
    }),
  );
});
it("allows only bounded owner browser routes", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  expect(permittedRoute("browser/plans", "GET")).toBe(true);
  expect(permittedRoute(`browser/plans/${id}/review`, "POST")).toBe(true);
  expect(permittedRoute(`browser/plans/${id}/next`, "POST")).toBe(true);
  expect(permittedRoute("browser/stop", "POST")).toBe(true);
  expect(permittedRoute("browser/execute", "POST")).toBe(false);
  expect(permittedRoute(`browser/plans/${id}/submit`, "POST")).toBe(false);
});
