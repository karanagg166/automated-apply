import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Outreach, OutreachDetail } from "@/features/outreach";
import { api, patch, post } from "@/lib/api";
const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}));
const id = "11111111-1111-4111-8111-111111111111";
let draft: any;
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  draft = {
    id,
    subject: "Fictional introduction",
    body: "Reviewed fictional message.",
    recipient_email: "target@example.com",
    draft_revision: 3,
    approval_status: "draft_created",
    delivery_status: "not_attempted",
    created_at: "2026-01-01T00:00:00Z",
    outbound_messages_sent: 0,
    eligibility: { eligible_for_approval: true, blockers: [], warnings: [] },
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === `outreach/drafts/${id}`) return draft;
    if (path === "outreach/drafts?limit=100")
      return { drafts: [draft], total: 1 };
    if (path === "integrations/gmail/status")
      return {
        status: "connected",
        sending_enabled: true,
        send_capability: "send_authorized",
      };
    return {} as any;
  });
  vi.mocked(post).mockResolvedValue({});
  vi.mocked(patch).mockResolvedValue({});
});
function mount(detail = true) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {detail ? <OutreachDetail id={id} /> : <Outreach />}
    </QueryClientProvider>,
  );
}

it("preserves exact local approval while offering no send flow even when legacy status would authorize it", async () => {
  mount();
  const approve = await screen.findByRole("button", {
    name: "Approve exact content",
  });
  await waitFor(() => expect(approve).toBeEnabled());
  expect(
    screen.getByRole("status", {
      name: "Gmail Permission: Read + Draft Only (Sending Disabled)",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Gmail account and draft workspace" }),
  ).toHaveAttribute("href", "/connections");
  expect(
    screen.queryByRole("button", { name: /send/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalledWith("integrations/gmail/status");
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(approve);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(`outreach/drafts/${id}/approve`, {
      expected_revision: 3,
    }),
  );
  expect(
    vi.mocked(post).mock.calls.every(([path]) => path.endsWith("/approve")),
  ).toBe(true);
});

it("keeps a draft with a legacy send attempt immutable without calling removed send routes", async () => {
  draft.send_attempt_id = "retained-attempt";
  mount();
  expect(await screen.findByLabelText("Subject")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Approve exact content" }),
  ).toBeDisabled();
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path.startsWith("outreach/send-attempts/")),
  ).toBe(false);
  expect(
    screen.queryByText(/PRIVATE_CONFIRMATION_CANARY|PRIVATE_HASH_CANARY/),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
});

it("keeps the local draft list visible under the locked read and draft policy", async () => {
  mount(false);
  await screen.findByText("Fictional introduction");
  expect(screen.getByText(/Sending is disabled\./)).toBeInTheDocument();
  expect(
    screen.getByRole("status", {
      name: "Gmail Permission: Read + Draft Only (Sending Disabled)",
    }),
  ).toBeInTheDocument();
  expect(api).not.toHaveBeenCalledWith("outreach/history");
  expect(post).not.toHaveBeenCalled();
});
it("requires review and rechecks the saved revision before preparing a replacement local draft", async () => {
  const contact = "22222222-2222-4222-8222-222222222222",
    replacement = "33333333-3333-4333-8333-333333333333";
  draft.contact_id = contact;
  draft.job_id = null;
  draft.sent_at = null;
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "outreach/drafts" && options?.method === "POST"
      ? { ...draft, id: replacement, draft_revision: 1 }
      : original(path, options),
  );
  mount();
  const button = await screen.findByRole("button", {
    name: "Prepare another local draft",
  });
  expect(button).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed this saved draft/ }),
  );
  fireEvent.click(button);
  await waitFor(() =>
    expect(navigation.push).toHaveBeenCalledWith(`/outreach/${replacement}`),
  );
  const request = vi
    .mocked(api)
    .mock.calls.find(
      ([path, options]) =>
        path === "outreach/drafts" && options?.method === "POST",
    );
  expect(JSON.parse(request![1]!.body as string)).toMatchObject({
    contact_id: contact,
    use_llm: false,
  });
  expect(post).not.toHaveBeenCalled();
});
it("refuses replacement when the reviewed revision changes before the independent saved read", async () => {
  draft.contact_id = "22222222-2222-4222-8222-222222222222";
  draft.job_id = null;
  mount();
  const button = await screen.findByRole("button", {
    name: "Prepare another local draft",
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed this saved draft/ }),
  );
  vi.mocked(api).mockImplementation(async () => ({
    ...draft,
    draft_revision: 4,
  }));
  fireEvent.click(button);
  await screen.findByText(/The saved draft changed/);
  expect(navigation.push).not.toHaveBeenCalled();
  expect(
    vi
      .mocked(api)
      .mock.calls.some(
        ([path, options]) =>
          path === "outreach/drafts" && options?.method === "POST",
      ),
  ).toBe(false);
});
