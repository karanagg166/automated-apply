import {
  test,
  expect,
  type Page,
  type BrowserContext,
  type APIRequestContext,
} from "@playwright/test";
import { readFileSync } from "node:fs";
const backend = "http://127.0.0.1:8767";
const headers = { Authorization: "Bearer fictional-browser-demo-owner-token" };
let cookies: Awaited<ReturnType<BrowserContext["cookies"]>> | null = null;
async function login(page: Page) {
  if (cookies) {
    await page.context().addCookies(cookies);
    await page.goto("/");
    return;
  }
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  cookies = await page.context().cookies();
}
function manifest() {
  return JSON.parse(
    readFileSync("../reports/phase3-browser-fixture.json", "utf8"),
  ) as { fixture: true; account_ids: string[]; question: string };
}
async function generate(request: APIRequestContext, question: string) {
  return request.post(`${backend}/api/v1/application-answers/generate`, {
    headers,
    data: { question, save_draft: false },
  });
}

test("unknown question persists, deep-links to frontend draft, requires exact human approval, and safely reuses", async ({
  page,
  request,
}) => {
  const { question } = manifest();
  const unknown = await generate(request, question);
  expect(unknown.status()).toBe(200);
  const result = await unknown.json();
  expect(result.status).toBe("needs_input");
  expect(result.answer).toBeNull();
  expect(result.missing_input_id).toMatch(/^[a-f0-9]{32}$/);
  const id = result.missing_input_id;
  expect(
    (
      await (
        await request.get(
          `${backend}/api/v1/application-answers/missing/${id}`,
          { headers },
        )
      ).json()
    ).status,
  ).toBe("needs_input");
  await login(page);
  await page.goto(`/profile?missing_input=${id}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(question);
  const answer =
    "In the fictional October incident I added bounded retry for idempotent GET requests after HTTP 429 responses.";
  await dialog.getByLabel("Your Truthful Answer").fill(answer);
  await dialog
    .getByLabel("Supporting Evidence / Project Context")
    .fill("My owner-reviewed fictional incident notes.");
  await dialog.getByRole("checkbox").check();
  const approve = dialog.getByRole("button", {
    name: "Approve answer for this context",
  });
  await expect(approve).toBeDisabled();
  await dialog.getByRole("button", { name: "Save as draft" }).click();
  await expect(
    dialog.getByText("Draft answer saved.", { exact: false }),
  ).toBeVisible();
  expect((await (await generate(request, question)).json()).answer).toBeNull();
  await dialog.getByRole("checkbox").check();
  await expect(approve).toBeEnabled();
  await dialog
    .getByLabel("Your Truthful Answer")
    .fill(answer + " Unsaved edit.");
  await expect(approve).toBeDisabled();
  await dialog.getByLabel("Your Truthful Answer").fill(answer);
  await dialog.getByRole("checkbox").check();
  await approve.click();
  await expect(
    dialog.getByText(
      "Saved answer approved for this exact question and context.",
      { exact: false },
    ),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "View revision history" }).click();
  await expect(dialog.getByLabel("Revision history")).toContainText(
    "approved exact context",
  );
  const reused = await (await generate(request, question)).json();
  expect(reused.status).toBe("draft_ready");
  expect(reused.answer).toBe(answer);
  expect(reused.source).toBe("owner_approved_exact_context");
  expect(reused.evidence_references).toContainEqual({
    source_type: "owner_answer",
    source_id: id,
  });
  const different = await (
    await generate(request, question + " At a different employer.")
  ).json();
  expect(different.answer).toBeNull();
  await page.reload();
  await expect(page.getByRole("dialog")).toContainText(answer);
  await page.screenshot({
    path: "../reports/phase3-approved-answer-fixture.png",
    fullPage: true,
  });
});

test("two Gmail accounts keep evidence isolated, require reviewed import, and reject every mailbox write", async ({
  page,
  request,
}) => {
  const {
    account_ids: [first, second],
  } = manifest();
  await login(page);
  await page.goto("/connections");
  await page
    .getByRole("tab", { name: "Connected mailboxes (Read-Only)" })
    .click();
  const firstEvidence = page.getByRole("region", {
    name: "Evidence from first-fixture@example.com",
  });
  const secondEvidence = page.getByRole("region", {
    name: "Evidence from second-fixture@example.com",
  });
  await expect(firstEvidence).toContainText("fixture-message-1");
  await expect(firstEvidence).not.toContainText("fixture-message-2");
  await expect(secondEvidence).toContainText("fixture-message-2");
  await expect(secondEvidence).not.toContainText("fixture-message-1");
  await expect(
    firstEvidence.getByRole("link", { name: "Inspect retained source link" }),
  ).toHaveAttribute("href", "https://fixture-company-1.example/jobs/backend");
  await page.getByLabel("Filter by account").selectOption(second);
  await expect(firstEvidence).not.toBeAttached();
  await expect(secondEvidence).toBeVisible();
  await secondEvidence
    .getByRole("button", { name: "Review lead for import" })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Account: second-fixture@example.com");
  const importButton = dialog.getByRole("button", {
    name: "Import reviewed lead",
  });
  await expect(importButton).toBeDisabled();
  await dialog
    .getByLabel("Actual job title")
    .fill("Fictional backend engineer");
  await dialog.getByRole("checkbox").check();
  const importResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/accounts/${second}/evidence/`) &&
      response.url().endsWith("/import"),
  );
  await importButton.click();
  const imported = await (await importResponse).json();
  expect(imported.job_ids).toHaveLength(1);
  await expect(
    page.getByText("Reviewed lead imported into workspace", { exact: false }),
  ).toBeVisible();
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === "aa_csrf",
  )!.value;
  for (const operation of [
    "send",
    "modify",
    "archive",
    "delete",
    "trash",
    "drafts",
  ]) {
    const path = `integrations/gmail/accounts/${first}/${operation}`;
    expect(
      (
        await page.request.post(`/api/backend/${path}`, {
          headers: { Origin: "http://localhost:3101", "X-CSRF-Token": csrf },
          data: {},
        })
      ).status(),
    ).toBe(404);
    expect(
      (
        await request.post(`${backend}/api/v1/${path}`, { headers, data: {} })
      ).status(),
    ).toBe(404);
  }
  const evidence = await (
    await request.get(
      `${backend}/api/v1/integrations/gmail/accounts/${second}/evidence`,
      { headers },
    )
  ).json();
  const retained = evidence.evidence[0];
  expect(retained.account_id).toBe(second);
  expect(retained.imported_job_ids).toEqual(
    expect.arrayContaining(imported.job_ids),
  );
  expect(retained.verification_status).toBe("requires_review");
  expect(retained.submission_confirmed).toBe(false);
  for (const key of [
    "sender",
    "subject",
    "body",
    "access_token",
    "refresh_token",
  ])
    expect(retained).not.toHaveProperty(key);
  for (const id of imported.job_ids) {
    const job = await (
      await request.get(`${backend}/api/v1/jobs/${id}`, { headers })
    ).json();
    expect(job.source_platform).toBe("gmail_alert");
    expect(job.status).toBe("discovered");
    expect(job.title).toBe("Fictional backend engineer");
    expect(job.job_url).toBe("https://fixture-company-2.example/jobs/backend");
  }
  const other = await (
    await request.get(
      `${backend}/api/v1/integrations/gmail/accounts/${first}/evidence`,
      { headers },
    )
  ).json();
  expect(
    other.evidence.every(
      (record: { imported_job_ids?: string[] }) =>
        !(record.imported_job_ids || []).some((id) =>
          imported.job_ids.includes(id),
        ),
    ),
  ).toBe(true);
  const foreign = await request.post(
    `${backend}/api/v1/integrations/gmail/accounts/${first}/evidence/${evidence.evidence[0].id}/import`,
    {
      headers,
      data: {
        job_url: "https://fixture-company-2.example/jobs/backend",
        title: "Foreign mailbox record",
        reviewed_job_evidence: true,
      },
    },
  );
  expect(foreign.status()).toBe(409);
  const audit = await (
    await request.get(`${backend}/_fictional_test/phase3-provider-audit`, {
      headers,
    })
  ).json();
  expect(audit.mailbox_writes).toBe(0);
  expect(audit.external_requests).toBe(0);
  expect(audit.calls.length).toBeGreaterThan(0);
  expect(
    audit.calls.every((call: { method: string }) => call.method === "GET"),
  ).toBe(true);
});

