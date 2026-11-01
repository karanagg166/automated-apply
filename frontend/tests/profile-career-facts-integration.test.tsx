import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { ProfileWizard } from "@/features/profile";
import { api, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
vi.mock("@/features/profile-resources", () => ({
  ProfileResources: () => null,
}));
vi.mock("@/features/project-context", () => ({ ProjectContext: () => null }));
vi.mock("@/features/resume-sync", () => ({ ResumeSync: () => null }));
vi.mock("@/features/approved-answers", () => ({ ApprovedAnswers: () => null }));

beforeEach(() => vi.clearAllMocks());

it("has one current-location answer and confirms only its newly saved reviewed version", async () => {
  let profile = {
    id: "fictional-profile",
    version: 7,
    full_name: "Alex Example",
    email: "alex@example.org",
    verified_skills: ["Python"],
    verified_roles: [],
    education: [],
    projects: [],
    preferences: { current_location: null as string | null },
  };
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === "profile") {
      if (options?.method === "PATCH") {
        const body = JSON.parse(String(options.body));
        profile = { ...profile, version: 8, preferences: body.preferences };
      }
      return profile;
    }
    if (path === "dashboard/onboarding/manifest") return { resources: [] };
    if (path === "candidate/resources") return { resources: [] };
    if (path === "dashboard/resumes") return { resumes: [] };
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.mocked(post).mockResolvedValue({ confirmed: true });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ProfileWizard />
    </QueryClientProvider>,
  );
  await screen.findByDisplayValue("Alex Example");
  const user = userEvent.setup();
  await user.click(
    screen.getByText("Private application facts", { exact: true }),
  );
  expect(screen.getAllByLabelText("Current location")).toHaveLength(1);
  await user.type(screen.getByLabelText("Current location"), "Fictional City");
  expect(
    screen.getByRole("button", { name: "Save reviewed career facts" }),
  ).toBeDisabled();
  await user.click(
    screen.getByLabelText(/I reviewed these private career facts/),
  );
  await user.click(
    screen.getByRole("button", { name: "Save reviewed career facts" }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("local-agent/profile-confirmation", {
      expected_version: 8,
      owner_confirmed: true,
    }),
  );
  const saved = vi
    .mocked(api)
    .mock.calls.find(
      ([path, options]) => path === "profile" && options?.method === "PATCH",
    );
  expect(saved?.[1]?.headers).toEqual({ "If-Match": '"7"' });
  expect(
    JSON.parse(String(saved?.[1]?.body)).preferences.current_location,
  ).toBe("Fictional City");
  await user.click(screen.getByRole("button", { name: /Search preferences/ }));
  expect(screen.getAllByLabelText("Current location")).toHaveLength(1);
  client.clear();
});
