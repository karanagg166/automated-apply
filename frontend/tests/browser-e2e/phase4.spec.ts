import { test, expect, type Page, type BrowserContext } from "@playwright/test";

const backend = "http://127.0.0.1:8767/api/v1";
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

test("combined dashboard filters country and publication evidence before pagination and preserves packet idempotency", async ({
  page,
  request,
}) => {
  const data = {
    source: "manual",
    use_profile: false,
    allow_paid: false,
    idempotency_key: "phase4-browser-contract-ingestion",
    query: { limit: 25 },
    manual_jobs: Array.from({ length: 22 }, (_, index) => ({
      source_name: "manual",
      source_job_id: `phase4-contract-${index}`,
      original_url: `https://fictional-phase4.example/jobs/${index}`,
      title:
        index === 0
          ? "Phase4 Contract India Engineer"
          : `Phase4 Contract France Engineer ${index}`,
      company_name: "Phase4 Fictional Labs",
      country: index === 0 ? "India" : "France",
      location: index === 0 ? "Bengaluru" : "Paris",
      experience_level: "Junior",
      experience_min_years: 0,
      experience_max_years: 3,
      date_posted: new Date().toISOString(),
    })),
  };
  const runResponse = await request.post(`${backend}/discovery/runs`, {
    headers,
    data,
  });
  expect(runResponse.status()).toBe(200);
  const run = await runResponse.json();
  expect(run.counts.inserted).toBe(22);
  const replay = await request.post(`${backend}/discovery/runs`, {
    headers,
    data,
  });
  expect((await replay.json()).id).toBe(run.id);
  await login(page);
  await page.goto("/jobs");
  await page.getByLabel("Job title").fill("Phase4 Contract");
  await expect(page.getByText("Page 1 of 2")).toBeVisible();
  // The India record was inserted first and is outside the newest 20 records.
  await expect(
    page.getByText("Phase4 Contract India Engineer", { exact: true }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: /^🇮🇳 India/ }).click();
  await expect(
    page.getByText("Phase4 Contract India Engineer", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Page 1 of 1")).toBeVisible();
  await page.getByRole("button", { name: /More filters/ }).click();
  await page
    .locator("select")
    .filter({ has: page.locator('option[value="junior"]') })
    .selectOption("junior");
  await page
    .locator("select")
    .filter({ has: page.locator('option[value="14"]') })
    .selectOption("14");
  await expect(
    page.getByText("Phase4 Contract India Engineer", { exact: true }),
  ).toBeVisible();
  const row = page
    .getByRole("row")
    .filter({ hasText: "Phase4 Contract India Engineer" });
  const job = await (
    await request.get(
      `${backend}/jobs/search?role=Phase4%20Contract&country=IN`,
      { headers },
    )
  ).json();
  expect(job.total).toBe(1);
  expect(job.jobs[0].source_verification_status).toBe("requires_review");
  const jobId = job.jobs[0].id;
  const packetData = { idempotency_key: "phase4-browser-contract-packet" };
  const packetResponse = await request.post(
    `${backend}/jobs/${jobId}/application-packets`,
    { headers, data: packetData },
  );
  expect(packetResponse.status()).toBe(201);
  const packet = await packetResponse.json();
  const packetReplay = await request.post(
    `${backend}/jobs/${jobId}/application-packets`,
    { headers, data: packetData },
  );
  expect((await packetReplay.json()).id).toBe(packet.id);
  expect(packet.lifecycle_state).not.toContain("submitted");
  expect(packet.snapshot.preparation_supported).toBe(false);
  await expect(row).toBeVisible();
  await page.screenshot({
    path: "../reports/phase4-integrated-jobs-fictional.png",
    fullPage: true,
  });
});

test("source availability and form compatibility remain evidence based on the running API", async ({
  page,
  request,
}) => {
  const response = await request.get(`${backend}/discovery/sources`, {
    headers,
  });
  expect(response.status()).toBe(200);
  const { sources } = await response.json();
  for (const id of ["simplify", "workday", "company_careers"]) {
    expect(
      sources.find((source: { id: string }) => source.id === id),
    ).toMatchObject({
      adapter_type: "manual",
      availability: "manual_import_only",
      live_verified: false,
    });
  }
  const smart = sources.find(
    (source: { id: string }) => source.id === "smartrecruiters",
  );
  expect(smart).toMatchObject({
    adapter_type: "direct_api",
    availability: "configuration_required",
    live_verified: false,
  });
  const run = await request.post(`${backend}/discovery/runs`, {
    headers,
    data: {
      source: "smartrecruiters",
      use_profile: false,
      query: { limit: 1 },
      idempotency_key: "phase4-browser-unconfigured-smartrecruiters",
    },
  });
  expect((await run.json()).status).toBe("configuration_required");
  await login(page);
  await page.goto("/jobs");
  await expect(page.getByLabel("Supported Job Sources")).toContainText(
    "manual import only",
  );
  await expect(page.getByLabel("Supported Job Sources")).not.toContainText(
    "✓ Verified",
  );
});