test("profile edits display actual 409 conflicts and stale exact-context approval is rejected", async ({
  page,
  request,
}) => {
  await login(page);
  await page.goto("/candidate-facts");
  await page
    .getByRole("tab", { name: /Edit personal & career facts/i })
    .click();
  const profile = await (
    await request.get(`${backend}/api/v1/profile`, { headers })
  ).json();
  const updated = await request.patch(`${backend}/api/v1/profile`, {
    headers: { ...headers, "If-Match": `"${profile.version}"` },
    data: { summary: "Fictional concurrently reviewed profile update." },
  });
  expect(updated.status()).toBe(200);
  await page
    .getByLabel("I confirm these facts are truthful", { exact: false })
    .check();
  await page.getByRole("button", { name: /Save and approve version/i }).click();
  await expect(
    page.getByText("Profile version conflict", { exact: true }),
  ).toBeVisible();
  const { question } = manifest();
  const generated = await (await generate(request, question)).json();
  expect(generated.answer).toBeNull();
  await page.goto("/needs-input");
  await page.getByRole("tab", { name: /Review required/i }).click();
  await expect(
    page.getByRole("heading", { name: question, exact: true }),
  ).toBeVisible();
});

test("filters Indian startups by 11–50 employees and technology category, preserving exact-versus-reported size evidence", async ({
  page,
}) => {
  await login(page);

  // Intercept startup searches with verified realistic startup observation data to test card rendering
  await page.route("**/api/backend/startups/search*", async (route) => {
    const json = {
      total: 2,
      startups: [
        {
          company_id: "11111111-2222-3333-4444-555555555555",
          company_name: "Fictional Bharat AI",
          company_domain: "bharat-ai.example",
          attributes: {
            industry: "AI / Machine Learning",
            description: "Fictional Bengaluru AI infrastructure team.",
            city: "Bengaluru",
            country: "India",
            location: "Bengaluru, India",
            is_remote: true,
            technology_stack: ["Python", "FastAPI", "PostgreSQL"],
          },
          exact_employee_count: false,
          employee_count: null,
          team_size_band: "11-50",
          team_size_evidence_status: "source_reported",
          leader_evidence_count: 2,
          technical_staff_count: 12,
          verification_status: "verified",
          hiring_status: "hiring_confirmed",
          startup_match_score: 94,
          current_job_count: 3,
          professional_contact_count: 4,
          sources: ["official_careers"],
          shortlisted: false,
          matching_roles: 2,
          missing_information: [],
          team_size_evidence: [
            {
              source_url: "https://bharat-ai.example/about",
              observed_at: "2026-03-01T10:00:00Z",
              source_type: "official_site",
              confidence: 0.9,
              detail: "11-50 employees on official team page",
            },
          ],
          hiring_evidence: [],
        },
        {
          company_id: "66666666-7777-8888-9999-000000000000",
          company_name: "Fictional Pune SaaS",
          company_domain: "pune-saas.example",
          attributes: {
            industry: "Software / SaaS",
            description: "Fictional B2B workflow software.",
            city: "Pune",
            country: "India",
            location: "Pune, India",
            is_remote: false,
            technology_stack: ["TypeScript", "Next.js"],
          },
          exact_employee_count: true,
          employee_count: 25,
          team_size_band: "11-50",
          team_size_evidence_status: "source_reported",
          leader_evidence_count: 1,
          technical_staff_count: 8,
          verification_status: "verified",
          hiring_status: "hiring_confirmed",
          startup_match_score: 82,
          current_job_count: 1,
          professional_contact_count: 2,
          sources: ["official_careers"],
          shortlisted: false,
          matching_roles: 1,
          missing_information: [],
          team_size_evidence: [],
          hiring_evidence: [],
        },
      ],
      page: 1,
      limit: 12,
    };
    await route.fulfill({ json });
  });

  await page.goto("/startups");
  await expect(
    page.getByRole("heading", { name: "Find your kind of startup." }),
  ).toBeVisible();

  // Apply location filter for India
  const locationSelect = page.getByLabel("Location");
  await locationSelect.selectOption("India");

  // Apply 11-50 size band
  const sizeSelect = page.getByLabel("Company size");
  await sizeSelect.selectOption("11-50");

  // Apply technology filter
  const techSelect = page.getByLabel("Technology");
  await techSelect.selectOption("Python");

  // Trigger search refetch
  await page.getByRole("button", { name: "Search saved" }).click();

  // Verify company cards rendered
  await expect(page.getByText("Fictional Bharat AI")).toBeVisible();
  await expect(page.getByText("Fictional Pune SaaS")).toBeVisible();

  // Preserves exact-versus-reported evidence:
  // Band company displays "11-50 band" and "Size: source reported"
  await expect(page.getByText("11-50 band")).toBeVisible();
  await expect(page.getByText("Size: source reported").first()).toBeVisible();

  // Exact headcount company displays "25 employees (source reported)"
  await expect(page.getByText("25 employees (source reported)")).toBeVisible();

  // Founder and contact evidence badges
  await expect(page.getByText("Founder / CEO available (2)")).toBeVisible();
  await expect(page.getByText("Technical staff evidence (12)")).toBeVisible();
  await expect(page.getByText("Contacts discovered (4)")).toBeVisible();

  // Test sorting by company name (A-Z)
  const sortSelect = page.getByLabel("Sort startups");
  await sortSelect.selectOption("name_asc");

  // Reset filters
  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByText("Filters reset.")).toBeVisible();
  await expect(sizeSelect).toHaveValue("all");
  await expect(locationSelect).toHaveValue("Any");
  await expect(techSelect).toHaveValue("Any");
});

