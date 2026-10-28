import { test, expect } from "@playwright/test";

const backend = "http://127.0.0.1:8767/api/v1";
const headers = { Authorization: "Bearer fictional-browser-demo-owner-token" };

test("three-account workspace persists reviewed history and local drafts with every Gmail write gate closed", async ({
  page,
  request,
}) => {
  const profile = await (
    await request.get(`${backend}/profile`, { headers })
  ).json();
  expect(
    (
      await request.post(`${backend}/local-agent/profile-confirmation`, {
        headers,
        data: { expected_version: profile.version, owner_confirmed: true },
      })
    ).ok(),
  ).toBe(true);
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/connections");
  await page.getByRole("tab", { name: "Connected Gmail accounts" }).click();
  const first = page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Account 1 · Read only" }),
  });
  const second = page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Account 2 · Read only" }),
  });
  const outreach = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Account 3 · Outreach drafts only",
    }),
  });
  await expect(first).toContainText("first-fixture@example.com");
  await expect(second).toContainText("second-fixture@example.com");
  await expect(
    outreach.getByRole("button", { name: "Connect with Google" }),
  ).toBeDisabled();
  for (const [index, card] of [first, second].entries()) {
    await card.getByRole("button", { name: "Review email evidence" }).click();
    await card
      .getByLabel("Reviewed company", { exact: true })
      .fill("Reviewed History Fictional Team");
    await card.getByLabel("Reviewed job role").fill("Backend Engineer");
    await card.getByLabel("Reviewed status").selectOption("interview");
    await card.getByLabel("I confirm I applied for this exact role").check();
    await card
      .getByLabel("I reviewed company, role, date, status and evidence")
      .check();
    await card
      .getByRole("button", { name: "Save reviewed application history" })
      .click();
    await expect(
      card.getByText(
        "Reviewed history saved separately from raw email metadata.",
      ),
    ).toBeVisible();
    await expect
      .poll(async () => {
        const data = await (
          await request.get(`${backend}/integrations/gmail/workspace/history`, {
            headers,
          })
        ).json();
        return Object.keys(
          data.history.find(
            (h: any) => h.company === "Reviewed History Fictional Team",
          ).evidence,
        ).length;
      })
      .toBe(index + 1);
  }
  const history = await (
    await request.get(`${backend}/integrations/gmail/workspace/history`, {
      headers,
    })
  ).json();
  expect(
    history.history.filter(
      (h: any) => h.company === "Reviewed History Fictional Team",
    ),
  ).toHaveLength(1);
  expect(history.history[0].confirmed_application).toBe(true);
  await first.getByLabel("Inbox", { exact: true }).check();
  await first.getByLabel("Sent Mail", { exact: true }).check();
  await first.getByLabel("Historical lookback (months, maximum 24)").fill("24");
  await first.getByRole("button", { name: "Save account settings" }).click();
  await expect
    .poll(async () => {
      const data = await (
        await request.get(
          `${backend}/integrations/gmail/accounts/10000000-0000-4000-8000-000000000001`,
          { headers },
        )
      ).json();
      return data.sync.policy.history_months;
    })
    .toBe(24);
  await page.getByLabel("Outreach recipient").fill("founder@fictional.example");
  await page.getByLabel("Outreach company").fill("Fictional Outreach Team");
  await page.getByLabel("Outreach role").fill("Backend Engineer");
  await page
    .getByLabel("Personalized context you reviewed")
    .fill("I reviewed your public Python infrastructure work.");
  await page
    .getByRole("button", { name: "Prepare local outreach draft" })
    .click();
  await expect(page.getByLabel("Draft subject")).toHaveValue(
    "Backend Engineer opportunities at Fictional Outreach Team",
  );
  await page
    .getByLabel("Draft subject")
    .fill("Owner edited fictional outreach");
  await page.getByRole("button", { name: "Save draft edits locally" }).click();
  await expect
    .poll(async () => {
      const data = await (
        await request.get(`${backend}/integrations/gmail/workspace/drafts`, {
          headers,
        })
      ).json();
      return data.drafts[0].content.subject;
    })
    .toBe("Owner edited fictional outreach");
  await expect(
    page.getByRole("button", { name: "Save reviewed draft in Gmail" }),
  ).toBeDisabled();
  expect(
    (
      await request.post(
        `${backend}/integrations/gmail/workspace/drafts/${(await (await request.get(`${backend}/integrations/gmail/workspace/drafts`, { headers })).json()).drafts[0].id}/create-in-gmail`,
        {
          headers,
          data: {
            expected_version: 2,
            content_hash: "a".repeat(64),
            owner_reviewed: true,
            expected_account_generation: 2,
          },
        },
      )
    ).status(),
  ).toBe(409);
  const audit = await (
    await request.get(
      "http://127.0.0.1:8767/_fictional_test/phase3-provider-audit",
      { headers },
    )
  ).json();
  expect(audit.mailbox_writes).toBe(0);
  expect(audit.external_requests).toBe(0);
  await page.screenshot({
    path: test.info().outputPath("gmail-workspace-fictional.png"),
    fullPage: true,
  });
});
