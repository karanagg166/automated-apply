import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PasteJobUrlCard } from "@/features/jobs";
import { post } from "@/lib/api";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  post: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
});

it("prepares a named destination once without silently starting a Naukri execution", async () => {
  vi.mocked(post).mockResolvedValue({ id: "packet-1" });
  render(<PasteJobUrlCard />);
  expect(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  ).toBeDisabled();
  await userEvent.type(
    screen.getByRole("textbox", { name: "Paste Job URL" }),
    "https://www.naukri.com/job-listings-fictional-281026123456",
  );
  await userEvent.type(
    screen.getByLabelText("Import company name"),
    "Fictional",
  );
  await userEvent.type(screen.getByLabelText("Import job title"), "Engineer");
  await userEvent.click(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  );
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(
    "application-packets/intake",
    expect.objectContaining({
      application_url:
        "https://www.naukri.com/job-listings-fictional-281026123456",
      company_name: "Fictional",
      job_title: "Engineer",
    }),
  );
  expect(push).toHaveBeenCalledWith("/applications/packet-1");
});

it("preserves an intake rejection without navigating or falling through", async () => {
  vi.mocked(post).mockRejectedValue(
    Error("Destination requires manual handoff"),
  );
  render(<PasteJobUrlCard />);
  await userEvent.type(
    screen.getByRole("textbox", { name: "Paste Job URL" }),
    "https://example.com/jobs/1",
  );
  await userEvent.type(
    screen.getByLabelText("Import company name"),
    "Fictional",
  );
  await userEvent.type(screen.getByLabelText("Import job title"), "Engineer");
  await userEvent.click(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  );
  expect(
    await screen.findByText("Destination requires manual handoff"),
  ).toBeVisible();
  expect(push).not.toHaveBeenCalled();
});
