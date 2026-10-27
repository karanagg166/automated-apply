import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { resolve } from "node:path";

async function login(page: Page) {
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
}

test.describe.serial("Phase 2 Job Discovery Dashboard", () => {
  test("exercises Job Discovery UI, previews plan, and inspects Jobs table", async ({
    page,
  }) => {
    await login(page);

    // 1. Visit Discover page
    await page.goto("/discover");

    // Verify tabs are present
    const jobTab = page.getByRole("tab", { name: "Job discovery" });
    const startupTab = page.getByRole("tab", { name: "Startup discovery" });
    await expect(jobTab).toBeVisible();
    await expect(startupTab).toBeVisible();
    await expect(jobTab).toHaveClass(/selected/);

    // Verify Source Selector shows Arbeitnow and disabled providers
    const sourceSelect = page.getByRole("combobox", {
      name: "Discovery source provider",
    });
    await expect(sourceSelect).toBeVisible();

    // Fill search parameters
    const keywordsInput = page.getByRole("textbox", {
      name: "Role or technology keywords",
    });
    await keywordsInput.fill("Python, Backend");

    const locationsInput = page.getByRole("textbox", {
      name: "Search locations",
    });
    await locationsInput.fill("Remote, Berlin");

    const workplaceSelect = page.getByRole("combobox", {
      name: "Workplace preference",
    });
    await workplaceSelect.selectOption("remote");

    // Preview discovery plan
    const previewBtn = page.getByRole("button", {
      name: "Preview discovery plan",
    });
    await previewBtn.click();

    // Verify Preview evidence card appears with plan details
    const previewHeading = page.getByText("Review your job discovery plan");
    await expect(previewHeading).toBeVisible();
    await expect(page.getByText("Provider calls in preview: 0")).toBeVisible();
    await expect(page.getByText("Free ($0.00)")).toBeVisible();

    // Run button is disabled until consent
    const runBtn = page.getByRole("button", {
      name: "Run approved discovery",
    });
    await expect(runBtn).toBeDisabled();

    // Take screenshot of Job Discovery panel
    await page.screenshot({
      path: resolve("../reports/phase2-job-discovery.png"),
      fullPage: true,
    });

    // 2. Navigate to Jobs page
    await page.goto("/jobs");
    await expect(
      page.getByRole("heading", { name: "Work worth exploring." }),
    ).toBeVisible();

    // Verify Status tabs
    const notAppliedTab = page.getByRole("button", {
      name: "Not Applied",
      exact: true,
    });
    const shortlistedTab = page.getByRole("button", {
      name: "Shortlisted",
      exact: true,
    });
    const appliedTab = page.getByRole("button", {
      name: "Applied",
      exact: true,
    });
    await expect(notAppliedTab).toBeVisible();
    await expect(shortlistedTab).toBeVisible();
    await expect(appliedTab).toBeVisible();

    // Verify filter fields
    await expect(page.getByLabel("Job title")).toBeVisible();
    await expect(page.getByLabel("Job location")).toBeVisible();
    await expect(page.getByLabel("Job skill")).toBeVisible();
    await expect(page.getByLabel("Source platform")).toBeVisible();
    await expect(page.getByLabel("Workplace preference")).toBeVisible();

    // Take screenshot of Jobs table
    await page.screenshot({
      path: resolve("../reports/phase2-jobs-table.png"),
      fullPage: true,
    });

    // Accessibility check
    const a11y = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    const criticalViolations = a11y.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );
    expect(criticalViolations).toEqual([]);
  });
  test("retains an actual backend failure and inspects its saved status without creating jobs", async ({
    page,
  }) => {
    await login(page);
    const before = await page.request.get("/api/backend/jobs/search");
    expect(before.ok()).toBeTruthy();
    const initialCount = (await before.json()).total;
    await page.goto("/discover");
    await page.getByRole("button", { name: "Preview discovery plan" }).click();
    await page
      .getByRole("checkbox", { name: /Run this approved job discovery/ })
      .check();
    const execution = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/backend/discovery/runs") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Run approved discovery" }).click();
    const run = await (await execution).json();
    // The actual fixture backend denies every outbound provider request. It must
    // persist an honest failure, never invent a vacancy or a successful ingestion.
    expect(run.status).toBe("failed");
    expect(run.counts.inserted).toBe(0);
    const result = page.getByLabel("Discovery execution result");
    await expect(result).toContainText(
      "Discovery failed; no batch changes committed",
    );
    const inspection = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/backend/discovery/runs/${run.id}`) &&
        response.request().method() === "GET",
    );
    await result
      .getByRole("button", { name: "Refresh saved run status" })
      .click();
    expect((await (await inspection).json()).id).toBe(run.id);
    const after = await page.request.get("/api/backend/jobs/search");
    expect((await after.json()).total).toBe(initialCount);
  });
});
