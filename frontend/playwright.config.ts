import { defineConfig, devices } from "@playwright/test";

const PORT = 5180;
const BACKEND_PORT = 8010;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["html", { outputFolder: "playwright-report" }], ["list"]],
  use: {
    baseURL: `http://localhost:8082`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // webServer: [
  //   {
  //     command: `cd ../backend && poetry run uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}`,
  //     url: `http://localhost:${BACKEND_PORT}/api/health`,
  //     reuseExistingServer: true,
  //     timeout: 30_000,
  //   },
  //   {
  //     command: "npm run dev",
  //     url: `http://localhost:${PORT}`,
  //     reuseExistingServer: true,
  //     timeout: 30_000,
  //   },
  // ],
});
