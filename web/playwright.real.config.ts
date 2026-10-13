import { defineConfig } from "@playwright/test";

const BASE = process.env.SATCHEL_REAL_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e-real",
  timeout: 600_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: BASE,
    browserName: "chromium",
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
});
