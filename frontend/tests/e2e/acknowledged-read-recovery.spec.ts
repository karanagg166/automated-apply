import { expect, test } from "@playwright/test";
import { login } from "./owner-session";
test("acknowledged read response loss retains its UUID across reload and reads finished pages back without another provider read", async ({
  page,
  context,
}, testInfo) => {
  const parent = "10000000-0000-0000-0000-000000000001";
  const budget = {
    reserved_usd: "0.100001",
    accounting: "full_cap_retained",
    billing_final: false,
  };
  const source = {
    id: "naukri",
    display_name: "Fictional Naukri discovery",
    adapter_type: "apify",
    operations: ["jobs"],
    availability: "available",
    pricing: "paid",
    enabled: true,
    read_only: true,
    owner_run_supported: true,
    live_verified: false,
    configuration: {
      native_execution: {
        ready: true,
        run_cap_usd: "0.100001",
        monthly_limit_usd: "2.000001",
      },
    },
  };
  let puts = 0,
    gets = 0,
    finished = false;
  let saved: Record<string, unknown> | null = null;
  await context.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/backend/", "");
    if (path === "discovery/sources")
      return route.fulfill({ json: { sources: [source] } });
    const run = () => ({
      id: parent,
      source: "naukri",
      status: finished ? "success" : "recovery_required",
      counts: {
        discovered: finished ? 1 : 0,
        inserted: finished ? 1 : 0,
        updated: 0,
        skipped: 0,
      },
      errors: [],
      started_at: "2026-11-17T00:00:00Z",
      finished_at: finished ? "2026-11-17T00:03:00Z" : null,
      provider_run_id: "originalRun",
      rankings: [],
      job_ids: finished ? ["30000000-0000-0000-0000-000000000003"] : [],
      local_intake_complete: finished,
      rankings_complete: finished,
      original_scope_available: true,
      billing_final: false,
      reservation: budget,
      usage: {
        finding_retained: saved?.finding_retained === true,
        read_rounds_admitted: saved ? 1 : 0,
        read_round_limit: 3,
        last_read_request_id: saved?.read_request_id ?? null,
        read_next_allowed_at: null,
      },
    });
    if (path === `discovery/runs/${parent}`) {
      expect(request.method()).toBe("GET");
      return route.fulfill({ json: run() });
    }
    const match = new RegExp(
      `^discovery/runs/${parent}/reads/([a-f0-9-]{36})$`,
    ).exec(path);
    if (!match) return route.fallback();
    if (request.method() === "PUT") {
      puts += 1;
      expect(puts).toBe(1);
      expect(request.postDataJSON()).toEqual({});
      saved = {
        request_id: parent,
        read_request_id: match[1],
        source: "naukri",
        recorded_state: "response_retained",
        status: "pending",
        finding_retained: false,
        local_merge_available: true,
        read_round_limit: 3,
        read_admissions: 1,
        round: 1,
        http_attempts: 3,
        http_responses: 3,
        http_counts_are_minimum: false,
        errors: [],
        admitted_at: "2026-11-17T00:02:00Z",
        expires_at: "2026-11-17T00:02:45Z",
        billing_final: false,
        provider_status: "SUCCEEDED",
        provider_start_authorized: false,
        provider_abort_authorized: false,
        replay_authorized: false,
        application_dispatch: false,
        live_verified: false,
        reservation: budget,
      };
      return route.abort("connectionreset");
    }
    if (!saved)
      return route.fulfill({
        status: 404,
        json: { detail: "No read admission" },
      });
    expect(request.method()).toBe("GET");
    gets += 1;
    return route.fulfill({ json: saved });
  });
  await login(page);
  await page.goto("/discover");
  await page.evaluate(
    (parent) =>
      localStorage.setItem(
        "job-discovery-attempt:v1",
        JSON.stringify({ requestId: parent, source: "naukri" }),
      ),
    parent,
  );
  await page.reload();
  const read = page.getByRole("button", { name: "Read acknowledged run" });
  await expect(read).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Allow bounded acknowledged run read" })
    .check();
  await read.click();
  await expect.poll(() => puts).toBe(1);
  const pointer = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("job-discovery-read:v1")!),
  );
  expect(Object.keys(pointer).sort()).toEqual(["readId", "requestId"]);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Refresh saved read" }).first(),
  ).toBeVisible();
  await expect.poll(() => gets).toBeGreaterThan(0);
  expect(puts).toBe(1);
  // The server merges the saved pages on its own; the dashboard only reads them back.
  Object.assign(saved!, {
    finding_retained: true,
    local_merge_available: false,
    recorded_state: "finding_retained",
    status: "finding_retained",
  });
  finished = true;
  await page
    .getByRole("button", { name: "Refresh saved read" })
    .first()
    .click();
  await expect(page.getByText("Saved (New): 1")).toBeVisible();
  expect(puts).toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("job-discovery-read:v1")!),
    ),
  ).toEqual(pointer);
  await page.screenshot({
    path: testInfo.outputPath("fictional-acknowledged-read-recovery.png"),
    fullPage: true,
  });
});
