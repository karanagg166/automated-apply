// Explicit opt-in public read-only acceptance. Fresh Chromium context, no profile,
// credentials, candidate facts, clicking, filling, challenge interaction or submission.
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { writeFile, mkdir } from "node:fs/promises";
import { formDOM } from "../form-dom.js";
if (process.env.PHASE52_PUBLIC_INSPECTION !== "1")
  throw Error("explicit_public_inspection_opt_in_required");
const destinations = [
  [
    "Razorpay Greenhouse",
    "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited/jobs/4744950005",
  ],
  [
    "Cloudflare Greenhouse",
    "https://job-boards.greenhouse.io/cloudflare/jobs/8097321",
  ],
  [
    "Veeva Lever expired posting",
    "https://jobs.lever.co/veeva/79256ab7-1862-4195-9f8b-87735247d017/apply",
  ],
  [
    "Veeva Lever current posting",
    "https://jobs.lever.co/veeva/52ba79af-1086-457d-b5d2-8e184f111ffd/apply",
  ],
  [
    "Hevo Lever saved packet",
    "https://jobs.lever.co/hevodata/6cbbe304-e065-4711-bf3e-756795d2bc2a/apply",
  ],
  [
    "Sarvam Ashby",
    "https://jobs.ashbyhq.com/sarvam/fcb15601-6440-41f7-aa79-b9992057a4b2/application",
  ],
];
const browser = await chromium.launch({ headless: true });
const observations = [];
try {
  for (const [site, url] of destinations) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const record = {
      site,
      requested_url: url,
      observed_at: new Date().toISOString(),
      entered_candidate_data: false,
      fill_attempted: false,
      submitted: false,
    };
    try {
      const response = await page.goto(url, {
        waitUntil: "domcontentloaded",
        timeout: 30000,
      });
      record.http_status = response?.status();
      // Wait for client-rendered controls, bounded when a site is unavailable.
      await page
        .locator("input:not([type=hidden]),textarea,select")
        .first()
        .waitFor({ timeout: 12000 })
        .catch(() => {});
      await page.waitForTimeout(1500);
      record.final_url = page.url();
      record.page_title = await page.title();
      const cdp = await context.newCDPSession(page);
      const { frameTree } = await cdp.send("Page.getFrameTree");
      const { executionContextId } = await cdp.send(
        "Page.createIsolatedWorld",
        {
          frameId: frameTree.frame.id,
          worldName: "automated-apply-phase52-readonly",
        },
      );
      const result = await cdp.send("Runtime.callFunctionOn", {
        executionContextId,
        functionDeclaration: formDOM.toString(),
        arguments: [
          {
            value: {
              operation: "inspect",
              only_empty: true,
              interactions_allowed: true,
            },
          },
        ],
        returnByValue: true,
        awaitPromise: true,
      });
      if (result.exceptionDetails) throw Error("inspection_script_failed");
      const inspection = result.result.value;
      // Save public semantic metadata only; never page HTML, cookies or challenge data.
      record.state = inspection.state;
      record.challenge_state =
        inspection.challenge_state || inspection.security_status || "UNKNOWN";
      record.manual_reason = inspection.manual_reason;
      record.fields = (inspection.fields || []).map(
        ({
          label,
          kind,
          group_label,
          section,
          required,
          preview_only,
          manual_reason,
          semantic_key,
        }) => ({
          label,
          kind,
          group_label,
          section,
          required,
          preview_only,
          manual_reason,
          semantic_key,
        }),
      );
      record.unsupported_controls = inspection.unsupported_controls || [];
      record.has_next = inspection.has_next;
      record.has_submit = inspection.has_submit;
    } catch (error) {
      record.error =
        error.name === "TimeoutError"
          ? "navigation_or_render_timeout"
          : error.message;
    }
    observations.push(record);
    console.log(
      JSON.stringify({
        site,
        state: record.state,
        challenge_state: record.challenge_state,
        fields: record.fields?.length,
        unsupported: record.unsupported_controls?.length,
        error: record.error,
      }),
    );
    await context.close();
  }
} finally {
  await browser.close();
}
const directory = new URL("../../docs/phase52/", import.meta.url);
await mkdir(directory, { recursive: true });
await writeFile(
  new URL("live-inspection.json", directory),
  JSON.stringify(
    {
      methodology:
        "Fresh isolated Chromium, public navigation and isolated-world DOM inspection only; no profile, candidate data, clicks, filling or submissions.",
      observations,
    },
    null,
    2,
  ) + "\n",
);
