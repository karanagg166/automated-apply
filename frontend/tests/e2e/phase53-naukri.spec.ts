import { mkdir } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { login } from "./owner-session";

const id = "11111111-1111-4111-8111-111111111111";
test("Naukri review keeps unknown fit, uncertain delivery and versioned controls honest", async ({
  page,
}) => {
  let revision = 1;
  let state = "DISCOVERED";
  const controls: unknown[] = [];
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/backend/",
      "",
    );
    let data: unknown = [];
    if (path === "integrations") data = { connectors: [] };
    else if (path === "dashboard/runtime") data = { demo_mode: true };
    else if (path === "execution/naukri")
      data = {
        configuration: {
          mode: "ON_DEMAND",
          interval_seconds: 21600,
          source: "saved_owner_imports",
          destinations: [],
          submission_permission: false,
        },
        executions: [
          {
            id,
            job_id: id,
            packet_id: null,
            role: "Fictional Backend Engineer",
            employer: "Fictional Labs",
            state,
            revision,
            diagnostic: null,
          },
        ],
        capabilities: { live_verified: false },
        account_session: {
          state: "browser_session_observed",
          last_verification_time: "2026-10-29T12:00:00Z",
          evidence_type: "extension_gesture_dom_indicator",
        },
      };
    else if (path === "execution/naukri/jobs")
      data = {
        jobs: [
          {
            id,
            title: "Fictional Backend Engineer",
            job_url:
              "https://www.naukri.com/job-listings-fictional-291026123456",
            profile_version: 1,
            vacancy_review: "unverified",
            state: "NEEDS_INPUT",
            reason: "required_experience_unknown",
            match: {
              match_score: 45,
              matched_skills: ["Python"],
              missing_skills: [],
              unknown_fields: ["experience_suitability"],
              negative_factors: [],
              explanation:
                "Experience is unknown; no seniority points awarded.",
            },
          },
        ],
      };
    else if (path === "execution/questions")
      data = [
        {
          id: "q-unknown",
          execution_id: id,
          employer: "Fictional Labs",
          role: "Backend Engineer",
          question: "What is your notice period?",
          state: "delivery_unknown",
          packet_revision: 2,
          expires_at: "2099-01-01T00:00:00Z",
          reuse_approved: false,
        },
      ];
    else if (path === `execution/${id}/control`) {
      const body = route.request().postDataJSON();
      expect(body.expected_revision).toBe(revision);
      controls.push(body);
      revision++;
      state =
        body.action === "pause"
          ? "PAUSED"
          : body.action === "cancel"
            ? "FAILED_FINAL"
            : "DISCOVERED";
      data = { id, state, revision };
    } else if (route.request().method() !== "GET")
      throw Error(`Unexpected mutation ${path}`);
    await route.fulfill({ json: data });
  });
  await login(page);
  await page.goto("/naukri");
  const panel = page.getByRole("region", { name: "Naukri preparation" });
  await expect(
    panel.getByText(
      /does not verify account identity or a Naukri API connection/,
    ),
  ).toBeVisible();
  await expect(
    panel.getByText("Experience is unknown; no seniority points awarded."),
  ).toBeVisible();
  await expect(
    panel.getByText(/this prompt will not be automatically resent/),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Submit Answer from Dashboard" }),
  ).toHaveCount(0);
  await panel.getByRole("button", { name: "pause", exact: true }).click();
  await expect(panel.getByText("PAUSED", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "resume", exact: true }).click();
  await expect(panel.getByText("DISCOVERED", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "cancel", exact: true }).click();
  await expect(panel.getByText("FAILED FINAL", { exact: true })).toBeVisible();
  expect(controls).toEqual([
    { action: "pause", expected_revision: 1 },
    { action: "resume", expected_revision: 2 },
    { action: "cancel", expected_revision: 3 },
  ]);
  await mkdir("../docs/phase53/screenshots", { recursive: true });
  await panel.screenshot({
    path: "../docs/phase53/screenshots/naukri-review-fictional.png",
  });
});

test("two connected Chrome profiles require explicit selection and show offline honestly", async ({
  page,
}) => {
  const personal = "a1111111-1111-4111-8111-111111111111";
  const jobs = "b1111111-1111-4111-8111-111111111111";
  let selection = { version: 3, profile_binding_id: personal };
  const mutations: unknown[] = [];
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/backend/",
      "",
    );
    let data: unknown = [];
    if (path === "integrations") data = { connectors: [] };
    else if (path === "dashboard/runtime") data = { demo_mode: true };
    else if (
      ["dashboard/connections", "contact-enrichment/providers"].includes(path)
    )
      data = { providers: [] };
    else if (path === "local-agent/policy")
      data = { version: 1, default: "approve", platforms: {} };
    else if (path === "browser/chrome-profiles")
      data = {
        selection,
        channel_available: false,
        commands: [],
        profiles: [
          {
            id: personal,
            label: "Personal Chrome (fictional)",
            selected: selection.profile_binding_id === personal,
            version: 2,
            connected: true,
            status: "CONNECTED",
            last_heartbeat: "2026-10-29T10:00:00Z",
            browser_session_id: id,
            window_id: 7,
            commands_enabled: false,
          },
          {
            id: jobs,
            label: "Job applications (fictional)",
            selected: selection.profile_binding_id === jobs,
            version: 1,
            connected: true,
            status: "PROFILE_OFFLINE",
            last_heartbeat: "2026-10-28T10:00:00Z",
            browser_session_id: id,
            window_id: 8,
            commands_enabled: false,
          },
        ],
      };
    else if (path === "browser/chrome-profiles/select") {
      const body = route.request().postDataJSON();
      mutations.push(body);
      expect(body).toEqual({ profile_binding_id: jobs, expected_version: 3 });
      selection = { version: 4, profile_binding_id: jobs };
      data = selection;
    } else if (route.request().method() !== "GET")
      throw Error(`Unexpected mutation ${path}`);
    await route.fulfill({ json: data });
  });
  await login(page);
  await page.goto("/connections");
  const panel = page.getByRole("region", { name: "Connected Chrome profiles" });
  await expect(
    panel.getByText("Personal Chrome (fictional)", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByText(`Binding: ${jobs}`)).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Use Personal Chrome (fictional)" }),
  ).toBeDisabled();
  expect(mutations).toEqual([]);
  await panel
    .getByRole("button", { name: "Use Job applications (fictional)" })
    .click();
  await expect(
    panel.getByText(/PROFILE_OFFLINE: Job applications/),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Use Personal Chrome (fictional)" }),
  ).toBeEnabled();
  expect(mutations).toHaveLength(1);
  await mkdir("../docs/phase53/screenshots", { recursive: true });
  await panel.screenshot({
    path: "../docs/phase53/screenshots/chrome-profiles-fictional.png",
  });
});
