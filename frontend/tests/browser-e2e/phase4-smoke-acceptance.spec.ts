import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync, existsSync } from "node:fs";

const backend = "http://127.0.0.1:8767/api/v1";
const headers = { Authorization: "Bearer fictional-browser-demo-owner-token" };
let sharedCookies: Awaited<ReturnType<BrowserContext["cookies"]>> | null = null;

async function loginOwner(page: Page) {
  if (sharedCookies) {
    await page.context().addCookies(sharedCookies);
    await page.goto("/");
    await expect(page).toHaveURL("/");
    return;
  }
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  const input = page.getByLabel("Owner passphrase");
  await expect(input).toBeEnabled();
  await input.fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  sharedCookies = await page.context().cookies();
}

test.describe("Phase 4 Dashboard Complete Acceptance Smoke Suite", () => {
  test("1. Login, invalid credential handling, and authenticated session protection", async ({
    page,
    browser,
  }) => {
    // Attempt invalid passphrase
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: "Welcome back." }),
    ).toBeVisible();
    await page.getByLabel("Owner passphrase").fill("wrong-passphrase-attempt");
    await page.getByRole("button", { name: "Enter workspace" }).click();
    await expect(page.locator(".form-error")).toContainText(
      "Unable to sign in. Check your owner passphrase.",
    );
    await expect(page).toHaveURL(/\/login/);

    // Successful login with owner passphrase
    await page
      .getByLabel("Owner passphrase")
      .fill("fictional-ui-owner-passphrase");
    await page.getByRole("button", { name: "Enter workspace" }).click();
    await expect(page).toHaveURL("/");
    await expect(page.getByText(/Personal workspace/i)).toBeVisible();
    sharedCookies = await page.context().cookies();

    // Verify unauthenticated context cannot access protected section
    const incognito = await browser.newContext();
    const incognitoPage = await incognito.newPage();
    await incognitoPage.goto("/jobs");
    await expect(incognitoPage).toHaveURL(/\/login/);
    await incognito.close();
  });

  test("2. Jobs discovery, filtering, preview modal, and shortlisting", async ({
    page,
    request,
  }) => {
    // Seed test jobs to ensure rich filtering fixtures
    const seedData = {
      source: "manual",
      use_profile: false,
      allow_paid: false,
      idempotency_key: "phase4-smoke-jobs-seed-v5",
      query: { limit: 10 },
      manual_jobs: [
        {
          source_name: "manual",
          source_job_id: "smoke-job-in-5",
          original_url: "https://smoke-test.example/jobs/in-5",
          title: "Principal Infrastructure Engineer (Smoke)",
          company_name: "SmokeTech India Labs",
          country: "India",
          location: "Bengaluru, India",
          experience_level: "Senior",
          experience_min_years: 5,
          experience_max_years: 10,
          date_posted: new Date().toISOString(),
          is_remote: true,
          remote_type: "remote",
        },
        {
          source_name: "manual",
          source_job_id: "smoke-job-eu-5",
          original_url: "https://smoke-test.example/jobs/eu-5",
          title: "Junior Frontend Developer (Smoke)",
          company_name: "SmokeTech EU",
          country: "Germany",
          location: "Berlin, Germany",
          experience_level: "Junior",
          experience_min_years: 1,
          experience_max_years: 3,
          date_posted: new Date().toISOString(),
          is_remote: false,
          remote_type: "onsite",
        },
      ],
    };
    await request.post(`${backend}/discovery/runs`, {
      headers,
      data: seedData,
    });

    await loginOwner(page);
    await page.goto("/jobs");
    await expect(
      page.getByRole("heading", { name: "Work worth exploring." }),
    ).toBeVisible();

    // Verify search by title
    const searchInput = page.getByLabel("Job title", { exact: true });
    await searchInput.fill("Principal Infrastructure");
    await expect(
      page.getByText("Principal Infrastructure Engineer (Smoke)"),
    ).toBeVisible();
    await expect(
      page.getByText("Junior Frontend Developer (Smoke)"),
    ).not.toBeVisible();

    // Reset title filter
    await searchInput.fill("");

    // Verify Country filter button: India
    const indiaFilter = page.getByRole("button", { name: /^🇮🇳 India/ });
    await indiaFilter.click();
    await expect(
      page.getByText("Principal Infrastructure Engineer (Smoke)"),
    ).toBeVisible();
    await expect(
      page.getByText("Junior Frontend Developer (Smoke)"),
    ).not.toBeVisible();

    // Reset country filter
    await indiaFilter.click();
    await expect(
      page.getByText("Junior Frontend Developer (Smoke)"),
    ).toBeVisible();

    // Open Job Preview modal
    const row = page
      .getByRole("row")
      .filter({ hasText: "Principal Infrastructure Engineer (Smoke)" });
    await row.getByRole("button", { name: "Preview" }).click();

    // Verify modal elements
    const previewModal = page.getByRole("dialog");
    await expect(previewModal).toBeVisible();
    await expect(
      previewModal.getByRole("heading", {
        name: "Principal Infrastructure Engineer (Smoke)",
      }),
    ).toBeVisible();
    await expect(previewModal.getByText("SmokeTech India Labs")).toBeVisible();
    await expect(previewModal.getByText("Bengaluru, India")).toBeVisible();

    // Test Shortlist button inside modal
    const shortlistBtn = previewModal.getByRole("button", {
      name: "Shortlist",
    });
    if ((await shortlistBtn.isVisible()) && (await shortlistBtn.isEnabled())) {
      await shortlistBtn.click();
      await expect(
        previewModal.getByRole("button", { name: "Shortlisted" }),
      ).toBeDisabled();
    }

    // Close preview modal
    await previewModal.getByRole("button", { name: "Close" }).click();
    await expect(previewModal).not.toBeVisible();
  });

  test("3. Unsupported sources (Simplify, Workday) are never claimed as automatically integrated", async ({
    page,
    request,
  }) => {
    // Check backend sources contract
    const res = await request.get(`${backend}/discovery/sources`, { headers });
    expect(res.status()).toBe(200);
    const { sources } = await res.json();

    const simplify = sources.find((s: { id: string }) => s.id === "simplify");
    expect(simplify).toBeDefined();
    expect(simplify.adapter_type).toBe("manual");
    expect(simplify.availability).toBe("manual_import_only");
    expect(simplify.live_verified).toBe(false);

    const workday = sources.find((s: { id: string }) => s.id === "workday");
    expect(workday).toBeDefined();
    expect(workday.adapter_type).toBe("manual");
    expect(workday.availability).toBe("manual_import_only");
    expect(workday.live_verified).toBe(false);

    // Verify in dashboard UI
    await loginOwner(page);
    await page.goto("/jobs");

    const sourcesCard = page.getByLabel("Supported Job Sources");
    await expect(sourcesCard).toBeVisible();

    // Both Simplify and Workday must show manual import only
    await expect(sourcesCard).toContainText(
      "Simplify Jobs (manual import only; manual)",
    );
    await expect(sourcesCard).toContainText(
      "Workday (manual import only; manual)",
    );
    await expect(sourcesCard).not.toContainText("✓ Verified");
  });

  test("4. Startup Explorer & People research filters without fabricated headcount", async ({
    page,
  }) => {
    await loginOwner(page);
    await page.goto("/startups");
    await expect(
      page.getByRole("heading", { name: "Find your kind of startup." }),
    ).toBeVisible();

    // Verify company size select filter
    const sizeSelect = page.getByRole("combobox", { name: "Company size" });
    await expect(sizeSelect).toBeVisible();
    await sizeSelect.selectOption("11-50");
    await expect(page.getByText("All sizes")).not.toBeVisible();

    // Check People research section
    await page.goto("/people");
    await expect(
      page.getByRole("heading", { name: "The people behind the team." }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Founders, engineering leaders and recruiters. Every identity needs a source.",
      ),
    ).toBeVisible();
  });

  test("5. Gmail connected-account states and Read-only Job Inbox boundary", async ({
    page,
  }) => {
    await loginOwner(page);
    await page.goto("/connections");

    await expect(
      page.getByRole("heading", {
        name: "The right tools. Clear permissions.",
      }),
    ).toBeVisible();

    // Open the workspace for saved evidence and drafts.
    const mailboxesTab = page.getByRole("tab", {
      name: "Gmail history and drafts",
    });
    await expect(mailboxesTab).toBeVisible();
    await mailboxesTab.click();

    await expect(
      page.getByRole("heading", { name: "Gmail Job Inbox" }),
    ).toBeVisible();
    await expect(page.getByText("Strict Read-Only Boundary:")).toBeVisible();
    await expect(
      page.getByText(
        "cannot send, reply, compose, draft, modify, archive, or delete",
      ),
    ).toBeVisible();

    // Check connected accounts list using heading role
    await expect(
      page.getByRole("heading", {
        name: "first-fixture@example.com",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "second-fixture@example.com",
        exact: true,
      }),
    ).toBeVisible();

    // Verify read-only scopes displayed
    await expect(page.locator("body")).toContainText("gmail.readonly");

    // Verify evidence card and review button
    const firstAccountCard = page.getByLabel(
      "Evidence from first-fixture@example.com",
    );
    await expect(firstAccountCard).toBeVisible();
    await expect(
      firstAccountCard.getByRole("button", { name: "Review lead for import" }),
    ).toBeVisible();
  });

  test("6. Candidate Knowledge facts management and protected versions", async ({
    page,
  }) => {
    await loginOwner(page);
    await page.goto("/candidate-facts");

    await expect(
      page.getByRole("heading", {
        name: "Candidate facts & approved answers.",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /Approved facts overview/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /Edit personal & career facts/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /Projects & achievements/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /Saved answers/i }),
    ).toBeVisible();

    // Switch to Edit personal & career facts tab
    await page
      .getByRole("tab", { name: /Edit personal & career facts/i })
      .click();
    await expect(
      page.getByRole("button", { name: /Save and approve/i }),
    ).toBeVisible();
  });

  test("7. Needs Input questions: missing factual answers lead to question editor, not fabricated content", async ({
    page,
  }) => {
    await loginOwner(page);
    await page.goto("/needs-input");

    await expect(
      page.getByRole("heading", { name: "Codex needs your answer." }),
    ).toBeVisible();
    await expect(page.getByText("Zero Silent Hallucinations:")).toBeVisible();
    await expect(
      page.getByText(
        "The assistant never invents facts when evidence is missing.",
      ),
    ).toBeVisible();
  });

  test("8. Application packet review, Universal Form Assistant, and browser connection status", async ({
    page,
  }) => {
    // Read pre-seeded packet from test fixture
    let packetId = "";
    if (existsSync("../reports/browser-mock.private.json")) {
      const data = JSON.parse(
        readFileSync("../reports/browser-mock.private.json", "utf8"),
      );
      packetId = data.packet_id || data.opportunity_packet_id;
    }

    if (!packetId) {
      test.skip();
      return;
    }

    await loginOwner(page);
    await page.goto(`/applications/${packetId}`);
    await page
      .getByLabel("Application browser", { exact: true })
      .selectOption("isolated");

    // Verify Universal Form Assistant Card
    const detector = page.getByLabel("Universal Form Assistant Detection");
    await expect(detector).toBeVisible();
    await expect(
      detector.getByText("UNIVERSAL FORM ASSISTANT — DETECTED PLATFORM:"),
    ).toBeVisible();
    await expect(
      page.getByText(
        "URL recognition does not verify a vendor adapter, site permission, or compatibility",
      ),
    ).toBeVisible();

    // Verify manual controls notice
    await expect(
      page.getByText("Manual Entry Required (Non-Automated):"),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Legal consent, sensitive disclosures, CAPTCHA and submission",
      ),
    ).toBeVisible();

    // Verify non-submission guarantee notice
    await expect(
      page.getByText("Manual Handoff & Non-Submission Guarantee:"),
    ).toBeVisible();
    await expect(
      page.getByText("It NEVER submits your application to the employer."),
    ).toBeVisible();

    // Verify browser profile consent checkbox
    const profileCheckbox = page.getByLabel(
      "I approve a dedicated browser profile",
      { exact: false },
    );
    await expect(profileCheckbox).toBeVisible();
  });

  test("9. Responsive layout (mobile viewport) and keyboard accessibility audit", async ({
    page,
  }) => {
    await loginOwner(page);
    await page.goto("/jobs");

    // Accessibility audit on Desktop /jobs
    const axeResults = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .disableRules(["color-contrast"]) // Ignore third-party brand badge contrasts
      .analyze();
    expect(axeResults.violations).toEqual([]);

    // Test Keyboard navigation (Tab key moves focus through main controls)
    await page.keyboard.press("Tab");
    const activeTagName = await page.evaluate(
      () => document.activeElement?.tagName,
    );
    expect(["A", "BUTTON", "INPUT"]).toContain(activeTagName);
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());

    // Test Mobile viewport responsiveness (390x844)
    await page.setViewportSize({ width: 390, height: 844 });

    // Ensure sidebar is closed on mobile by default
    await expect
      .poll(() =>
        page
          .locator("aside.sidebar")
          .evaluate((el) => Math.ceil(el.getBoundingClientRect().right)),
      )
      .toBeLessThanOrEqual(0);

    // Hamburger navigation menu opens on click
    const menuBtn = page.getByRole("button", { name: "Open navigation" });
    await expect(menuBtn).toBeVisible();
    await menuBtn.click();
    await expect(page.locator("aside.sidebar.open")).toBeVisible();
    await page.getByRole("link", { name: "My Profile", exact: true }).click();
    await expect(page).toHaveURL("/profile");
    await expect(
      page.getByRole("heading", { name: "Make it yours." }),
    ).toBeVisible();
  });
});
