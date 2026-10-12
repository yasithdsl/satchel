import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.SATCHEL_E2E_PORT ?? 3200);
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: BASE, browserName: "chromium" },
  webServer: {
    command: `pnpm exec next start -p ${PORT}`,
    url: BASE,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
