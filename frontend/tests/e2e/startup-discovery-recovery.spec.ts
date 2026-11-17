import { expect, test } from "@playwright/test";
import { login } from "./owner-session";
test("startup response loss retains original UUID across reload and finishes company results locally without another PUT", async ({
  page,
  context,
}, testInfo) => {
  const source = {
    provider: "hacker_news",
    modes: ["job_led"],
    availability: "available",
    configured: true,
    authorized: true,
    pricing: "free",
    native_execution_implemented: true,
  };
  const child = "20000000-0000-0000-0000-000000000002";
  let saved: Record<string, unknown> | null = null;
  let puts = 0,
    gets = 0,
    completes = 0;
  await context.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/backend/", "");
    if (path === "startups/sources")
      return route.fulfill({ json: { sources: [source] } });
    if (path === "startups/discovery/preview")
      return route.fulfill({
        json: {
          source,
          query: { keywords: [], locations: [] },
          provider_calls: 0,
          writes: 0,
          job_led_available: true,
          message: "Fictional startup preview only",
        },
      });
    const match =
      /^startups\/discovery\/runs\/([a-f0-9-]{36})(\/complete)?$/.exec(path);
    if (!match) return route.fallback();
    if (request.method() === "PUT") {
      puts += 1;
      expect(puts).toBe(1);
      expect(request.postDataJSON()).toMatchObject({
        source: "hacker_news",
        mode: "job_led",
        allow_paid: false,
      });
      saved = {
        id: match[1],
        source: "startup_hacker_news",
        status: "running",
        counts: {},
        errors: [],
        rankings: [],
        finished_at: null,
        local_intake_complete: false,
        usage: { finding_retained: true },
        application_dispatch: false,
        live_verified: false,
        child_run: {
          id: child,
          status: "success",
          local_intake_complete: true,
          rankings_complete: true,
        },
      };
      return route.abort("connectionreset");
    }
    if (!saved)
      return route.fulfill({
        status: 404,
        json: { detail: "No original admission" },
      });
    if (match[2]) {
      expect(request.method()).toBe("POST");
      expect(request.postDataJSON()).toEqual({});
      completes += 1;
      Object.assign(saved, {
        status: "success",
        local_intake_complete: true,
        finished_at: "2026-11-17T00:03:00Z",
        counts: { companies_observed: 1, companies_matching: 1 },
      });
    } else {
      expect(request.method()).toBe("GET");
      gets += 1;
    }
    return route.fulfill({ json: saved });
  });
  await login(page);
  await page.goto("/discover");
  await page
    .getByRole("tab", { name: "Startup discovery", exact: true })
    .click();
  await page.getByRole("button", { name: "Preview startup discovery" }).click();
  await expect(
    page.getByRole("button", { name: "Run approved startup discovery" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Run this bounded startup search" })
    .check();
  await page
    .getByRole("button", { name: "Run approved startup discovery" })
    .click();
  await expect.poll(() => puts).toBe(1);
  await expect(
    page.getByText(/request timed out or the network is unavailable/i),
  ).toBeVisible();
  const pointer = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("startup-discovery-attempt:v1")!),
  );
  expect(Object.keys(pointer).sort()).toEqual(["requestId", "source"]);
  await page.reload();
  await page
    .getByRole("tab", { name: "Startup discovery", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Complete saved startup search" }),
  ).toBeVisible();
  expect(puts).toBe(1);
  expect(completes).toBe(0);
  expect(gets).toBeGreaterThan(0);
  await page
    .getByRole("button", { name: "Complete saved startup search" })
    .click();
  await expect(page.getByText("Run result: Success")).toBeVisible();
  expect(completes).toBe(1);
  expect(puts).toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("startup-discovery-attempt:v1")!),
    ),
  ).toEqual(pointer);
  await page.screenshot({
    path: testInfo.outputPath("fictional-startup-discovery-recovery.png"),
    fullPage: true,
  });
});
