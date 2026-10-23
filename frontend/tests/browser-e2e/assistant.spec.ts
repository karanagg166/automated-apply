import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

async function approveBrowser(page: Page) {
  await page
    .getByLabel("I approve a dedicated browser profile", { exact: false })
    .check();
  await page
    .getByLabel("I approve credential-free loading", { exact: false })
    .check();
}

test.afterEach(async ({ page }) => {
  const manifest = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === "aa_csrf",
  )?.value;
  if (!csrf) return;
  for (const id of [
    manifest.packet_id,
    manifest.mock_packet_id,
    manifest.opportunity_packet_id,
    manifest.guided_packet_id,
    manifest.slow_packet_id,
    manifest.navigation_packet_id,
    manifest.complete_packet_id,
    manifest.asset_packet_id,
    manifest.dropdown_packet_id,
  ].filter(Boolean)) {
    const response = await page.request.get(
      `/api/backend/browser-applications/${id}/operation`,
    );
    if (response.status() !== 200) continue;
    const control = await response.json();
    const state = control.active_operation
      ? null
      : await (
          await page.request.get(`/api/backend/browser-applications/${id}`)
        ).json();
    if (control.active_operation || state?.connected) {
      const closed = await page.request.post(
        `/api/backend/browser-applications/${id}/actions`,
        {
          headers: { Origin: "http://localhost:3101", "X-CSRF-Token": csrf },
          data: {
            action: "cancel",
            expected_revision:
              control.active_operation?.expected_revision ??
              control.packet_revision,
            operation_id: control.active_operation?.id ?? null,
          },
        },
      );
      expect(closed.status()).toBe(200);
    }
  }
});

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
  await approveBrowser(page);
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
  const takeover = page.waitForResponse(
    (response) =>
      response.url().endsWith("/actions") &&
      response.request().postDataJSON()?.action === "take_over",
  );
  await page.getByRole("button", { name: "Take Over", exact: true }).click();
  expect((await takeover).status()).toBe(200);
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
  await approveBrowser(page);
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
  await approveBrowser(page);
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
  const generated = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes(`/application-packets/${opportunity_packet_id}/questions/`) &&
      response.url().endsWith("/generate") &&
      response.request().method() === "POST",
    { timeout: 45000 },
  );
  await question
    .getByRole("button", { name: "Generate with configured AI" })
    .click();
  expect((await generated).status()).toBe(200);
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
  const savedReview = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/application-packets/${opportunity_packet_id}/review`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save field review" }).click();
  const reviewResponse = await savedReview;
  expect(reviewResponse.status()).toBe(200);
  const reviewedPacket = await reviewResponse.json();
  await expect(
    page
      .getByText(`Revision ${reviewedPacket.revision}`, { exact: false })
      .first(),
  ).toBeVisible();
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

test("owner fills grouped choices and explicitly advances an in-page application step", async ({
  page,
}) => {
  const { guided_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${guided_packet_id}`);
  await approveBrowser(page);
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeEnabled({ timeout: 45000 });
  await page.getByRole("button", { name: "Analyze Application" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /^analyzed$/ }),
  ).toBeVisible();
  async function answer(question: string, value: string) {
    const field = page
      .locator(".evidence-item")
      .filter({ hasText: question })
      .first();
    await field.getByLabel("Reviewable answer").fill(value);
    const saved = page.waitForResponse(
      (response) =>
        response
          .url()
          .includes(`/application-packets/${guided_packet_id}/questions/`) &&
        response.request().method() === "PATCH",
    );
    await field
      .getByRole("button", { name: "Save answer", exact: true })
      .click();
    const response = await saved;
    expect(response.status()).toBe(200);
    const updated = await response.json();
    await expect(
      page.getByText(`Revision ${updated.revision}`, { exact: false }).first(),
    ).toBeVisible();
  }
  async function reviewAndFill() {
    for (const checkbox of await page
      .getByLabel("I reviewed this exact answer")
      .all())
      await checkbox.check();
    const reviewed = page.waitForResponse(
      (response) =>
        response
          .url()
          .endsWith(`/application-packets/${guided_packet_id}/review`) &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Save field review" }).click();
    const response = await reviewed;
    expect(response.status()).toBe(200);
    const updated = await response.json();
    await expect(
      page.getByText(`Revision ${updated.revision}`, { exact: false }).first(),
    ).toBeVisible();
    await page
      .getByLabel(
        "I reviewed the current answers, destination and selected resume below.",
      )
      .check();
    await page
      .getByLabel(
        "I confirmed the actual page belongs to this company and job.",
      )
      .check();
    await page.getByRole("button", { name: "Fill supported fields" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "filled review on website" }),
    ).toBeVisible();
  }
  await answer("Remote work preference", "remote");
  await reviewAndFill();
  await page.getByText("Review next application step", { exact: true }).click();
  await page.getByRole("button", { name: "Preview next step" }).click();
  await expect(
    page.getByRole("cell", { name: "remote", exact: true }),
  ).toBeVisible();
  const next = page.getByRole("button", { name: "Authorize Next step" });
  await expect(next).toBeDisabled();
  await page
    .getByLabel(
      "I reviewed the actual values and every selected consent before advancing this step.",
    )
    .check();
  await next.click();
  await expect(
    page.getByRole("status").filter({ hasText: "next step analyzed" }),
  ).toBeVisible();
  await answer("Department", "Engineering");
  await answer("Availability date", "2050-01-01");
  await reviewAndFill();
  await expect(
    page.getByRole("button", { name: "Submit", exact: true }),
  ).toBeDisabled();
});

