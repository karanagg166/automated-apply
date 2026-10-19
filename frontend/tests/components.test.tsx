import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Button, Empty, ErrorState, External, Modal } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { sizeFilter } from "@/features/startups";
import { pipelineColumn } from "@/features/applications";
it("blocks a disabled prominent action", async () => {
  const click = vi.fn();
  render(
    <Button disabled onClick={click}>
      Send exact message
    </Button>,
  );
  await userEvent.click(screen.getByRole("button"));
  expect(click).not.toHaveBeenCalled();
});
it("offers an actionable empty state without fictional results", () => {
  render(
    <Empty
      title="No saved teams"
      description="Run an approved search."
      action={<Button>Discover</Button>}
    />,
  );
  expect(screen.getByRole("heading")).toHaveTextContent("No saved teams");
  expect(screen.getByRole("button", { name: "Discover" })).toBeEnabled();
});
it("makes provider and rate-limit failures visible", () => {
  render(<ErrorState error={new ApiError(429, "No credits available")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Rate limit reached");
  expect(screen.getByRole("alert")).toHaveTextContent("No credits available");
});
it("never links unsafe professional URLs", () => {
  render(<External href="javascript:alert(1)">Profile</External>);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("uses accessible dialog semantics", () => {
  render(
    <Modal
      open
      onOpenChange={() => {}}
      title="Review exact send"
      description="Review before authorizing."
    >
      <Button>Confirm</Button>
    </Modal>,
  );
  expect(
    screen.getByRole("dialog", { name: "Review exact send" }),
  ).toHaveAccessibleDescription("Review before authorizing.");
});
it("uses numeric evidence for exact 2–10", () => {
  expect(sizeFilter("2-10")).toMatchObject({
    min_employees: 2,
    max_employees: 10,
    exact_employee_count: true,
    include_unknown_size: false,
  });
});
it("keeps an opened application separate from submission", () => {
  expect(
    pipelineColumn({
      lifecycle_state: "external_application_opened",
      tracking_state: "not_applied",
    }),
  ).toBe("Approved / Manual Handoff");
  expect(
    pipelineColumn({
      lifecycle_state: "user_reported_submitted",
      tracking_state: "applied_manually",
    }),
  ).toBe("Applied — User Reported");
});

it("preserves larger and unrestricted size presets without inheriting the default 50-person cap", () => {
  expect(sizeFilter("51-200")).toMatchObject({
    max_employees: null,
    size_bands: ["51-200"],
    include_unknown_size: false,
  });
  expect(sizeFilter("all")).toMatchObject({
    max_employees: null,
    min_employees: null,
    size_bands: [],
  });
});
