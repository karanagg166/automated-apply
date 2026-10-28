import { test, expect } from "@playwright/test";
import { login } from "../e2e/owner-session";

test("Naukri imports a fictional posting and controls one durable intent without submission", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "Naukri", exact: true }).first().click();
  await expect(
    page.getByRole("heading", { name: "Naukri", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Automation mode" }),
  ).toHaveValue("ON_DEMAND");
  await page
    .getByLabel("Naukri posting URL")
    .fill("https://www.naukri.com/job-listings-phase51-fictional-291026123456");
  await page
    .getByLabel("Role from the posting")
    .fill("Phase51 Fictional Junior Software Engineer");
  await page
    .getByLabel("Employer from the posting")
    .fill("Phase51 Fictional Labs");
  await page
    .getByRole("button", { name: "Import posting", exact: true })
    .click();
  await expect(
    page.getByRole("link", {
      name: "Phase51 Fictional Junior Software Engineer",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Prepare selected job" })
    .last()
    .click();
  await expect(page.getByText("DISCOVERED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "pause", exact: true }).last().click();
  await expect(page.getByText("PAUSED", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "resume", exact: true })
    .last()
    .click();
  await expect(page.getByText("DISCOVERED", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "cancel", exact: true })
    .last()
    .click();
  await expect(page.getByText("FAILED FINAL", { exact: true })).toBeVisible();
  await expect(page.getByText(/Submission remains manual/)).toBeVisible();
  await page.screenshot({
    path: "test-results-browser/naukri-fictional.png",
    fullPage: true,
  });
});
