import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Naukri } from "@/features/naukri";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "execution/naukri")
      return {
        configuration: {
          mode: "ON_DEMAND",
          interval_seconds: 21600,
          source: "saved_owner_imports",
          destinations: [],
          submission_permission: false,
        },
        executions: [],
        capabilities: {},
      };
    if (path === "execution/naukri/jobs") return { jobs: [] };
    if (path === "execution/questions") return [];
    throw Error(path);
  });
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Naukri />
    </QueryClientProvider>,
  );
}
it("defaults to on demand and does not start unattended work on mount", async () => {
  mount();
  await screen.findByRole("heading", { name: "Naukri" });
  expect(screen.getByRole("combobox", { name: "Automation mode" })).toHaveValue(
    "ON_DEMAND",
  );
  expect(screen.getByText(/Submission remains manual/)).toBeVisible();
  expect(post).not.toHaveBeenCalled();
});
it("imports only owner provided posting facts", async () => {
  mount();
  await screen.findByRole("heading", { name: "Naukri" });
  await userEvent.type(
    screen.getByLabelText("Naukri posting URL"),
    "https://www.naukri.com/job-listings-fictional-281026123456",
  );
  await userEvent.type(
    screen.getByLabelText("Role from the posting"),
    "Junior Software Engineer",
  );
  await userEvent.type(
    screen.getByLabelText("Employer from the posting"),
    "Fictional Circuit",
  );
  await userEvent.click(screen.getByRole("button", { name: "Import posting" }));
  expect(post).toHaveBeenCalledWith("execution/naukri/import", {
    jobs: [
      {
        url: "https://www.naukri.com/job-listings-fictional-281026123456",
        title: "Junior Software Engineer",
        employer: "Fictional Circuit",
      },
    ],
  });
});
it("allows only the fixed owner routes and no submit proxy", () => {
  expect(permittedRoute("execution/naukri", "PUT")).toBe(true);
  expect(permittedRoute("execution/naukri/import", "POST")).toBe(true);
  expect(permittedRoute("execution/naukri/submit", "POST")).toBe(false);
  expect(permittedRoute("execution/other/import", "POST")).toBe(false);
});