test("owner cancels an opening browser while its navigation is still in flight", async ({
  page,
}) => {
  const { slow_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${slow_packet_id}`);
  await approveBrowser(page);
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  await expect(
    page.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeEnabled();
  await expect
    .poll(async () => {
      const response = await page.request.get(
        `/api/backend/browser-applications/${slow_packet_id}/operation`,
      );
      return (await response.json()).active_operation?.kind;
    })
    .toBe("open");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeEnabled({ timeout: 15000 });
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeDisabled();
  const state = await (
    await page.request.get(
      `/api/backend/browser-applications/${slow_packet_id}`,
    )
  ).json();
  expect(state.connected).toBe(false);
  expect(state.active_operation).toBeNull();
  expect(state.cancellation_pending).toBe(false);
  expect(state.packet.tracking_state).toBe("not_applied");
});

test("owner resumes after a manual server step through the signed dashboard review", async ({
  page,
  request,
}) => {
  const { navigation_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${navigation_packet_id}`);
  await approveBrowser(page);
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeEnabled({ timeout: 45000 });
  await page.getByRole("button", { name: "Analyze Application" }).click();
  await expect(page.getByText("analyzed", { exact: true })).toBeVisible();
  const takeover = page.waitForResponse(
    (response) =>
      response.url().endsWith("/actions") &&
      response.request().postDataJSON()?.action === "take_over",
  );
  await page.getByRole("button", { name: "Take Over", exact: true }).click();
  expect((await takeover).status()).toBe(200);
  // The testing-only fixture controls its own dedicated page to simulate the
  // human's save. This fixed action is absent from the production application.
  const manual = await request.post(
    "http://127.0.0.1:8767/_fictional_test/owner-server-step",
    {
      headers: { Authorization: "Bearer fictional-browser-demo-owner-token" },
    },
  );
  expect(manual.status()).toBe(200);
  expect((await manual.json()).server_save_count).toBe(1);
  await page.getByRole("button", { name: "Get status" }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeDisabled();
  await page
    .getByText("Resume after manual navigation", { exact: true })
    .click();
  await page.getByRole("button", { name: "Preview current page" }).click();
  const authorize = page.getByRole("button", {
    name: "Authorize page and analyze",
  });
  await expect(authorize).toBeVisible();
  await expect(authorize).toBeDisabled();
  await page
    .getByLabel("I checked this page is part of the same company", {
      exact: false,
    })
    .check();
  const resumed = page.waitForResponse(
    (response) =>
      response.url().endsWith("/resume-page") &&
      response.request().method() === "POST",
  );
  await authorize.click();
  expect((await resumed).status()).toBe(200);
  await expect(
    page.getByText("owner page resumed", { exact: true }),
  ).toBeVisible();
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
    page.getByText("filled review on website", { exact: true }),
  ).toBeVisible();
  const state = await (
    await page.request.get(
      `/api/backend/browser-applications/${navigation_packet_id}`,
    )
  ).json();
  expect(state.analysis.page_context.url).toMatch(/\/server-step-two$/);
  expect(state.analysis.navigation_history).toHaveLength(1);
  expect(
    state.analysis.validation.some(
      (field: { complete: boolean }) => field.complete,
    ),
  ).toBe(true);
  expect(state.packet.tracking_state).toBe("not_applied");
  expect(state.automated_submission_enabled).toBe(false);
});

