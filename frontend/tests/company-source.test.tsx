import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { post } from "@/lib/api";
import { OpportunityContext } from "@/features/opportunity-context";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  post: vi.fn(),
}));
const source = "https://official.example:443/about";
const captured = {
  source_url: "https://careers.official.example/apply",
  company_source_url: source,
  company_source_title: "About Example Circuit",
  company_source_token: "b".repeat(64),
  company_name: "Example Circuit",
  job_title: "Backend Engineer",
  capture_digest: "a".repeat(64),
  expected_revision: 3,
  job_text: "The role involves Python services.",
  company_text: "Example Circuit builds Python tools.",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(post).mockResolvedValue(captured);
});

function mount(onSaved = vi.fn(async () => {}), ownerAvailable = true) {
  render(
    <OpportunityContext
      packetId="11111111-1111-4111-8111-111111111111"
      revision={3}
      blocked={false}
      ownerAvailable={ownerAvailable}
      setBusy={vi.fn()}
      onSaved={onSaved}
      sourceUrls={[source]}
    />,
  );
}

it("requires source permission and preserves the exact preview token through excerpt review", async () => {
  mount();
  const read = screen.getByRole("button", {
    name: "Read approved company source",
  });
  expect(read).toBeDisabled();
  await userEvent.selectOptions(
    screen.getByLabelText("Official public company page"),
    source,
  );
  expect(read).toBeDisabled();
  await userEvent.click(
    screen.getByLabelText(
      "I checked that this official page belongs to this employer and permits automated reading.",
    ),
  );
  await userEvent.click(read);
  expect(post).toHaveBeenCalledWith(
    expect.stringContaining("/company-source-preview"),
    {
      expected_revision: 3,
      source_url: source,
      confirm_public_source_permission: true,
    },
  );
  await screen.findByDisplayValue(captured.company_text);
  const save = screen.getByRole("button", {
    name: "Save reviewed job context",
  });
  expect(save).toBeDisabled();
  await userEvent.click(
    screen.getByLabelText(
      "I checked the company, job, source and selected excerpts.",
    ),
  );
  await userEvent.click(save);
  expect(post).toHaveBeenLastCalledWith(
    expect.stringContaining("/opportunity-approve"),
    expect.objectContaining({
      company_source_token: captured.company_source_token,
      capture_digest: captured.capture_digest,
      expected_revision: 3,
    }),
  );
});

it("announces saved context only after the packet refresh completes", async () => {
  let finish!: () => void;
  const onSaved = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  mount(onSaved);
  await userEvent.click(
    screen.getByRole("button", { name: "Capture job context" }),
  );
  await screen.findByDisplayValue(captured.company_text);
  await userEvent.click(
    screen.getByLabelText(
      "I checked the company, job, source and selected excerpts.",
    ),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Save reviewed job context" }),
  );
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(screen.queryByText(/Reviewed context saved/)).not.toBeInTheDocument();
  await act(async () => finish());
  await screen.findByText(/Reviewed context saved/);
});

it("cannot read a configured page without independent owner approval capability", async () => {
  mount(undefined, false);
  await userEvent.selectOptions(
    screen.getByLabelText("Official public company page"),
    source,
  );
  await userEvent.click(
    screen.getByLabelText(
      "I checked that this official page belongs to this employer and permits automated reading.",
    ),
  );
  expect(
    screen.getByRole("button", { name: "Read approved company source" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});
