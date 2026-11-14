// Headless disposable Chromium and a fictional loopback service; never owner Chrome.
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
const root = fileURLToPath(new URL("../../", import.meta.url));
const frontend = root + "frontend/";
const require = createRequire(frontend + "package.json");
const { chromium } = require("@playwright/test");
const token = "fictional-browser-fixture-token-0123456789";
const id = "11111111-1111-4111-8111-111111111111";
const approvalId = "22222222-2222-4222-8222-222222222222";
let revision = 12,
  firstApproval = true,
  mutations = [];
const graph = () => ({
  node: "human_approval",
  plan_revision: revision - 11,
  iteration: revision - 12,
  maximum_replans: 2,
  human_review: true,
  decision_summary: "Fictional validated checkpoint",
  approvals: [
    {
      id: approvalId,
      scope: { kind: "review" },
      status: "pending",
      plan_revision: revision - 11,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    },
  ],
});
const run = () => ({
  id,
  revision,
  state: "waiting_approval",
  role: "execution",
  diagnostic: null,
  model_policy: { provider: "deterministic" },
  usage: {
    model_calls: 0,
    tool_calls: 4,
    decision_calls: 8,
    reserved_tokens: 0,
  },
  graph: graph(),
});
const backend = createServer(async (request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.headers.authorization !== `Bearer ${token}`) {
    response.writeHead(401);
    response.end("{}");
    return;
  }
  const path = request.url.replace("/api/v1/rust-agent/", "");
  let result;
  if (request.method === "POST") {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    mutations.push(body);
    assert.equal(body.expected_revision, revision);
    assert.equal(body.decision, "approve");
    if (firstApproval) {
      firstApproval = false;
      revision++;
      response.writeHead(409);
      result = { error: "agent_revision_conflict" };
    } else result = run();
  } else if (path === "runs") result = { runs: [run()] };
  else if (path === "control")
    result = { mode: "PAUSED", revision: 1, worker_online: true };
  else if (path === "capabilities")
    result = {
      review_model: "deterministic",
      recommended_limits: {},
      application_dispatch: false,
    };
  else if (path === `runs/${id}/plan`)
    result = {
      run_id: id,
      revision,
      graph: graph(),
      prepared_results: [
        {
          tool: "rank_jobs",
          evidence: [id],
          trust: "Fictional observed data",
          data: { score: 80, text: "<img src=x onerror=alert(1)>" },
        },
      ],
      pending_tool: null,
      approval_grants_submission: false,
    };
  else {
    response.writeHead(404);
    result = { error: "fixture_route_not_found" };
  }
  response.end(JSON.stringify(result));
});
await new Promise((resolve) => backend.listen(0, "127.0.0.1", resolve));
const probe = createServer();
await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise((resolve) => probe.close(resolve));
const origin = `http://127.0.0.1:${port}`;
process.env.FRONTEND_ORIGIN = origin;
process.env.FRONTEND_LOCAL_HTTP = "true";
process.env.FRONTEND_SESSION_SECRET =
  "fictional-browser-secret-minimum-thirty-two-characters";
const { issueSession, csrfFor } =
  await import("../../frontend/src/lib/security.ts");
const session = issueSession();
const child = spawn(
  process.execPath,
  ["run.mjs", "start", "-H", "127.0.0.1", "-p", String(port)],
  {
    cwd: frontend,
    env: {
      PATH: process.env.PATH,
      NODE_ENV: "production",
      FRONTEND_ISOLATED: "1",
      FRONTEND_ORIGIN: origin,
      FRONTEND_LOCAL_HTTP: "true",
      FRONTEND_SESSION_SECRET: process.env.FRONTEND_SESSION_SECRET,
      RUST_AGENT_URL: `http://127.0.0.1:${backend.address().port}`,
      JOB_AGENT_API_TOKEN: token,
      NEXT_TELEMETRY_DISABLED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
// Keep potentially sensitive runtime output in memory; publish only fixed assertions.
let diagnostics = "";
child.stdout.on("data", (b) => (diagnostics += b));
child.stderr.on("data", (b) => (diagnostics += b));
let browser;
try {
  const deadline = Date.now() + 20000;
  while (true) {
    try {
      if ((await fetch(origin + "/login")).ok) break;
    } catch {}
    if (Date.now() > deadline || child.exitCode !== null)
      throw new Error("fixture_frontend_not_ready");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: "aa_owner",
      value: session,
      url: origin,
      httpOnly: true,
      sameSite: "Strict",
    },
    {
      name: "aa_csrf",
      value: csrfFor(session),
      url: origin,
      sameSite: "Strict",
    },
  ]);
  const page = await context.newPage();
  // Shell's independent legacy API reads are fictional; no existing service is contacted.
  await page.route("**/api/backend/**", (route) =>
    route.fulfill({ json: { connectors: [], demo_mode: false } }),
  );
  await page.goto(origin + "/workflow");
  await page
    .getByRole("heading", { name: "Agent workflow", exact: true })
    .waitFor();
  await page.getByText("Plan 1 · checkpoint 12.", { exact: false }).waitFor();
  const approve = page.getByRole("button", { name: "Approve checkpoint" });
  assert.equal(await approve.isDisabled(), true);
  await page
    .getByRole("button", { name: "Review / replan", exact: true })
    .click();
  assert.equal(
    await page
      .getByRole("button", { name: "Review / replan", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  await page.getByRole("checkbox").check();
  await approve.click();
  await page
    .getByRole("alert")
    .filter({ hasText: "checkpoint changed" })
    .waitFor();
  assert.equal(mutations.length, 1);
  await page.getByRole("button", { name: "Refresh status" }).click();
  await page.getByText("Plan 2 · checkpoint 13.", { exact: false }).waitFor();
  assert.equal(await page.getByRole("checkbox").isChecked(), false);
  assert.equal(await approve.isDisabled(), true);
  await page.getByRole("checkbox").check();
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/approvals/") && response.status() === 200,
    ),
    approve.click(),
  ]);
  assert.equal(mutations.length, 2);
  await page.getByText("rank_jobs · 1 evidence references").click();
  assert.equal(await page.locator("img[src=x]").count(), 0);
  const artifact = root + "rust/ui/workflow-fictional.png";
  await page
    .getByRole("heading", { name: "Agent workflow", exact: true })
    .click();
  await page.screenshot({ path: artifact, fullPage: true });
  console.log(
    JSON.stringify({
      result: "PASS",
      journeys: 1,
      approval_mutations: mutations.length,
      automatic_retries: 0,
      screenshot: "rust/ui/workflow-fictional.png",
      scope: "headless_fictional_no_owner_browser_or_live_service",
    }),
  );
} finally {
  await browser?.close();
  if (child.exitCode === null) {
    child.kill("SIGTERM");
    await once(child, "exit");
  }
  backend.closeAllConnections();
  await new Promise((resolve) => backend.close(resolve));
}
