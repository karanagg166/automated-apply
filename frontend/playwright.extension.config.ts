import { scryptSync } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";

const salt = "0123456789abcdef0123456789abcdef";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "extension-assistant.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3152",
    ...devices["Desktop Chrome"],
    screenshot: "only-on-failure",
  },
  // All backend responses are fictional route fixtures. No backend or profile
  // database is started, and this process reads no private environment file.
  webServer: {
    command: "pnpm exec next start --hostname localhost --port 3152",
    url: "http://localhost:3152/login",
    reuseExistingServer: false,
    env: {
      FRONTEND_ISOLATED: "1",
      FRONTEND_ORIGIN: "http://localhost:3152",
      FRONTEND_LOCAL_HTTP: "true",
      BACKEND_ORIGIN: "http://127.0.0.1:9",
      FRONTEND_SESSION_SECRET:
        "fictional-phase52-session-secret-for-isolated-ui",
      FRONTEND_PASSWORD_HASH: `${salt}:${scryptSync("fictional-ui-owner-passphrase", salt, 64).toString("hex")}`,
    },
  },
});
