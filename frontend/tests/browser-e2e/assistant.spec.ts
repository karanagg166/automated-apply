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

test("owner authorizes a mock application and sees the independently verified receipt", async ({
  page,
}) => {
  const { mock_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${mock_packet_id}`);
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
  await page
    .getByLabel("I confirmed the actual page belongs to this company and job.")
    .check();
  await page
    .getByRole("button", {
      name: "Select on website: I consent to data processing",
    })
    .click();
  await page.getByRole("button", { name: "Review exact submission" }).click();
  await expect(
    page.getByText("I consent to data processing", { exact: false }).last(),
  ).toBeVisible();
  await page
    .getByLabel("I reviewed this selected consent or answer:", { exact: false })
    .check();
  await page
    .getByLabel("I authorize this exact fictional application", {
      exact: false,
    })
    .check();
  await page.getByRole("button", { name: "Authorize mock submission" }).click();
  await expect(
    page.getByRole("button", { name: "Submit", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Mock submission: verified" }),
  ).toBeVisible({ timeout: 45000 });
  await expect(
    page.getByText("Verified mock receipt: MOCK-", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Get status" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Mock submission: verified" }),
  ).toBeVisible();
});

test("reviewed employer context grounds an AI proposal and fills the actual fictional form", async ({
  page,
}) => {
  const { opportunity_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${opportunity_packet_id}`);
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
  ).toBeVisible();
  await page
    .getByText("Company and job evidence for AI answers", { exact: true })
    .click();
  await page.getByRole("button", { name: "Capture job context" }).click();
  await expect(page.getByLabel("Reviewed company excerpt")).toHaveValue(
    "Example Circuit Context builds task management tools.",
  );
  await page
    .getByLabel("I checked the company, job, source and selected excerpts.")
    .check();
  await page.getByRole("button", { name: "Save reviewed job context" }).click();
  await expect(
    page.getByText("Reviewed context saved.", { exact: false }),
  ).toBeVisible();
  const question = page
    .locator(".evidence-item")
    .filter({ hasText: "Why do you want to join our company?" })
    .first();
  await question
    .getByRole("button", { name: "Generate with configured AI" })
    .click();
  await expect(question.getByLabel("Reviewable answer")).toHaveValue(
    "Example Circuit Context builds task management tools. I built backend authentication using Python and FastAPI.",
  );
  for (const checkbox of await page
    .getByLabel("I reviewed this exact answer")
    .all())
    await checkbox.check();
  await page.getByLabel("I reviewed the selected resume variant.").check();
  await page
    .getByLabel("I verified this is the official application destination.")
    .check();
  await page.getByRole("button", { name: "Save field review" }).click();
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
  ).toBeVisible();
  await page.goto("/profile");
  await page.getByText("Reviewed application answers", { exact: true }).click();
  await page.getByRole("button", { name: "View employer evidence" }).click();
  await expect(
    page.locator("blockquote").filter({
      hasText: "Example Circuit Context builds task management tools.",
    }),
  ).toBeVisible();
});

test("owner manages protected career facts and signed answer reuse with PostgreSQL persistence", async ({
  page,
}) => {
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/profile");
  await page.getByText("Reviewed application answers", { exact: true }).click();
  await page
    .getByRole("checkbox", {
      name: "I reviewed this answer, its evidence and reuse scope.",
    })
    .check();
  await page.getByRole("button", { name: "Approve answer reuse" }).click();
  await expect(
    page.getByRole("button", { name: "Revoke reuse approval" }),
  ).toBeVisible();
  await page.reload();
  await page.getByText("Reviewed application answers", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Revoke reuse approval" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Revoke reuse approval" }).click();
  await expect(
    page.getByRole("button", { name: "Approve answer reuse" }),
  ).toBeVisible();
  await page.getByText("Private application facts", { exact: true }).click();
  await page
    .getByLabel("Current compensation amount", { exact: true })
    .fill("1200000");
  await page
    .getByLabel("Current compensation currency", { exact: true })
    .fill("INR");
  await page
    .getByLabel("Current compensation period", { exact: true })
    .selectOption("year");
  await page
    .getByLabel("Current compensation type", { exact: true })
    .selectOption("ctc");
  await page
    .getByRole("checkbox", {
      name: "I reviewed these private career facts and their units.",
    })
    .check();
  await page
    .getByRole("button", { name: "Save reviewed career facts" })
    .click();
  await expect(page.getByText("Saved · version 2")).toBeVisible();
  await page.reload();
  await page.getByText("Private application facts", { exact: true }).click();
  await expect(
    page.getByLabel("Current compensation amount", { exact: true }),
  ).toHaveValue("1200000");
  await expect(
    page.getByLabel("Expected compensation amount", { exact: true }),
  ).toHaveValue("");
  await page.getByText("Reviewed application answers", { exact: true }).click();
  await expect(
    page.getByText("Stale profile", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve answer reuse" }),
  ).toHaveCount(0);
});
