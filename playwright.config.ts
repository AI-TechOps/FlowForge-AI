/**
 * Playwright configuration for the Phase 6 gates (spec 07, task 15).
 *
 * The specs themselves are Codex's (task 4) and live in `tests/phase6/`,
 * alongside every other phase's gate suite rather than inside the frontend
 * package — the pattern the CI wiring and the D6 lane both already assume.
 *
 * There is no `webServer` block on purpose. These gates drive the **real
 * stack**: nginx serving the production build, the FastAPI backend, Postgres,
 * Redis and the arq worker, all under docker compose. Letting Playwright boot
 * a Vite dev server instead would test an artifact that never ships, which is
 * the whole thing D21 decision 7 moved away from.
 */

import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.PHASE6_BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./tests/phase6",
  // Serial by default. These gates share one backend and one tenant, and the
  // golden path mutates ticket and run state that a parallel spec would see;
  // a flaky gate teaches people to ignore gates.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  // One retry in CI absorbs genuine infrastructure noise without hiding a real
  // regression, which would need to fail twice.
  retries: process.env.CI ? 1 : 0,
  // Triage runs through a real graph and a real worker; 30s is not enough.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
