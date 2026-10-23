import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post, type Schema } from "@/lib/api";
import { BrowserAssistant } from "@/features/browser-assistant";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const packet = {
  id: "11111111-1111-4111-8111-111111111111",
  revision: 1,
  lifecycle_state: "needs_input",
} as Schema<"PacketRead">;
const policy = {
  origins: ["https://static.employer.example:443"],
  digest: "a".repeat(64),
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BrowserAssistant packet={packet} />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(policy);
  vi.mocked(post).mockResolvedValue({
    packet,
    connected: true,
    manual: false,
    analysis: null,
  });
});

it("requires visible approval of the configured asset origins and sends their exact policy digest", async () => {
  mount();
  await userEvent.click(
    screen.getByLabelText("I approve a dedicated browser profile", {
      exact: false,
    }),
  );
  await screen.findByText(/static\.employer\.example/);
  const open = screen.getByRole("button", { name: "Open dedicated browser" });
  expect(open).toBeDisabled();
  await userEvent.click(
    screen.getByLabelText("I approve credential-free loading", {
      exact: false,
    }),
  );
  await userEvent.click(open);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `browser-applications/${packet.id}/open`,
      expect.objectContaining({
        confirm_asset_permissions: true,
        asset_policy_digest: policy.digest,
        approve_dedicated_profile: true,
        confirm_destination_permission: true,
      }),
    ),
  );
});

it("invalidates the asset approval if the advertised policy changes", async () => {
  const client = mount();
  await screen.findByText(/static\.employer\.example/);
  await userEvent.click(
    screen.getByLabelText("I approve a dedicated browser profile", {
      exact: false,
    }),
  );
  await userEvent.click(
    screen.getByLabelText("I approve credential-free loading", {
      exact: false,
    }),
  );
  expect(
    screen.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeEnabled();
  act(() =>
    client.setQueryData(["browser-policy"], {
      origins: ["https://other-static.example:443"],
      digest: "b".repeat(64),
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByLabelText("I approve credential-free loading", {
        exact: false,
      }),
    ).not.toBeChecked(),
  );
  expect(
    screen.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});

it("blocks filling unsaved edits and requires fresh value/context review after saving", async () => {
  vi.mocked(post).mockResolvedValue({
    packet,
    connected: true,
    manual: false,
    analysis: {
      fields: [],
      warnings: [],
      validation: [],
      diagnostic: "analyzed",
    },
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const node = (dirty: boolean) => (
    <QueryClientProvider client={client}>
      <BrowserAssistant packet={packet} hasUnsavedAnswers={dirty} />
    </QueryClientProvider>
  );
  const { rerender } = render(node(false));
  await userEvent.click(
    screen.getByLabelText("I approve a dedicated browser profile", {
      exact: false,
    }),
  );
  await screen.findByText(/static\.employer\.example/);
  await userEvent.click(
    screen.getByLabelText("I approve credential-free loading", {
      exact: false,
    }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Open dedicated browser" }),
  );
  await screen.findByText("analyzed", { exact: true });
  const reviewed = () =>
    screen.getByLabelText(
      "I reviewed the current answers, destination and selected resume below.",
    );
  const context = () =>
    screen.getByLabelText(
      "I confirmed the actual page belongs to this company and job.",
    );
  await userEvent.click(reviewed());
  await userEvent.click(context());
  const fill = screen.getByRole("button", { name: "Fill supported fields" });
  expect(fill).toBeEnabled();
  rerender(node(true));
  await userEvent.click(reviewed());
  await userEvent.click(context());
  expect(fill).toBeDisabled();
  rerender(node(false));
  await waitFor(() => expect(reviewed()).not.toBeChecked());
  expect(context()).not.toBeChecked();
  expect(fill).toBeDisabled();
  expect(post).toHaveBeenCalledTimes(1);
});
