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
    page.getByText("Reviewed lead imported.", { exact: false }),
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
