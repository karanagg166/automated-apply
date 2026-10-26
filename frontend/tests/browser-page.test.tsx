import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { post } from "@/lib/api";
import { BrowserPage } from "@/features/browser-page";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  post: vi.fn(),
}));
const view = {
  expected_revision: 3,
  capture_digest: "a".repeat(64),
  display_url: "https://employer.example/step-2",
  title: "Example Engineer",
  heading: "Example Engineer",
  warning: "Page networking is paused.",
  questions: [{ question: "Email", required: true, supported: true }],
};

it("requires a reviewed current page and independent owner approval before resuming", async () => {
  vi.mocked(post)
    .mockReset()
    .mockResolvedValueOnce(view)
    .mockResolvedValueOnce({});
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(
    <BrowserPage
      packetId="packet"
      revision={3}
      blocked={false}
      ownerAvailable
      setBusy={vi.fn()}
      refresh={refresh}
    />,
  );
  await userEvent.click(screen.getByText("Resume after manual navigation"));
  await userEvent.click(
    screen.getByRole("button", { name: "Preview current page" }),
  );
  const resume = await screen.findByRole("button", {
    name: "Authorize page and analyze",
  });
  expect(resume).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(resume);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "browser-applications/packet/resume-page",
      {
        expected_revision: 3,
        capture_digest: view.capture_digest,
        confirm_same_application: true,
      },
    ),
  );
  expect(refresh).toHaveBeenCalled();
});

it("keeps resumption disabled without owner authority", async () => {
  vi.mocked(post).mockReset().mockResolvedValue(view);
  render(
    <BrowserPage
      packetId="packet"
      revision={3}
      blocked={false}
      ownerAvailable={false}
      setBusy={vi.fn()}
      refresh={vi.fn().mockResolvedValue(undefined)}
    />,
  );
  await userEvent.click(screen.getByText("Resume after manual navigation"));
  await userEvent.click(
    screen.getByRole("button", { name: "Preview current page" }),
  );
  await screen.findByRole("button", { name: "Authorize page and analyze" });
  await userEvent.click(screen.getByRole("checkbox"));
  expect(
    screen.getByRole("button", { name: "Authorize page and analyze" }),
  ).toBeDisabled();
});
