import { test, expect } from "@playwright/test";

test("exact submission review and uncertain receipt recovery controls", async ({
  page,
}) => {
  const id = "11111111-1111-4111-8111-111111111111";
  let record = {
    application_id: id,
    job_id: "22222222-2222-4222-8222-222222222222",
    employer: "Fictional Fixture Employer",
    job_title: "Backend Engineer",
    state: "awaiting_submission_approval",
    origin: "http://127.0.0.1:18765",
    application_url:
      "http://127.0.0.1:18765/fixtures/lever/example/jobs/2/apply",
    request_url:
      "http://127.0.0.1:18765/fixtures/lever/example/jobs/2/applications",
    candidate_version: 2,
    packet_revision: 3,
    campaign_revision: 4,
    review_digest: "a".repeat(64),
    pdf_digest: "b".repeat(64),
    project_digest: "c".repeat(64),
    document_digest: "d".repeat(64),
    nonce: id,
    expires_at: "2099-01-01T00:00:00Z",
    authorization: null as unknown,
    released: false,
    evidence: null as unknown,
  };
  const actions: string[] = [];
  await page.route("**/api/backend/browser/submissions**", async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: [record] });
    const action = route.request().url().split("/").at(-1)!;
    actions.push(action);
    if (action === "approve") {
      expect(route.request().postDataJSON()).toEqual({
        nonce: id,
        review_digest: "a".repeat(64),
        campaign_revision: 4,
        application_ids: [id],
        maximum_count: 1,
        scope: "submit_application",
      });
      record = { ...record, authorization: { owner: "primary" } };
    }
    if (action === "execute")
      record = { ...record, state: "submission_uncertain", released: true };
    if (action === "reconcile")
      record = {
        ...record,
        state: "submitted",
        evidence: {
          type: "application_acknowledgment",
          application_id: "fixture-receipt-2",
          destination: record.request_url,
          timestamp: "2026-10-26T10:00:00Z",
          correlation_id: id,
        },
      };
    return route.fulfill({ json: record });
  });
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/agent");
  const review = page.getByRole("region", { name: "Submission review" });
  await expect(review.getByText(`Selected application: ${id}`)).toBeVisible();
  const authorize = review.getByRole("button", {
    name: "Authorize this one application",
  });
  await expect(authorize).toBeDisabled();
  await review.getByRole("checkbox").check();
  await page.screenshot({
    path: "../reports/submission-review.png",
    fullPage: true,
  });
  await authorize.click();
  await review
    .getByRole("button", { name: "Submit this approved application" })
    .click();
  await expect(
    review.getByText("Submission uncertain", { exact: true }),
  ).toBeVisible();
  await expect(
    review.getByRole("button", { name: "Submit this approved application" }),
  ).toHaveCount(0);
  await review
    .getByRole("button", { name: "Check receipt without resubmitting" })
    .click();
  await expect(
    review.getByText("Submitted with evidence", { exact: true }),
  ).toBeVisible();
  await expect(review.getByText(/fixture-receipt-2/)).toBeVisible();
  expect(actions).toEqual(["approve", "execute", "reconcile"]);
});
