import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { resolve } from "node:path";
import { mkdirSync } from "node:fs";
import { login } from "./owner-session";

test.describe.serial("Actual FastAPI with isolated fictional fixtures", () => {
  test("manages disabled automation through the authenticated BFF", async ({
    page,
    request,
  }) => {
    expect(
      (await request.get("/api/backend/dashboard/automation")).status(),
    ).toBe(401);
    await login(page);
    await page.goto("/discover");
    const panel = page.getByRole("region", { name: "Discovery automation" });
    await expect(
      panel.getByRole("heading", { name: "Discovery automation" }),
    ).toBeVisible();
    await expect(
      panel.getByRole("button", { name: "Enable automation" }),
    ).toBeDisabled();
    await expect(panel.getByRole("button", { name: "Run Now" })).toBeDisabled();
    await panel.getByRole("checkbox", { name: "arbeitnow" }).check();
    await panel
      .getByRole("button", { name: "Save automation configuration" })
      .click();
    await expect(
      panel.getByRole("button", { name: "Preview saved automation plan" }),
    ).toBeEnabled();
    await panel
      .getByRole("button", { name: "Preview saved automation plan" })
      .click();
    await expect(
      panel.getByRole("heading", { name: "Saved automation plan" }),
    ).toBeVisible();
    await expect(
      panel.getByText("0 provider calls", { exact: false }),
    ).toBeVisible();
    await panel.getByLabel("Execution status filter").selectOption("blocked");
    await expect(
      panel.getByText("No executions recorded.", { exact: false }),
    ).toBeVisible();
    const csrfFailure = await page.evaluate(
      async () =>
        (
          await fetch("/api/backend/dashboard/automation/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_version: 2,
              idempotency_key: "fixture",
            }),
          })
        ).status,
    );
    expect(csrfFailure).toBe(403);
    await panel.getByRole("button", { name: "Pause notifications" }).click();
    await expect(
      panel.getByText("Notifications paused.", { exact: false }),
    ).toBeVisible();
    // Restore fixture preferences for the existing independent notification journeys.
    await page.goto("/settings");
    await page
      .getByRole("checkbox", { name: /Pause all notifications/ })
      .uncheck();
    await page.getByRole("button", { name: "Save preferences" }).click();
  });
  test("rejects anonymous, CSRF and unlisted privileged calls", async ({
    page,
    request,
  }) => {
    await page.goto("/startups");
    await expect(page).toHaveURL("/login");
    expect(
      (await request.get("/api/backend/dashboard/overview")).status(),
    ).toBe(401);
    await login(page);
    const csrfFailure = await page.evaluate(async () => {
      const r = await fetch("/api/backend/dashboard/presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      return r.status;
    });
    expect(csrfFailure).toBe(403);
    expect((await page.request.get("/api/backend/mcp")).status()).toBe(404);
    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === "aa_owner")?.httpOnly).toBe(true);
  });
  test("onboards, filters exact evidence, reviews a packet and records manual submission", async ({
    page,
  }) => {
    await login(page);
    await page.getByRole("link", { name: "Set up my profile" }).click();
    await expect(
      page.getByRole("heading", { name: "Make it yours." }),
    ).toBeVisible();
    await page
      .getByLabel("Upload private resume")
      .setInputFiles(resolve("../reports/phase7-fictional-resume.pdf"));
    await expect(
      page.getByText("1 pages parsed locally.", { exact: false }),
    ).toBeVisible();
    await page.getByLabel("Full name", { exact: true }).fill("Alex Sample");
    await page.getByLabel("Email", { exact: true }).fill("alex@sample.org");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByLabel("Technical skills")
      .fill("Python, FastAPI, PostgreSQL");
    await page.getByLabel("Verified experience in years").fill("0");
    await page.getByRole("button", { name: "Add project entry" }).click();
    await page
      .getByLabel("Project 1 name", { exact: true })
      .fill("Fictional Service Monitor");
    await page
      .getByLabel("Project 1 description")
      .fill("A test project for isolated verification");
    await page.getByLabel("Project 1 technologies").fill("Python, FastAPI");
    await page
      .getByLabel("Project 1 contribution")
      .fill("Built Python services and API endpoints with FastAPI.");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(
      page.getByText("The two GeeksforGeeks links conflict.", { exact: false }),
    ).toBeVisible();
    await page
      .getByRole("checkbox", { name: "Confirm GeeksforGeeks (resume)" })
      .check();
    await page
      .getByRole("checkbox", { name: "Confirm GeeksforGeeks (GitHub README)" })
      .check();
    await expect(
      page.getByRole("checkbox", { name: "Confirm GeeksforGeeks (resume)" }),
    ).not.toBeChecked();
    await page
      .getByRole("checkbox", { name: "Confirm GeeksforGeeks (GitHub README)" })
      .uncheck();
    await page.screenshot({
      path: test.info().outputPath("phase7-onboarding.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByLabel("Target job titles").fill("Backend Engineer");
    await page.getByLabel("Preferred locations").fill("India");
    await page.getByLabel("Startup team size").selectOption("51-200");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByRole("checkbox", { name: "I reviewed these facts", exact: false })
      .check();
    await page
      .getByRole("button", { name: "Save reviewed profile", exact: true })
      .click();
    await expect(
      page.getByText("Your reviewed profile and selected evidence are saved.", {
        exact: false,
      }),
    ).toBeVisible();
    const accepted = await page.evaluate(async () => {
      const r = await fetch("/api/backend/local-agent/connections");
      return r.json();
    });
    expect(
      accepted.find((x: { name: string }) => x.name === "Candidate profile")
        .state,
    ).toBe("capability_verified");
    expect(
      accepted.find((x: { name: string }) => x.name === "Resume").state,
    ).toBe("capability_verified");
    await page.goto("/startups");
    await page
      .getByRole("button", { name: "My preferred team size", exact: true })
      .click();
    await expect(page.getByText("1 teams", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Fictional Large Team", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Reset filters", exact: true })
      .click();
    await page.getByLabel("Search saved companies").fill("Northstar");
    await page.getByLabel("Search saved companies").press("Enter");
    await expect(page.getByText("1 teams", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Fictional Northstar Labs", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Fictional Large Team", exact: true }),
    ).not.toBeVisible();
    await page.getByLabel("Search saved companies").fill("");
    await page.getByLabel("Search saved companies").press("Enter");
    await expect(page.getByText("4 teams", { exact: true })).toBeVisible();
    await page.getByLabel("Location", { exact: true }).selectOption("India");
    await page.getByLabel("Company size").selectOption("2-10");
    await page.getByLabel("Technology", { exact: true }).selectOption("Python");
    await page
      .getByLabel("Role", { exact: true })
      .selectOption("Backend Engineer");
    await expect(page.getByText("1 teams", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Fictional Northstar Labs", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Fictional Pixel Current", { exact: true }),
    ).not.toBeVisible();
    await expect(
      page.getByText("Fictional Solo Systems", { exact: true }),
    ).not.toBeVisible();
    await page.screenshot({
      path: test.info().outputPath("phase7-startups-desktop.png"),
      fullPage: true,
    });
    await page
      .getByRole("link", { name: "View company", exact: false })
      .click();
    await expect(
      page.getByRole("heading", { name: "Source observations" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Founders & contacts" }).click();
    await expect(
      page.getByRole("heading", { name: "Jordan Fictional" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Contact evidence" }).click();
    await expect(
      page.getByRole("dialog", { name: "Contact evidence" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();
    const companyUrl = page.url();
    await page.getByRole("button", { name: "Prepare local draft" }).click();
    await expect(
      page.getByRole("heading", { name: "Message preview" }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("button", { name: "Review exact send" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Approve exact content" }).click();
    await expect(
      page.getByText("Local draft · Revision", { exact: false }),
    ).toContainText("approved");
    await page.goto(companyUrl);
    await page.getByRole("button", { name: "Open roles", exact: true }).click();
    await page.getByRole("button", { name: "Prepare application" }).click();
    await expect(
      page.getByRole("heading", { name: "Application fields" }),
    ).toBeVisible();
    await page
      .getByLabel("Question text", { exact: true })
      .fill("Why are you interested in this backend role?");
    await page
      .getByRole("button", { name: "Add question", exact: true })
      .click();
    const question = page
      .locator(".evidence-item")
      .filter({ hasText: "Why are you interested in this backend role?" })
      .first();
    await question
      .getByLabel("Reviewable answer")
      .fill(
        "I would like to contribute my Python and FastAPI experience to reliable backend systems.",
      );
    await question
      .getByRole("button", { name: "Save answer", exact: true })
      .click();
    await expect(
      question.getByRole("checkbox", { name: "I reviewed this exact answer" }),
    ).toBeEnabled();
    await question
      .getByRole("checkbox", { name: "I reviewed this exact answer" })
      .check();
    await page
      .getByLabel("Question text", { exact: true })
      .fill("Preferred backend language");
    await page
      .getByLabel("Field type", { exact: true })
      .selectOption("multiple_choice");
    await expect(
      page.getByRole("button", { name: "Add question", exact: true }),
    ).toBeDisabled();
    await page
      .getByLabel("Actual form options (one per line)")
      .fill("Python\nJava");
    const addedChoice = page.waitForResponse(
      (response) =>
        response.url().endsWith("/questions") &&
        response.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Add question", exact: true })
      .click();
    expect((await addedChoice).status()).toBe(200);
    const choice = page
      .locator(".evidence-item")
      .filter({ hasText: "Preferred backend language" })
      .first();
    await expect(choice).toContainText("Python · Java");
    await choice.getByLabel("Reviewable answer").fill("Python");
    await choice
      .getByRole("button", { name: "Save answer", exact: true })
      .click();
    await expect(
      choice.getByRole("checkbox", { name: "I reviewed this exact answer" }),
    ).toBeEnabled();
    await choice.getByLabel("I reviewed this exact answer").check();
    // Adding a question revises the packet; review the original answer again.
    await question.getByLabel("I reviewed this exact answer").check();
    if (process.env.PHASE2_SCREENSHOT_DIR) {
      mkdirSync(process.env.PHASE2_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({
        path: resolve(
          process.env.PHASE2_SCREENSHOT_DIR,
          "fictional-packet-choice-review.png",
        ),
        fullPage: true,
      });
    }
    await page
      .getByRole("checkbox", {
        name: "I reviewed the selected resume variant.",
      })
      .check();
    await page
      .getByRole("checkbox", {
        name: "I verified this is the official application destination.",
      })
      .check();
    await page.getByRole("button", { name: "Approve current packet" }).click();
    await expect(
      page.getByRole("button", { name: "Open manual handoff", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Open manual handoff", exact: true })
      .click();
    await expect(
      page.getByText("Ready for manual handoff", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath("phase7-application-review.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Report manual completion" })
      .click();
    await page
      .getByRole("checkbox", {
        name: "I submitted this application on the official website.",
      })
      .check();
    await page
      .getByRole("button", { name: "Record user-reported submission" })
      .click();
    await expect(
      page.getByText("Submission recorded as user reported", { exact: false }),
    ).toBeVisible();
    await page.goto("/jobs");
    await expect(
      page.getByRole("button", { name: "Prepare application", exact: true }),
    ).toHaveCount(3);
    await page.getByRole("button", { name: "Applied", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Prepare application", exact: true }),
    ).toHaveCount(1);
  });
  test("saves notification preferences, shows truthful accounts and keeps Gmail disabled", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/settings");
    await page.getByLabel("Quiet hours start").fill("0");
    await page.getByLabel("Quiet hours end").fill("0");
    await page
      .getByRole("button", { name: "Save preferences", exact: true })
      .click();
    await expect(
      page.getByText("Notification preferences saved."),
    ).toBeVisible();
    await page.goto("/notifications");
    await page.getByRole("button", { name: "Check saved activity" }).click();
    await expect(
      page.getByRole("heading", { name: "Your daily review" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Check saved activity" }).click();
    await expect(
      page.getByRole("heading", { name: "Your daily review" }),
    ).toHaveCount(1);
    await page.goto("/connections");
    await expect(
      page.getByRole("heading", { name: "Secondary Gmail" }),
    ).toBeVisible();
    await page
      .locator(".connection-card")
      .filter({ has: page.getByRole("heading", { name: "Secondary Gmail" }) })
      .getByRole("button")
      .click();
    await expect(
      page.getByRole("button", { name: "Continue to Google consent" }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Close dialog" }).click();
    await page.goto("/outreach");
    await expect(
      page.getByRole("status").filter({ hasText: "Sending is disabled." }),
    ).toBeVisible();
  });
  test("desktop and mobile layouts, dark theme, accessibility and client-secret boundary", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/startups");
    await expect(
      page.getByRole("heading", { name: "Find your kind of startup." }),
    ).toBeVisible();
    const a11y = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    const violations = a11y.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    }));
    expect(violations).toEqual([]);
    await page.getByRole("button", { name: "Toggle color theme" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    const darkA11y = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      darkA11y.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          summary: n.failureSummary,
        })),
      })),
    ).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("phase7-startups-dark.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      )
      .toBe(true);
    await expect
      .poll(() =>
        page
          .locator("aside.sidebar")
          .evaluate((el) => Math.ceil(el.getBoundingClientRect().right)),
      )
      .toBeLessThanOrEqual(0);
    await page.screenshot({
      path: test.info().outputPath("phase7-startups-mobile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("link", { name: "My Profile", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Make it yours." }),
    ).toBeVisible();
    const html = await page.content();
    expect(html).not.toContain("fictional-phase7-backend-token-never-client");
    const scripts = await page
      .locator("script[src]")
      .evaluateAll((nodes) => nodes.map((n) => (n as HTMLScriptElement).src));
    for (const src of scripts) {
      const response = await page.request.get(src);
      expect(await response.text()).not.toContain(
        "fictional-phase7-backend-token-never-client",
      );
    }
  });
  test("defers Drive download and preserves the canonical manual PDF and profile", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/profile");
    await expect(
      page.getByText(/Google Drive OAuth and live PDF download are deferred/),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sync Now", exact: true }),
    ).toBeDisabled();
    const before = await (
      await page.request.get("/api/backend/profile")
    ).json();
    const resumesBefore = await (
      await page.request.get("/api/backend/dashboard/resumes")
    ).json();
    expect(resumesBefore.resumes.length).toBeGreaterThan(0);
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Sync Now", exact: true }),
    ).toBeDisabled();
    expect(
      await (await page.request.get("/api/backend/profile")).json(),
    ).toEqual(before);
    expect(
      await (await page.request.get("/api/backend/dashboard/resumes")).json(),
    ).toEqual(resumesBefore);
  });
  test("persists ranked project configuration and reviewed canonical profile links", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/profile");
    await page
      .getByLabel("Ranked project 1 name", { exact: true })
      .fill("Fictional API service");
    await page
      .getByLabel("Ranked project 1 GitHub repository", { exact: true })
      .fill("https://github.com/fictional-owner/fictional-service");
    await page
      .getByLabel("Ranked project 1 technology stack", { exact: true })
      .fill("FastAPI, PostgreSQL");
    await page
      .getByRole("button", { name: "Save ranked projects", exact: true })
      .click();
    await expect(page.getByText(/Project configuration saved/)).toBeVisible();
    await page.reload();
    await expect(
      page.getByLabel("Ranked project 1 name", { exact: true }),
    ).toHaveValue("Fictional API service");
    await page
      .getByRole("button", {
        name: "Recompute context for project-01",
        exact: true,
      })
      .click();
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "repository_not_authorized_or_unavailable" }),
    ).toBeVisible();
    await page
      .getByLabel("Profile link label", { exact: true })
      .fill("Fictional LeetCode profile");
    await page
      .getByLabel("Reviewed profile URL", { exact: true })
      .fill("https://leetcode.com/u/fictional-reviewed");
    const save = page.getByRole("button", {
      name: "Save reviewed profile link",
      exact: true,
    });
    await expect(save).toBeDisabled();
    await page
      .getByRole("checkbox", { name: /I reviewed this profile URL/ })
      .check();
    await save.click();
    await expect(page.getByText("Reviewed profile link saved.")).toBeVisible();
    const resources = await (
      await page.request.get("/api/backend/candidate/resources")
    ).json();
    expect(resources.resources).toContainEqual(
      expect.objectContaining({
        resource_type: "leetcode",
        url: "https://leetcode.com/u/fictional-reviewed",
        user_confirmed: true,
      }),
    );
    expect(resources.resolved_links).toContainEqual(
      expect.objectContaining({
        resource_type: "leetcode",
        url: "https://leetcode.com/u/fictional-reviewed",
        user_confirmed: true,
      }),
    );
  });
  test("shows unavailable providers without invented results", async ({
    page,
  }) => {
    await login(page);
    await page.route("**/api/backend/startups/search", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Isolated unavailable-provider fixture",
        }),
      }),
    );
    await page.goto("/startups");
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "Unable to complete this request" }),
    ).toContainText("Isolated unavailable-provider fixture");
    await expect(page.getByRole("link", { name: "View company" })).toHaveCount(
      0,
    );
  });
});
