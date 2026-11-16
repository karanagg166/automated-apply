import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { ContactReview, type ContactDetail } from "@/features/contact-review";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const contact: ContactDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  company_id: "22222222-2222-4222-8222-222222222222",
  company: "Fictional employer",
  full_name: "Fictional Person",
  role_title: "Engineering Manager",
  email_status: "provider_reported",
  email_evidence_status: "provider_reported",
  source: "manual",
  confidence: "supported",
  do_not_contact: false,
  manual_linkedin_available: false,
  manual_outreach_review_available: true,
  email_send_ready: false,
  retention_expired: false,
  review_version: "fixture:1",
  evidence: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      source: "manual",
      type: "human_correction",
      strength: "strong",
      url: "https://contact-fixture.example/team",
    },
  ],
};
function mount(value: ContactDetail = contact) {
  const onRefresh = vi.fn(async () => {}),
    onSaved = vi.fn();
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContactReview contact={value} onRefresh={onRefresh} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { onRefresh, onSaved };
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue({ ...contact, review_version: "fixture:2" });
});
it("requires reviewed corrections and sends the exact saved version without re-attesting unchanged mailbox status", async () => {
  const { onSaved } = mount();
  const user = userEvent.setup();
  const save = screen.getByRole("button", { name: "Save reviewed contact" });
  expect(save).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", {
      name: "Exclude this contact from outreach",
    }),
  );
  await user.type(screen.getByLabelText("Exclusion reason"), "Owner exclusion");
  await user.click(
    screen.getByRole("checkbox", {
      name: "I reviewed these contact corrections against the evidence",
    }),
  );
  await user.click(save);
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  const [path, options] = vi.mocked(api).mock.calls[0];
  expect(path).toBe(`contacts/${contact.id}`);
  expect(options?.method).toBe("PATCH");
  expect(options?.headers).toEqual({ "If-Match": "fixture:1" });
  const body = JSON.parse(options?.body as string);
  expect(body).toMatchObject({
    do_not_contact: true,
    suppression_reason: "Owner exclusion",
  });
  expect(body).not.toHaveProperty("email_status");
  expect(save).toBeDisabled();
  expect(screen.getByText(/Contact correction saved/)).toBeInTheDocument();
});
it("locks an uncertain correction and requires a fresh evidence load before repeating", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Fictional response loss"));
  const { onRefresh } = mount();
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("checkbox", {
      name: "I reviewed these contact corrections against the evidence",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "Save reviewed contact" }),
  );
  await screen.findByText("Fictional response loss");
  expect(vi.mocked(api)).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Save reviewed contact" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/network error may have occurred after saving/),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Reload current contact evidence" }),
  );
  expect(onRefresh).toHaveBeenCalledTimes(1);
});
it("requires current mailbox evidence to request a new verified status and never exposes sending", async () => {
  mount();
  const user = userEvent.setup();
  await user.selectOptions(
    screen.getByLabelText("Reviewed mailbox status"),
    "verified",
  );
  await user.click(
    screen.getByRole("checkbox", {
      name: "I reviewed these contact corrections against the evidence",
    }),
  );
  const save = screen.getByRole("button", { name: "Save reviewed contact" });
  expect(save).toBeDisabled();
  const evidence = "44444444-4444-4444-8444-444444444444";
  await user.type(
    screen.getByLabelText("Mailbox verification evidence ID"),
    evidence,
  );
  await user.click(save);
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(1));
  expect(
    JSON.parse(vi.mocked(api).mock.calls[0][1]?.body as string),
  ).toMatchObject({
    email_status: "verified",
    verification_evidence_id: evidence,
  });
  expect(
    screen.queryByRole("button", { name: /^send/i }),
  ).not.toBeInTheDocument();
});
it("refuses correction when the saved version is absent and renders selected evidence fields", () => {
  mount({ ...contact, review_version: undefined });
  expect(
    screen.queryByRole("button", { name: "Save reviewed contact" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Reload current contact evidence before/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Review evidence source" }),
  ).toHaveAttribute("href", "https://contact-fixture.example/team");
});
