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
  const preparation = page.getByRole("region", { name: "Naukri preparation" });
  await expect(
    preparation.getByText("DISCOVERED", { exact: true }),
  ).toBeVisible();
  await preparation.getByRole("button", { name: "pause", exact: true }).click();
  await expect(preparation.getByText("PAUSED", { exact: true })).toBeVisible();
  await preparation
    .getByRole("button", { name: "resume", exact: true })
    .last()
    .click();
  await expect(
    preparation.getByText("DISCOVERED", { exact: true }),
  ).toBeVisible();
  await preparation
    .getByRole("button", { name: "cancel", exact: true })
    .last()
    .click();
  await expect(
    preparation.getByText("FAILED FINAL", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Submission remains manual/)).toBeVisible();
  // The shared fixture deliberately starts unconfirmed. Explicitly review only
  // this fictional profile through the authenticated owner gateway.
  await page.evaluate(async () => {
    const csrf = document.cookie
      .split("; ")
      .find((c) => c.startsWith("aa_csrf="))!
      .split("=")[1];
    const current = await (await fetch("/api/backend/profile")).json();
    const updated = await fetch("/api/backend/profile", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
        "If-Match": `"${current.version}"`,
      },
      body: JSON.stringify({ verified_experience_years: 2 }),
    });
    if (!updated.ok) throw new Error("fictional_profile_update_failed");
    const profile = await updated.json();
    const confirmed = await fetch(
      "/api/backend/local-agent/profile-confirmation",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        body: JSON.stringify({
          expected_version: profile.version,
          owner_confirmed: true,
        }),
      },
    );
    if (!confirmed.ok) throw new Error("fictional_profile_confirmation_failed");
  });
  await page.reload();
  await expect(
    page.getByRole("button", { name: "START AUTOMATION" }),
  ).toBeDisabled();
  await page
    .getByLabel("Allowed exact role titles (comma separated)")
    .fill("Backend Developer");
  await page
    .getByLabel("Allowed exact locations (comma separated)")
    .fill("India");
  await page
    .getByRole("button", { name: "Save bounded preparation policy" })
    .click();
  await expect(
    page.getByRole("button", { name: "START AUTOMATION" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "START AUTOMATION" }).click();
  await expect(preparation.getByText(/Persisted state:/)).toContainText(
    "RUNNING",
  );
  await page.reload();
  await expect(preparation.getByText(/Persisted state:/)).toContainText(
    "RUNNING",
  );
  await page.getByRole("button", { name: "STOP AUTOMATION" }).click();
  await expect(preparation.getByText(/Persisted state:/)).toContainText(
    "STOPPED",
  );
  await page.screenshot({
    path: "test-results-browser/naukri-fictional.png",
    fullPage: true,
  });
});
