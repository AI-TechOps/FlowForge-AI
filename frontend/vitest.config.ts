/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Component tests only (D21 decision 4). The MVP journey is asserted by
 * Playwright against the real stack — asserting it here, against a mocked
 * `fetch`, would prove the mock. What belongs here is what a browser is
 * overkill for: role gating, error and empty rendering, and the pure functions
 * behind them.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
