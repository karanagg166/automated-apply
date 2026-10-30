import { mkdir } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { login } from "./owner-session";

test("background queue policy, ledger filters and revocable controls", async ({
  page,
}) => {
  const limits = {
    daily_cap: 80,
    max_job_age_days: 2,
    applicant_limit: 10000,
    unknown_applicants: "needs_review",
    minimum_match_score: 80,
  };
  let configuration = {
    state: "STOPPED",
    revision: 1,
    policy: {
      global_limits: limits,
      platforms: {
        naukri: {
          enabled: false,
          sources: [
            "approved_gmail_alerts",
            "saved_verified_job",
            "naukri_ui_search",
          ],
          mode: "PREPARE_ONLY",
          owner_submission_authorized: false,
          cap_mode: "global",
          age_mode: "global",
          applicants_mode: "global",
          preferences_mode: "global",
          limits,
          preferences: {
            roles: [],
            locations: [],
            excluded_companies: [],
            experience_min: null,
            experience_max: null,
            minimum_salary: null,
            maximum_salary: null,
            salary_currency: "INR",
            salary_period: "year",
          },
          discovery_interval_seconds: 300,
          supervised_submission_cap: 1,
        },
      },
      day_timezone: "Asia/Kolkata",
      concurrency: 1,
      max_pending: 200,
      background_only: true,
      notify_submitted: true,
    },
  };
  const mutations: string[] = [],
    filters: URL[] = [];
  await page.route("**/api/backend/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/backend/", "");
    let data: unknown = [];
    if (path === "dashboard/runtime") data = { demo_mode: true };
    else if (path === "integrations") data = { connectors: [] };
    else if (path === "execution/naukri")
      data = {
        configuration: {
          mode: "ON_DEMAND",
          interval_seconds: 21600,
          source: "saved_owner_imports",
          destinations: [],
          submission_permission: false,
        },
        executions: [],
        capabilities: {},
      };
    else if (path === "execution/naukri/jobs") data = { jobs: [] };
    else if (path === "execution/queue") {
      filters.push(url);
      data = {
        configuration,
        total: 1,
        counts: { NEEDS_INPUT: 1 },
        capabilities: {
          submission: "executor_pending",
          background_read: "implemented_not_live_accepted",
          locked_screen: "NOT_TESTED",
        },
        consumer: null,
        discovery: null,
        items: [
          {
            id: "fictional",
            requisition: "291026123456",
            platform: "naukri",
            title: "Fictional Backend Developer",
            company: "Fictional Labs",
            location: "Pune",
            stage: "NEEDS_INPUT",
            status: "waiting",
            match_score: 90,
            applicants_min: null,
            applicants_max: null,
            posted_at: null,
            reason: "applicant_count_requires_review",
            created_at: "2026-10-31T00:00:00Z",
          },
        ],
      };
    } else if (path === "execution/queue/policy") {
      const body = route.request().postDataJSON();
      expect(body.expected_revision).toBe(configuration.revision);
      configuration = {
        state: "STOPPED",
        revision: configuration.revision + 1,
        policy: body.policy,
      };
      mutations.push("save");
      data = configuration;
    } else if (path === "execution/queue/control") {
      const body = route.request().postDataJSON();
      expect(body.expected_revision).toBe(configuration.revision);
      configuration = {
        ...configuration,
        revision: configuration.revision + 1,
        state:
          body.action === "start"
            ? "RUNNING"
            : body.action === "pause"
              ? "PAUSED"
              : "STOPPED",
      };
      mutations.push(body.action);
      data = configuration;
    } else if (route.request().method() !== "GET")
      throw Error("unexpected fixture mutation");
    await route.fulfill({ json: data });
  });
  await login(page);
  await page.goto("/naukri");
  const panel = page.getByRole("region", {
    name: "Background application queue",
  });
  await expect(panel.getByText("Fictional Backend Developer")).toBeVisible();
  await expect(
    panel.getByLabel("Global maximum posting age in days"),
  ).toHaveValue("2");
  await panel.getByLabel("Enable Naukri automation").check();
  await panel.getByLabel("Naukri posting age source").selectOption("custom");
  await panel.getByLabel("Naukri maximum posting age in days").fill("1");
  await panel
    .getByLabel("Naukri applicant threshold source")
    .selectOption("custom");
  await panel
    .getByLabel("Naukri applicant threshold (skip at or above)")
    .fill("500");
  await panel.getByRole("button", { name: "Save queue policy" }).click();
  await expect.poll(() => mutations).toEqual(["save"]);
  await panel.getByRole("button", { name: "START QUEUE" }).click();
  await expect(panel.getByText("RUNNING", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "PAUSE QUEUE" }).click();
  await expect(
    panel.locator("strong").filter({ hasText: /^PAUSED$/ }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "STOP QUEUE" }).click();
  await expect(panel.getByText("STOPPED", { exact: true })).toBeVisible();
  await panel.getByLabel("Queue status filter").selectOption("NEEDS_INPUT");
  await panel.getByLabel("Queue location filter").fill("Pune");
  await panel.getByLabel("Queue minimum match score filter").fill("85");
  await panel.getByRole("button", { name: "Filter jobs" }).click();
  await expect
    .poll(() =>
      filters.some(
        (u) =>
          u.searchParams.get("stage") === "NEEDS_INPUT" &&
          u.searchParams.get("location") === "Pune" &&
          u.searchParams.get("minimum_score") === "85",
      ),
    )
    .toBe(true);
  expect(mutations).toEqual(["save", "start", "pause", "stop"]);
  await page.reload();
  await expect(
    panel.getByLabel("Naukri maximum posting age in days"),
  ).toHaveValue("1");
  await expect(
    panel.getByLabel("Naukri applicant threshold (skip at or above)"),
  ).toHaveValue("500");
  await expect(
    panel.getByText(/Automatic submission is still being implemented/),
  ).toBeVisible();
  await mkdir("../docs/acceptance/screenshots", { recursive: true });
  await panel.screenshot({
    path: "../docs/acceptance/screenshots/naukri-background-queue-fictional.png",
  });
});
