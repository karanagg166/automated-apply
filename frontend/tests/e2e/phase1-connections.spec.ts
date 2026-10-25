import { test, expect } from "@playwright/test";
import { resolve } from "node:path";

test("connections show evidence and persist approval preferences through owner BFF", async ({
  page,
  request,
}) => {
  expect(
    (await request.get("/api/backend/local-agent/connections")).status(),
  ).toBe(401);
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/connections");
  const section = page.getByRole("region", {
    name: "Local foundation connections",
  });
  await expect(
    section.getByRole("heading", { name: "Core infrastructure" }),
  ).toBeVisible();
  await expect(
    section.getByRole("heading", { name: "Supabase PostgreSQL" }),
  ).toBeVisible();
  await expect(
    section.getByRole("heading", { name: "Telegram worker" }),
  ).toBeVisible();
  for (const name of [
    "Supabase CLI",
    "Gmail identity",
    "Gmail compose",
    "Candidate profile",
    "Resume",
  ]) {
    await expect(
      section.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
  }
  for (const name of [
    "Naukri",
    "Wellfound",
    "Instahyre",
    "YC Work at a Startup",
    "Internshala",
  ]) {
    const connect = section.getByRole("link", {
      name: `Connect ${name}`,
      exact: true,
    });
    await expect(connect).toHaveAttribute("href", /^https:\/\//);
    await expect(connect).toHaveAttribute("target", "_blank");
  }
  await section
    .getByRole("button", { name: "Forget Naukri metadata", exact: true })
    .click();
  await expect(
    section.getByRole("status", { name: "Platform metadata status" }),
  ).toContainText("Connection metadata forgotten");
  await section
    .getByRole("button", {
      name: "Accept manual-only capability for Naukri",
      exact: true,
    })
    .click();
  const naukri = section
    .locator("article")
    .filter({
      has: page.getByRole("heading", { name: "Naukri", exact: true }),
    });
  await expect(naukri.getByText("Manual-only", { exact: true })).toBeVisible();
  await expect(
    naukri.getByRole("button", {
      name: "Accept manual-only capability for Naukri",
      exact: true,
    }),
  ).toBeDisabled();
  const policies = section.getByRole("region", { name: "Approval policies" });
  await expect(policies.getByLabel("naukri", { exact: true })).toHaveValue(
    "automatic_preferred",
  );
  await policies.getByLabel("naukri", { exact: true }).selectOption("approve");
  await policies
    .getByRole("button", { name: "Save approval preferences" })
    .click();
  await expect(policies.getByRole("status")).toContainText("saved");
  await page.reload();
  await expect(policies.getByLabel("naukri", { exact: true })).toHaveValue(
    "approve",
  );
  await expect(policies.getByLabel("gmail", { exact: true })).toHaveValue(
    "draft_only",
  );
  const denied = await page.evaluate(
    async () =>
      (
        await fetch("/api/backend/local-agent/policy", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        })
      ).status,
  );
  expect(denied).toBe(403);
  await page.screenshot({
    path: resolve("../reports/phase1-connections.png"),
    fullPage: true,
  });
  await page.goto("/discover");
  const preferences = page.getByRole("region", {
    name: "Saved job search preferences",
  });
  await preferences.getByText("Edit saved filters", { exact: true }).click();
  await preferences
    .getByLabel("Job titles", { exact: true })
    .fill("Backend Engineer");
  await preferences.getByLabel("Minimum employees", { exact: true }).fill("2");
  await preferences.getByLabel("Maximum employees", { exact: true }).fill("10");
  await preferences
    .getByRole("button", { name: "Save search preferences" })
    .click();
  await expect(preferences.getByRole("status")).toContainText("saved");
  await page.reload();
  await preferences.getByText("Edit saved filters", { exact: true }).click();
  await expect(
    preferences.getByLabel("Job titles", { exact: true }),
  ).toHaveValue("Backend Engineer");
  await expect(
    preferences.getByLabel("Minimum employees", { exact: true }),
  ).toHaveValue("2");
});
