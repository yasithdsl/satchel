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
    viewport: { width: 1560, height: 950 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
});
