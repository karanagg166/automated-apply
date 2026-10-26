import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { api, post } from "@/lib/api";
import { ProfileResources } from "@/features/profile-resources";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
it("saves a reviewed URL into the existing canonical resources and resets review after edits", async () => {
  vi.mocked(api).mockResolvedValue({ resources: [], resolved_links: [] });
  vi.mocked(post).mockResolvedValue({});
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ProfileResources />
    </QueryClientProvider>,
  );
  const save = screen.getByRole("button", {
    name: "Save reviewed profile link",
  });
  expect(save).toBeDisabled();
  await userEvent.type(
    screen.getByLabelText("Profile link label"),
    "LeetCode profile",
  );
  await userEvent.type(
    screen.getByLabelText("Reviewed profile URL"),
    "https://leetcode.com/u/fictional",
  );
  await userEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed this profile URL/ }),
  );
  expect(save).toBeEnabled();
  await userEvent.type(
    screen.getByLabelText("Reviewed profile URL"),
    "-reviewed",
  );
  expect(save).toBeDisabled();
  await userEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed this profile URL/ }),
  );
  await userEvent.click(save);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("candidate/resources", {
      resource_type: "leetcode",
      label: "LeetCode profile",
      url: "https://leetcode.com/u/fictional-reviewed",
      user_confirmed: true,
      is_primary: false,
    }),
  );
});
