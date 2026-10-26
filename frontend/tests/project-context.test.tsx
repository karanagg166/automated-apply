import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import { ProjectContext } from "@/features/project-context";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const configuration = {
  schema_version: 1,
  links: { other: [] },
  projects: [
    {
      id: "project-01",
      name: "",
      priority: 1,
      tech_stack: [],
      context_file: "",
      repository_url: null,
    },
  ],
};
const knowledge = {
  candidate: {
    revision: "fictional-revision",
    facts: [
      {
        id: "fact-1",
        text: "Uses FastAPI.",
        verification: "direct",
        evidence: [
          { file: "requirements.txt", content_sha256: "a".repeat(64) },
        ],
      },
      {
        id: "fact-2",
        text: "Invented scale.",
        verification: "inferred",
        evidence: [],
      },
    ],
    candidate_contexts: { explanation_100: "Uses FastAPI." },
  },
  approved: null,
};
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(post).mockReset();
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("configuration") ? { revision: 3, configuration } : knowledge,
  );
  vi.mocked(post).mockResolvedValue({});
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <ProjectContext />
    </QueryClientProvider>,
  );
}
it("leaves missing facts empty and saves explicit project importance", async () => {
  mount();
  const name = await screen.findByLabelText("Ranked project 1 name");
  expect(name).toHaveValue("");
  await userEvent.type(name, "Fictional service");
  await userEvent.click(
    screen.getByRole("button", { name: "Save ranked projects" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "dashboard/candidate-context/configuration",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const call = vi
    .mocked(api)
    .mock.calls.find(([, options]) => options?.method === "PUT")!;
  const payload = JSON.parse(call[1]!.body as string);
  expect(payload.expected_revision).toBe(3);
  expect(payload.configuration.projects[0]).toMatchObject({
    name: "Fictional service",
    priority: 1,
    tech_stack: [],
  });
});
it("requires explicit evidence selection and owner confirmation for the current revision", async () => {
  mount();
  const approve = await screen.findByRole("button", {
    name: "Approve selected project facts",
  });
  expect(approve).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: /Invented scale/ }),
  ).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: /Uses FastAPI/ }));
  expect(approve).toBeDisabled();
  await userEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed these facts/ }),
  );
  await userEvent.click(approve);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "dashboard/candidate-context/projects/project-01/approve",
      {
        expected_revision: "fictional-revision",
        fact_ids: ["fact-1"],
        owner_confirmed: true,
      },
    ),
  );
});
