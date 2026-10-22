import { defineConfig, devices } from "@playwright/test";
import { scryptSync } from "node:crypto";

const salt = "0123456789abcdef0123456789abcdef"; // pragma: allowlist secret — fixed fictional fixture
const password = "fictional-ui-owner-passphrase"; // pragma: allowlist secret — fixture only
export default defineConfig({
  testDir: "./tests/browser-e2e",
  outputDir: "./test-results-browser",
  workers: 1,
  timeout: 90000,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://localhost:3101", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${process.env.PYTHON || "../backend/venv/bin/python"} ../backend/scripts/verify_browser_submission.py --serve`,
      url: "http://127.0.0.1:8767/health",
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        PYTHONPATH: "..",
        PROFILE_TEST_DATABASE_URL: process.env.PROFILE_TEST_DATABASE_URL || "",
      },
    },
    {
      command: "node run.mjs start --hostname localhost --port 3101",
      url: "http://localhost:3101/login",
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        FRONTEND_ISOLATED: "1",
        FRONTEND_ORIGIN: "http://localhost:3101",
        FRONTEND_LOCAL_HTTP: "true",
        BACKEND_ORIGIN: "http://127.0.0.1:8767",
        JOB_AGENT_API_TOKEN: "fictional-browser-demo-owner-token",
        BROWSER_OWNER_APPROVAL_KEY:
          "fictional-owner-approval-separate-from-cli-token", // pragma: allowlist secret — fixture only
        FRONTEND_SESSION_SECRET: "fictional-browser-workspace-session-secret", // pragma: allowlist secret — fictional test configuration
        FRONTEND_PASSWORD_HASH: `${salt}:${scryptSync(password, salt, 64).toString("hex")}`,
      },
    },
  ],
});
