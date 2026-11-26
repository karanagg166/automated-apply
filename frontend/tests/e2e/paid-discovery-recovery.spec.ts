import { expect, test } from "@playwright/test";
import { login } from "./owner-session";
test("paid discovery retains its UUID and full reservation across response loss and reload, then recovers with saved GETs", async ({
  page,
  context,
}, testInfo) => {
  const source = {
    id: "naukri",
    display_name: "Fictional paid Naukri",
    adapter_type: "apify",
    operations: ["jobs"],
    authentication: "local token",
    availability: "available",
    pricing: "paid",
    enabled: true,
    read_only: true,
    mutation_capabilities: [],
    live_verified: false,
    owner_run_supported: true,
    configuration: {
      native_execution: {
        ready: true,
        run_cap_usd: "0.100001",
        monthly_limit_usd: "2.000001",
      },
    },
  };
  let puts = 0,
    gets = 0;
  const saved = new Map<string, Record<string, unknown>>();
  await context.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/backend/", "");
    if (path === "discovery/sources")
      return route.fulfill({ json: { sources: [source] } });
    if (path === "discovery/preview") {
      expect(request.postDataJSON()).toMatchObject({
        source: "naukri",
        allow_paid: true,
      });
      return route.fulfill({
        json: {
          source,
          query: request.postDataJSON().query,
          jobs: [],
          provider_calls: 0,
          writes: 0,
          estimated_usd: 0.02,
          estimate_only: true,
          message: "Fictional saved preview; no provider calls",
          paid_execution: {
            ready: true,
            run_cap_usd: "0.100001",
            monthly_limit_usd: "2.000001",
          },
        },
      });
    }
    const match = /^discovery\/runs\/([a-f0-9-]{36})$/.exec(path);
    if (!match) return route.fallback();
    const id = match[1];
    if (request.method() === "PUT") {
      puts += 1;
      expect(puts).toBe(1);
      expect(request.postDataJSON()).toMatchObject({
        source: "naukri",
        allow_paid: true,
      });
      saved.set(id, {
        id,
        source: "naukri",
        status: "running",
        counts: { discovered: 1, inserted: 0, updated: 0, skipped: 0 },
        errors: [],
        started_at: "2026-11-17T00:00:00Z",
        finished_at: null,
        provider_run_id: "fictionalOriginalRun",
        rankings: [],
        job_ids: [],
        usage: { finding_retained: true },
        local_intake_complete: false,
        rankings_complete: false,
        original_scope_available: true,
        billing_final: false,
        reservation: {
          reserved_usd: "0.100001",
          accounting: "full_cap_retained",
          billing_final: false,
        },
      });
      return route.abort("connectionreset");
    }
    const result = saved.get(id);
    if (!result)
      return route.fulfill({ status: 404, json: { detail: "No admission" } });
    expect(request.method()).toBe("GET");
    gets += 1;
    return route.fulfill({ json: result });
  });
  await login(page);
  await page.goto("/discover");
  await page
    .getByRole("combobox", { name: "Discovery source provider" })
    .selectOption("naukri");
  await expect(
    page.getByRole("button", { name: "Preview discovery plan" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Allow this paid discovery" })
    .check();
  await page.getByRole("button", { name: "Preview discovery plan" }).click();
  await expect(
    page.getByRole("button", { name: "Run approved discovery" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /Run this approved job discovery/ })
    .check();
  await page.getByRole("button", { name: "Run approved discovery" }).click();
  await expect.poll(() => puts).toBe(1);
  await expect(
    page.getByRole("button", { name: "Recover interrupted discovery" }),
  ).toBeVisible();
  const pointer = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("job-discovery-attempt:v1")!),
  );
  expect(Object.keys(pointer).sort()).toEqual(["requestId", "source"]);
  await page.reload();
  await expect(
    page.getByText(/Retained reservation: \$0.100001/),
  ).toBeVisible();
  expect(puts).toBe(1);
  expect(gets).toBeGreaterThan(0);
  await expect(
    page.getByRole("checkbox", { name: "Allow this paid discovery" }),
  ).not.toBeChecked();
  // The server finishes the retained finding on its own; the dashboard only reads it back.
  for (const result of saved.values())
    Object.assign(result, {
      status: "success",
      counts: { discovered: 1, inserted: 1, updated: 0, skipped: 0 },
      job_ids: ["30000000-0000-0000-0000-000000000001"],
      finished_at: "2026-11-17T00:00:02Z",
      local_intake_complete: true,
      rankings_complete: true,
    });
  await page.getByRole("button", { name: "Recover saved discovery" }).click();
  await expect(page.getByText("Saved (New): 1")).toBeVisible();
  expect(puts).toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("job-discovery-attempt:v1")!),
    ),
  ).toEqual(pointer);
  await page.screenshot({
    path: testInfo.outputPath("fictional-paid-discovery-recovery.png"),
    fullPage: true,
  });
});