test("owner generates a grounded company answer and completes one authorized mock application", async ({
  page,
}) => {
  const { complete_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${complete_packet_id}`);
  await approveBrowser(page);
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
    "Example Circuit AI builds task management tools.",
  );
  await page
    .getByLabel("I checked the company, job, source and selected excerpts.")
    .check();
  await page.getByRole("button", { name: "Save reviewed job context" }).click();
  await expect(
    page.getByText("Reviewed context saved.", { exact: false }),
  ).toBeVisible();
  const analyzed = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/browser-applications/${complete_packet_id}/actions`) &&
      response.request().postDataJSON()?.action === "analyze",
  );
  await page.getByRole("button", { name: "Analyze Application" }).click();
  const analyzedResponse = await analyzed;
  expect(analyzedResponse.status()).toBe(200);
  const analyzedState = await analyzedResponse.json();
  await expect(
    page
      .getByText(`Revision ${analyzedState.packet.revision}`, { exact: false })
      .first(),
  ).toBeVisible();
  const question = page
    .locator(".evidence-item")
    .filter({ hasText: "Why do you want to join our company?" })
    .first();
  const generated = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes(`/application-packets/${complete_packet_id}/questions/`) &&
      response.url().endsWith("/generate") &&
      response.request().method() === "POST",
    { timeout: 45000 },
  );
  await question
    .getByRole("button", { name: "Generate with configured AI" })
    .click();
  expect((await generated).status()).toBe(200);
  const proposed =
    "Example Circuit AI builds task management tools. I built backend authentication using Python and FastAPI.";
  await expect(question.getByLabel("Reviewable answer")).toHaveValue(proposed);
  for (const checkbox of await page
    .getByLabel("I reviewed this exact answer")
    .all())
    await checkbox.check();
  await page.getByLabel("I reviewed the selected resume variant.").check();
  await page
    .getByLabel("I verified this is the official application destination.")
    .check();
  const savedReview = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/application-packets/${complete_packet_id}/review`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save field review" }).click();
  const reviewResponse = await savedReview;
  expect(reviewResponse.status()).toBe(200);
  const reviewedPacket = await reviewResponse.json();
  await expect(
    page
      .getByText(`Revision ${reviewedPacket.revision}`, { exact: false })
      .first(),
  ).toBeVisible();
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
    page.getByRole("status").filter({ hasText: /^filled review on website$/ }),
  ).toBeVisible();
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
    page
      .getByRole("region", { name: "Mock submission review" })
      .getByText(proposed, { exact: false }),
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
  await page.reload();
  await page.getByRole("button", { name: "Get status" }).click();
  await expect(
    page.getByText("Verified mock receipt: MOCK-", { exact: false }),
  ).toBeVisible();
  const state = await (
    await page.request.get(
      `/api/backend/browser-applications/${complete_packet_id}`,
    )
  ).json();
  expect(state.packet.lifecycle_state).toBe("provider_confirmed_submitted");
  expect(state.packet.tracking_state).toBe("applied_verified");
  expect(state.execution.adapter).toBe("local_mock_v2");
  expect(state.page_review_required).toBe(false);
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeDisabled();
  await expect(
    page.getByText("Resume after manual navigation", { exact: true }),
  ).toHaveCount(0);
  expect(state.execution.receipt.fixture).toBe("automated-apply-employer-v2");
  const saved = state.packet.fields.find(
    (field: { question: string }) =>
      field.question === "Why do you want to join our company?",
  );
  expect(saved.effective_answer).toBe(proposed);
  expect(saved.provenance.answer_draft_id).toBeTruthy();
  const evidence = await page.request.get(
    `/api/backend/application-answers/drafts/${saved.provenance.answer_draft_id}/opportunity-evidence`,
  );
  expect(evidence.status()).toBe(200);
  expect((await evidence.json()).evidence.length).toBeGreaterThan(0);
  expect(state.real_employer_submission_enabled).toBe(false);
});

test("owner approves public asset origins before inspecting and filling an external-script form", async ({
  page,
}) => {
  const { asset_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${asset_packet_id}`);
  await page
    .getByLabel("I approve a dedicated browser profile", { exact: false })
    .check();
  await expect(
    page.getByLabel("I approve credential-free loading", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open dedicated browser" }),
  ).toBeDisabled();
  await page
    .getByLabel("I approve credential-free loading", { exact: false })
    .check();
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  await expect(
    page.getByRole("button", { name: "Analyze Application" }),
  ).toBeEnabled({ timeout: 45000 });
  await page.getByRole("button", { name: "Analyze Application" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /^analyzed$/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Public asset loading closed:", { exact: false }),
  ).toBeVisible();
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
    page.getByRole("status").filter({ hasText: /^filled review on website$/ }),
  ).toBeVisible();
  const response = await page.request.get(
    `/api/backend/browser-applications/${asset_packet_id}`,
  );
  const state = await response.json();
  expect(state.assets.sealed).toBe(true);
  expect(state.assets.requests).toBe(2);
  expect(state.assets.bytes).toBeGreaterThan(0);
  expect(
    state.analysis.validation.some(
      (field: { complete: boolean }) => field.complete,
    ),
  ).toBe(true);
  expect(state.packet.tracking_state).toBe("not_applied");
  expect(state.automated_submission_enabled).toBe(false);
});

