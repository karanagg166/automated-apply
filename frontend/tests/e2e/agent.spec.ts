import { test, expect } from "@playwright/test";
import { verifySubmissionReview } from "./submission-review";
test("dashboard command executes real fixture services, keeps followups, and cancels", async ({
  page,
  request,
}) => {
  expect((await request.get("/api/backend/agent/campaigns")).status()).toBe(
    401,
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/agent");
  await expect(
    page.getByRole("heading", { name: "Agent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Chrome form plans" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Stop filling applications" }),
  ).toBeVisible();
  await page
    .getByLabel("Command", { exact: true })
    .fill("Find backend jobs in India");
  await page.getByRole("button", { name: "Send command" }).click();
  const search = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Find backend jobs in India",
      exact: true,
    }),
  });
  await expect(search.getByText(/4 match your filters/)).toBeVisible({
    timeout: 20000,
  });
  await expect(search.getByRole("listitem")).toHaveCount(4);
  await page
    .getByLabel("Command", { exact: true })
    .fill("Only companies with 2–10 employees");
  await page.getByRole("button", { name: "Send command" }).click();
  const filtered = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Only companies with 2–10 employees",
      exact: true,
    }),
  });
  await expect(filtered.getByText(/1 match your filters/)).toBeVisible({
    timeout: 20000,
  });
  await page
    .getByLabel("Command", { exact: true })
    .fill("Apply to the first one");
  await page.getByRole("button", { name: "Send command" }).click();
  const pending = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Apply to the first one",
      exact: true,
    }),
  });
  await expect(
    pending.getByRole("button", { name: "Approve 1 local drafts only" }),
  ).toBeVisible({ timeout: 20000 });
  await pending.getByRole("button", { name: "Cancel campaign" }).click();
  await expect(pending.getByText("cancelled", { exact: true })).toBeVisible();
  await page.reload();
  await expect(search.getByRole("listitem")).toHaveCount(4);
  await expect(pending.getByText("cancelled", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../reports/command-execution-dashboard.png",
    fullPage: true,
  });
  await page
    .getByLabel("Command", { exact: true })
    .fill("Fill the first application");
  await page.getByRole("button", { name: "Send command" }).click();
  const campaign = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Fill the first application",
      exact: true,
    }),
  });
  await expect(
    campaign.getByText(/previous selection is unavailable/).first(),
  ).toBeVisible({ timeout: 20000 });
  await expect(campaign.getByText(/Zero submissions were made/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Chrome form plans" }),
  ).toBeVisible();
  await verifySubmissionReview(page);
});