test("extension reports field as unsupported or needing input, dashboard shows clear next action and never claims submitted", async ({
  page,
}) => {
  const { packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await login(page);
  await page.goto(`/applications/${packet_id}`);
  await expect(
    page.getByRole("heading", { name: "Local browser assistant" }),
  ).toBeVisible();

  // Synchronize packet evidence following prior profile updates
  const refreshBtn = page.getByRole("button", {
    name: "Refresh profile & saved evidence",
  });
  if (await refreshBtn.isVisible()) {
    const refreshResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        response.url().includes(`/application-packets/${packet_id}`),
    );
    await refreshBtn.click();
    const response = await refreshResponse;
    expect(response.ok()).toBeTruthy();
    const refreshedPacket = await response.json();
    expect(refreshedPacket.revision).toBeGreaterThan(1);
    await expect(
      page.getByText(new RegExp(`Revision ${refreshedPacket.revision}\\b`)),
    ).toBeVisible();
  }

  // Approve dedicated browser
  await page
    .getByLabel("I approve a dedicated browser profile", { exact: false })
    .check();
  await page
    .getByLabel("I approve credential-free loading", { exact: false })
    .check();

  // Open browser and analyze application
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  const analyzeBtn = page.getByRole("button", { name: "Analyze Application" });
  await expect(analyzeBtn).toBeEnabled({ timeout: 45000 });
  await analyzeBtn.click();
  await expect(
    page.getByRole("status").filter({ hasText: /^analyzed$/ }),
  ).toBeVisible({ timeout: 45000 });

  // Verify non-submission notice is displayed
  await expect(
    page.getByText(
      "Non-submission notice: Autofill does NOT submit your application",
      { exact: false },
    ),
  ).toBeVisible();

  // Check the unfilled mandatory questions section with clear next action link
  const reviewCheck = page.getByLabel(
    "I reviewed the current answers, destination and selected resume below.",
  );
  const contextCheck = page.getByLabel(
    "I confirmed the actual page belongs to this company and job.",
  );
  await reviewCheck.check();
  await contextCheck.check();

  const fillBtn = page.getByRole("button", { name: "Fill supported fields" });
  await fillBtn.click();
  await expect(
    page.getByRole("status").filter({ hasText: "filled review on website" }),
  ).toBeVisible({ timeout: 45000 });

  // Verify the unanswered field reports needing attention
  await expect(
    page.getByText("Current CTC: Answer missing or invalid", { exact: true }),
  ).toBeVisible();

  // Verify clear next action deep-link to Needs Your Input queue
  const needsInputLink = page.getByRole("link", {
    name: "Open 'Needs your input' queue",
  });
  await expect(needsInputLink).toBeVisible();
  await expect(needsInputLink).toHaveAttribute("href", "/needs-input");

  // Verify Submit button remains disabled
  await expect(
    page.getByRole("button", { name: "Submit", exact: true }),
  ).toBeDisabled();

  // Navigate to applications pipeline and verify it is NEVER marked as "Submitted"
  await page.goto("/applications");
  await expect(
    page.getByRole("heading", { name: "Your search is taking shape." }),
  ).toBeVisible();

  // Application packet must be in "Needs Input", never "Applied — User Reported" or "Applied — Provider Confirmed"
  const needsInputColumn = page
    .locator(".kanban-column")
    .filter({ hasText: "Needs Input" });
  await expect(
    needsInputColumn.getByText("Example Circuit", { exact: false }),
  ).toBeVisible();
  const appliedColumn = page
    .locator(".kanban-column")
    .filter({ hasText: "Applied — User Reported" });
  await expect(
    appliedColumn.getByText("Example Circuit", { exact: false }),
  ).not.toBeVisible();
});
