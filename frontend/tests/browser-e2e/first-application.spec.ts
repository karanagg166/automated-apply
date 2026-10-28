import { test, expect } from "@playwright/test";
import { login } from "../e2e/owner-session";

test("URL intake preserves the exact packet through a missing answer and fresh review", async ({
  page,
}) => {
  await login(page);
  await page.goto("/jobs");
  await page
    .getByRole("textbox", { name: "Paste Job URL" })
    .fill(
      "https://job-boards.greenhouse.io/fictionalfirstapplication/jobs/12345",
    );
  await page
    .getByLabel("Import company name")
    .fill("Fictional First Application");
  await page.getByLabel("Import job title").fill("Fictional Backend Engineer");
  await page
    .getByRole("button", { name: "Prepare application from URL" })
    .click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]{36}$/);
  const application = page.url();
  await expect(
    page.getByRole("heading", {
      name: "Fictional Backend Engineer",
      level: 1,
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByLabel("Question text", { exact: true })
    .fill("Are you willing to relocate?");
  await page.getByLabel("Field type", { exact: true }).selectOption("yes_no");
  await page.getByLabel("Actual form options (one per line)").fill("Yes\nNo");
  await page.getByRole("button", { name: "Add question", exact: true }).click();
  await page
    .getByRole("button", {
      name: "Ask me on Telegram: Are you willing to relocate?",
    })
    .click();
  await expect(page.getByText("Backend paused preparation")).toBeVisible();
  await page.getByLabel("Your verified answer").selectOption("Yes");
  await page
    .getByRole("button", { name: "Submit Answer from Dashboard" })
    .click();
  await expect(
    page.getByText(
      "Answer saved. Review and approve the updated packet before filling.",
    ),
  ).toBeVisible();
  await expect(page).toHaveURL(application);
  await expect(
    page.getByRole("button", { name: "Resume Application", exact: true }),
  ).toHaveCount(0);
  const reviews = page.getByRole("checkbox", {
    name: "I reviewed this exact answer",
  });
  for (const checkbox of await reviews.all()) await checkbox.check();
  await page.getByLabel("I reviewed the selected resume variant.").check();
  await page
    .getByLabel("I verified this is the official application destination.")
    .check();
  const reviewed = page.waitForResponse(
    (response) =>
      response.url().endsWith("/review") &&
      response.request().postDataJSON()?.action === "review",
  );
  await page
    .getByRole("button", { name: "Save field review", exact: true })
    .click();
  expect((await reviewed).status()).toBe(200);
  await page.getByLabel("I reviewed the selected resume variant.").check();
  await page
    .getByLabel("I verified this is the official application destination.")
    .check();
  const approval = page.waitForResponse(
    (response) =>
      response.url().endsWith("/review") &&
      response.request().postDataJSON()?.action === "approve",
  );
  await page
    .getByRole("button", { name: "Approve current packet", exact: true })
    .click();
  expect((await approval).status()).toBe(409);
  await expect(
    page.getByText(
      /Packet cannot be approved: Correct the saved posting source/,
    ),
  ).toBeVisible();
  await expect(page).toHaveURL(application);
  await page.screenshot({
    path: "test-results-browser/first-application-review.png",
    fullPage: true,
  });
});
