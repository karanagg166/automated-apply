import { defineConfig } from "@playwright/test";
import isolated from "./playwright.extension.config";

// Production frontend with fictional API responses only; no owner configuration.
export default defineConfig({
  ...isolated,
  testMatch: "phase53-naukri.spec.ts",
});
