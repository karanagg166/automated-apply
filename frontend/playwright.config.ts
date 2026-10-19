import { defineConfig, devices } from "@playwright/test";
import { scryptSync } from "node:crypto";
const salt = "0123456789abcdef0123456789abcdef"; // pragma: allowlist secret — fixed test salt
const password = "fictional-ui-owner-passphrase"; // pragma: allowlist secret — isolated fixture only
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${process.env.PYTHON || "python3"} ../backend/scripts/phase7_ui_fixture.py`,
      cwd: process.cwd(),
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: false,
      env: { PHASE7_ISOLATED_UI: "true", PYTHONPATH: ".." },
      timeout: 60000,
    },
    {
      command: "node run.mjs start --hostname localhost --port 3100",
      url: "http://localhost:3100/login",
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        FRONTEND_ISOLATED: "1",
        FRONTEND_ORIGIN: "http://localhost:3100",
        FRONTEND_LOCAL_HTTP: "true",
        BACKEND_ORIGIN: "http://127.0.0.1:8765",
        JOB_AGENT_API_TOKEN: "fictional-phase7-backend-token-never-client",
        FRONTEND_SESSION_SECRET:
          "fictional-session-secret-only-for-phase7-ui-tests",
        FRONTEND_PASSWORD_HASH: `${salt}:${scryptSync(password, salt, 64).toString("hex")}`,
      },
    },
  ],
});