test("owner manually loads remote choices then reviews and fills a transient dropdown", async ({
  page,
  request,
}) => {
  const { dropdown_packet_id } = JSON.parse(
    readFileSync("../reports/browser-mock.private.json", "utf8"),
  );
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`/applications/${dropdown_packet_id}`);
  await approveBrowser(page);
  await page.getByRole("button", { name: "Open dedicated browser" }).click();
  const analyze = page.getByRole("button", { name: "Analyze Application" });
  await expect(analyze).toBeEnabled({ timeout: 45000 });
  const blocked = page.waitForResponse(
    (response) =>
      response.url().endsWith("/actions") &&
      response.request().postDataJSON()?.action === "analyze",
  );
  await analyze.click();
  expect((await blocked).status()).toBe(409);
  const takeover = page.waitForResponse(
    (response) =>
      response.url().endsWith("/actions") &&
      response.request().postDataJSON()?.action === "take_over",
  );
  await page.getByRole("button", { name: "Take Over", exact: true }).click();
  expect((await takeover).status()).toBe(200);
  const manual = await request.post(
    "http://127.0.0.1:8767/_fictional_test/owner-load-choices",
    {
      headers: { Authorization: "Bearer fictional-browser-demo-owner-token" },
    },
  );
  expect(manual.status()).toBe(200);
  expect((await manual.json()).choice_loads).toBe(1);
  await analyze.click();
  await expect(
    page.getByRole("status").filter({ hasText: /^analyzed$/ }),
  ).toBeVisible();
  const field = page
    .locator(".evidence-item")
    .filter({ hasText: "Preferred city" })
    .first();
  await expect(
    field.getByText("Choose one exact option: Pune · Bengaluru"),
  ).toBeVisible();
  await field.getByLabel("Reviewable answer").fill("Bengaluru");
  const saved = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes(`/application-packets/${dropdown_packet_id}/questions/`) &&
      response.request().method() === "PATCH",
  );
  await field.getByRole("button", { name: "Save answer", exact: true }).click();
  const edited = await saved;
  expect(edited.status()).toBe(200);
  await expect(
    page
      .getByText(`Revision ${(await edited.json()).revision}`, { exact: false })
      .first(),
  ).toBeVisible();
  for (const checkbox of await page
    .getByLabel("I reviewed this exact answer")
    .all())
    await checkbox.check();
  const reviewed = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/application-packets/${dropdown_packet_id}/review`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save field review" }).click();
  const review = await reviewed;
  expect(review.status()).toBe(200);
  await expect(
    page
      .getByText(`Revision ${(await review.json()).revision}`, { exact: false })
      .first(),
  ).toBeVisible();
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
    page.getByRole("status").filter({ hasText: /^filled review on website$/ }),
  ).toBeVisible();
  const state = await (
    await page.request.get(
      `/api/backend/browser-applications/${dropdown_packet_id}`,
    )
  ).json();
  const city = state.analysis.fields.find(
    (item: { question: string }) => item.question === "Preferred city",
  );
  expect(city.choices_on_open).toBe(true);
  expect(
    state.analysis.validation.find(
      (item: { field_id: string }) => item.field_id === city.field_id,
    ).complete,
  ).toBe(true);
  expect(
    state.packet.fields.find(
      (item: { id: string }) => item.id === city.field_id,
    ).effective_answer,
  ).toBe("Bengaluru");
  expect(state.packet.tracking_state).toBe("not_applied");
  expect(state.automated_submission_enabled).toBe(false);
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
  const approval = page.waitForResponse(
    (response) =>
      response.url().endsWith("/approve-reuse") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Approve answer reuse" }).click();
  expect((await approval).status()).toBe(200);
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
