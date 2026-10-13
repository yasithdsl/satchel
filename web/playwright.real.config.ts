import { defineConfig } from "@playwright/test";

const BASE = process.env.SATCHEL_REAL_URL ?? "http://localhost:3100";
/** e.g. SATCHEL_REAL_VIEWPORT=1512x845 to walk the demo on a laptop-sized window. */
const [width, height] = (process.env.SATCHEL_REAL_VIEWPORT ?? "1920x1080").split("x").map(Number);

export default defineConfig({
  testDir: "./e2e-real",
  timeout: 600_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: BASE,
    browserName: "chromium",
    viewport: { width, height },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
});
