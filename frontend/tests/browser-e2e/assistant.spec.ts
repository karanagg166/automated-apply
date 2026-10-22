import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("owner dashboard analyzes and fills using real FastAPI, PostgreSQL and a dedicated browser", async ({
  page,
  request,
}) => {
  const { packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  expect(
    (
      await request.get(`/api/backend/browser-applications/${packet_id}`)
    ).status(),
  ).toBe(401);
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${packet_id}`);
  await expect(
    page.getByRole("heading", { name: "Local browser assistant" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeDisabled();
  await page
    .getByLabel("I approve a dedicated browser profile", { exact: false })
    .check();
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeEnabled({ timeout: 45000 });
  await page.getByRole("button", { name: "Analyze Application" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /^analyzed$/ }),
  ).toBeVisible({ timeout: 45000 });
  await expect(
    page.getByRole("button", { name: "Fill supported fields" }),
  ).toBeDisabled();
  await page
    .getByLabel(
      "I reviewed the current answers, destination and selected resume below.",
    )
    .check();
  await page
    .getByLabel("I confirmed the actual page belongs to this company and job.")
    .check();
  await page.getByRole("button", { name: "Fill supported fields" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "filled review on website" }),
  ).toBeVisible({ timeout: 45000 });
  await expect(
    page.getByText("Current CTC: Answer missing or invalid", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Submit", exact: true }),
  ).toBeDisabled();
  // The authenticated BFF also rejects a missing CSRF proof for privileged browser actions.
  const status = await page.evaluate(
    async (id) =>
      (
        await fetch(`/api/backend/browser-applications/${id}/actions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "submit", expected_revision: 2 }),
        })
      ).status,
    packet_id,
  );
  expect(status).toBe(403);
  await page.getByRole("button", { name: "Take Over", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Fill supported fields" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeDisabled();
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("fictional-browser-demo-owner-token");
});
