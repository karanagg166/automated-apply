import { expect, test, type Page } from "@playwright/test";
import { login } from "./owner-session";
test("research UUID survives a lost response across real browser tabs and reload without another PUT", async ({
  page,
  context,
}, testInfo) => {
  const company = "10000000-0000-0000-0000-000000000001";
  const results = new Map<string, unknown>();
  let puts = 0,
    gets = 0,
    legacy = 0;
  await context.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/backend/", "");
    if (path === "startups/search")
      return route.fulfill({
        json: {
          startups: [
            {
              company_id: company,
              company_name: "Fictional Research Company",
              company_domain: "company-fixture.example",
            },
          ],
        },
      });
    if (path === `companies/${company}/contacts`)
      return route.fulfill({ json: { contacts: [] } });
    if (path === `companies/${company}/people`)
      return route.fulfill({ json: { people: [] } });
    if (path === "discovery/people/search") {
      legacy += 1;
      return route.fulfill({
        status: 428,
        json: { detail: "Unkeyed search is forbidden in this fixture" },
      });
    }
    const match =
      /^rust-agent\/research\/people\/requests\/([a-f0-9-]{36})$/.exec(path);
    if (!match) return route.fallback();
    const id = match[1];
    if (request.method() === "PUT") {
      puts += 1;
      expect(request.postDataJSON()).toMatchObject({
        company_name: "Fictional Research Company",
        company_domain: "company-fixture.example",
        limit: 5,
        allow_paid: true,
      });
      results.set(id, {
        request_id: id,
        company_id: company,
        status: "success",
        recorded_state: "completed",
        persistence_status: "imported",
        people: [],
      });
      return route.abort("connectionreset"); // The fictional server committed before response loss.
    }
    expect(request.method()).toBe("GET");
    gets += 1;
    const result = results.get(id);
    return result
      ? route.fulfill({ json: result })
      : route.fulfill({ status: 404, json: { detail: "No admission" } });
  });
  await login(page);
  await page.goto("/people");
  await page.evaluate(
    (company) => localStorage.removeItem(`people-research-attempt:${company}`),
    company,
  );
  const second = await context.newPage();
  await second.goto("/people");
  async function select(target: Page) {
    await target.getByLabel("Choose a saved company").selectOption(company);
    await target
      .getByText("Review an optional founder / leader research plan")
      .click();
  }
  await select(page);
  await select(second);
  expect(await page.evaluate(() => Boolean(navigator.locks?.request))).toBe(
    true,
  );
  await page
    .getByRole("checkbox", {
      name: /I authorize this limited official-company research/,
    })
    .check();
  await page.getByRole("button", { name: "Run approved research" }).click();
  await expect.poll(() => puts).toBe(1);
  await expect(
    page.getByText(/request timed out or the network is unavailable/i),
  ).toBeVisible();
  const original = await page.evaluate(
    (company) =>
      JSON.parse(localStorage.getItem(`people-research-attempt:${company}`)!),
    company,
  );
  expect(Object.keys(original).sort()).toEqual(["companyId", "requestId"]);
  await second
    .getByRole("checkbox", {
      name: /I authorize this limited official-company research/,
    })
    .check();
  await second.getByRole("button", { name: "Run approved research" }).click();
  await expect(second.getByText(/Research results are saved/)).toBeVisible();
  expect(puts).toBe(1);
  expect(gets).toBeGreaterThan(0);
  expect(legacy).toBe(0);
  await page.reload();
  await select(page);
  await page.getByRole("button", { name: "Recover saved research" }).click();
  await expect(page.getByText(/Research results are saved/)).toBeVisible();
  expect(puts).toBe(1);
  expect(legacy).toBe(0);
  expect(
    await page.evaluate(
      (company) =>
        JSON.parse(localStorage.getItem(`people-research-attempt:${company}`)!),
      company,
    ),
  ).toEqual(original);
  await page.screenshot({
    path: testInfo.outputPath("people-research-recovery.png"),
    fullPage: true,
  });
});
