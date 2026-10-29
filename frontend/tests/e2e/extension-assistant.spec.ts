import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const packetId = "11111111-1111-4111-8111-111111111111";
const taskId = "33333333-3333-4333-8333-333333333333";
const packet = {
  id: packetId,
  job_id: "22222222-2222-4222-8222-222222222222",
  platform: "greenhouse",
  lifecycle_state: "ready_for_review",
  tracking_state: "not_applied",
  revision: 3,
  approved_revision: null,
  review_status: "pending",
  submission_mode: "manual_handoff",
  fields: [
    {
      id: "55555555-5555-4555-8555-555555555555",
      question: "Email",
      category: "contact_information",
      field_type: "text",
      required: true,
      max_characters: 200,
      max_words: null,
      writing_style: "professional",
      validation_status: "draft_ready",
      review_status: "pending",
      effective_answer: "alex@example.com",
      proposed_answer: "alex@example.com",
      answer_revision: 1,
      requires_review: true,
      provenance: {
        origin: "packet_core",
        source: "candidate_profile",
        resolver: "deterministic",
        evidence_references: [],
      },
    },
  ],
  readiness: {
    state: "needs_review",
    blockers: [],
    manual_steps: [],
    warnings: [],
    stale: false,
  },
  snapshot: {
    preparation_supported: true,
    company_name: "Fictional Employer",
    job_title: "Platform Engineer",
    source_platform: "greenhouse",
    original_job_url: "https://fictional.example/jobs/platform",
    context_digest: "fictional-phase52-context",
    destination: {
      application_url: "https://fictional.example/apply/platform",
      kind: "employer_external",
      valid: true,
      source_confidence: "source_consistent",
      warnings: [],
    },
    resume: {
      selected: null,
      alternatives: [],
      reason: "Fictional fixture",
      upload_status: "manual_resume_upload_required",
    },
    warnings: [],
  },
  created_at: "2026-10-29T09:00:00Z",
  updated_at: "2026-10-29T09:00:00Z",
};

function task() {
  return {
    id: taskId,
    version: 7,
    application_id: packetId,
    job_id: packet.job_id,
    company_name: "Fictional Employer",
    job_title: "Platform Engineer",
    packet_revision: 3,
    profile_version: 5,
    target_url: packet.snapshot.destination.application_url,
    current_url: "https://fictional.example/apply/platform/experience",
    tab_id: 12,
    tab_active: false,
    browser_connection: "connected",
    state: "CHALLENGE_REQUIRED",
    challenge_state: "WIDGET_PRESENT_UNVERIFIED",
    step: "Employment history",
    plan_id: null,
    authorization_id: null,
    field_answer_revisions: {},
    reason: null,
    next_action:
      "Complete the security check yourself, then inspect and review this step again in Chrome.",
    mode: "ASSISTED_FILL",
    capabilities: {
      preview: true,
      assisted_fill: false,
      reviewed_submission: false,
      unattended_approved: false,
    },
    counts: {
      ready: 2,
      completed: 0,
      existing: 3,
      missing: 1,
      manual: 2,
      validation_errors: 1,
    },
    updated_at: "2026-10-29T09:00:00Z",
  };
}

async function login(page: Page) {
  await page.goto("/login");
  await page
    .getByLabel("Owner passphrase")
    .fill("fictional-ui-owner-passphrase");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL("/");
}

test("shows challenge and packet context, preserves a versioned pause and prevents stale resume", async ({
  page,
}) => {
  let currentTask = task();
  let currentPacket = { ...packet };
  const controls: unknown[] = [];
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/backend/",
      "",
    );
    let data: unknown = [];
    if (path === "integrations") data = { connectors: [] };
    else if (path === "dashboard/runtime") data = { demo_mode: true };
    else if (path === `application-packets/${packetId}`) data = currentPacket;
    else if (path === `browser/extension-tasks/application/${packetId}`)
      data = currentTask;
    else if (path === `browser/extension-tasks/${taskId}/control`) {
      const body = route.request().postDataJSON();
      controls.push(body);
      expect(body).toEqual({ action: "pause", expected_version: 7 });
      currentTask = {
        ...currentTask,
        state: "PAUSED",
        version: 8,
        browser_connection: "paused",
      };
      data = currentTask;
    } else if (path === "browser-applications/policy")
      data = { origins: [], digest: "fictional" };
    await route.fulfill({ json: data });
  });
  await login(page);
  await page.goto(`/applications/${packetId}`);
  const assistant = page.getByRole("region", {
    name: "Chrome extension assistant",
  });
  await expect(
    assistant.getByText("Fictional Employer · Platform Engineer"),
  ).toBeVisible();
  await expect(
    assistant.getByText(/Security widget present; completion is unverified/),
  ).toBeVisible();
  await expect(assistant.getByText(/Another tab is active/)).toBeVisible();
  await expect(
    assistant.getByText("Unattended approved: disabled"),
  ).toBeVisible();
  await expect(
    assistant.getByText("Assisted fill: disabled for this task"),
  ).toBeVisible();
  const screenshotDir = resolve("../docs/phase52/screenshots");
  await mkdir(screenshotDir, { recursive: true });
  await assistant.screenshot({
    path: resolve(screenshotDir, "extension-dashboard-challenge-fictional.png"),
  });
  await expect(page.getByText("Evidence & Provenance")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Reviewable answer" }),
  ).toHaveValue("alex@example.com");
  await page.screenshot({
    path: resolve(screenshotDir, "extension-field-review-fictional.png"),
    fullPage: true,
  });
  await assistant.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(
    assistant.getByRole("button", { name: "Resume", exact: true }),
  ).toBeEnabled();
  currentPacket = { ...packet, revision: 4 };
  await page.reload();
  await expect(assistant.getByText(/The current revision is 4/)).toBeVisible();
  await expect(
    assistant.getByRole("button", { name: "Resume", exact: true }),
  ).toBeDisabled();
  await assistant.screenshot({
    path: resolve(screenshotDir, "extension-dashboard-stale-fictional.png"),
  });
  expect(controls).toEqual([{ action: "pause", expected_version: 7 }]);
  await expect(
    assistant.getByRole("button", { name: /fill|submit/i }),
  ).toHaveCount(0);
});
