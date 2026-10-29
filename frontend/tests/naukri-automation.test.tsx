import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  NaukriAutomation,
  type NaukriAutomationStatus,
} from "@/features/naukri-automation";
import { api, post } from "@/lib/api";
import { permittedRoute } from "@/lib/gateway";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());
const data: NaukriAutomationStatus = {
  state: "RUNNING",
  revision: 7,
  scope: "PARTIAL_PREPARATION",
  source: "saved_owner_imports",
  policy: {
    profile_version: 3,
    resume_resource_id: "11111111-1111-4111-8111-111111111111",
    resume_version: "a".repeat(64),
    allowed_roles: ["Backend Developer"],
    allowed_locations: ["India"],
    excluded_companies: [],
    experience_min: 0,
    experience_max: 3,
    minimum_match_score: 90,
    interval_seconds: 900,
    max_preparations_per_day: 2,
    telegram_questions: false,
  },
  worker_online: false,
  worker_heartbeat_at: null,
  last_observation: null,
  chrome_profile: null,
  blockers: [
    "execution_worker_offline",
    "recurring_external_source_not_connected",
  ],
  counts: { prepared: 2, submitted_confirmed: 0, unknown: 1 },
  stages: { SUBMISSION: "unsupported" },
  policy_context: {
    profile_version: 3,
    resume: {
      resource_id: "11111111-1111-4111-8111-111111111111",
      resource_version: "a".repeat(64),
      label: "Approved resume",
    },
  },
  decisions: [],
};
const act = async (work: () => Promise<unknown>) => {
  await work();
};
it("shows persisted status and truthful blockers without dispatch on render", () => {
  render(<NaukriAutomation data={data} busy={false} act={act} />);
  expect(screen.getByText(/Persisted state/)).toHaveTextContent("RUNNING");
  expect(screen.getByText(/Worker:/)).toHaveTextContent("Offline");
  expect(screen.getByText(/Selected Chrome profile/)).toHaveTextContent(
    "None selected",
  );
  expect(
    screen.getByText(/recurring external source not connected/i),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "START AUTOMATION" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});
it("keeps Gmail intake deferred to Phase 5.4", () => {
  render(<NaukriAutomation data={data} busy={false} act={act} />);
  expect(
    screen.getByRole("option", {
      name: /job-alert emails.*deferred to Phase 5.4/i,
    }),
  ).toBeDisabled();
  expect(screen.getByText(/two-account Naukri alert detection/)).toBeVisible();
  expect(api).not.toHaveBeenCalled();
  expect(post).not.toHaveBeenCalled();
});
it("sends versioned Stop and Pause commands through the backend", async () => {
  render(<NaukriAutomation data={data} busy={false} act={act} />);
  await userEvent.click(
    screen.getByRole("button", { name: "STOP AUTOMATION" }),
  );
  expect(post).toHaveBeenCalledWith("execution/naukri/automation/control", {
    action: "stop",
    expected_revision: 7,
  });
  await userEvent.click(
    screen.getByRole("button", { name: "PAUSE AUTOMATION" }),
  );
  expect(post).toHaveBeenCalledWith("execution/naukri/automation/control", {
    action: "pause",
    expected_revision: 7,
  });
});
it("saves bounded policy and pins the reviewed profile and resume without starting", async () => {
  render(<NaukriAutomation data={data} busy={false} act={act} />);
  await userEvent.click(
    screen.getByRole("button", { name: "Save bounded preparation policy" }),
  );
  expect(api).toHaveBeenCalledWith(
    "execution/naukri/automation/policy",
    expect.objectContaining({ method: "PUT" }),
  );
  const options = vi.mocked(api).mock.calls[0][1];
  const body = JSON.parse(options?.body as string);
  expect(body.expected_revision).toBe(7);
  expect(body.policy).toMatchObject({
    profile_version: 3,
    resume_version: "a".repeat(64),
    max_preparations_per_day: 2,
    telegram_questions: false,
  });
  expect(post).not.toHaveBeenCalled();
});
it("exposes only approved gateway methods and denies a submission route", () => {
  expect(permittedRoute("execution/naukri/automation/control", "POST")).toBe(
    true,
  );
  expect(permittedRoute("execution/naukri/automation/policy", "PUT")).toBe(
    true,
  );
  expect(permittedRoute("execution/naukri/automation/control", "GET")).toBe(
    false,
  );
  expect(permittedRoute("execution/naukri/automation/submit", "POST")).toBe(
    false,
  );
});
