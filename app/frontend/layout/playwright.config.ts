import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

import { PROBE_ORIGIN } from "./probeServer";

const SERVER_START_TIMEOUT_MS = 180_000;
const FRONTEND_ROOT = fileURLToPath(new URL("..", import.meta.url));

/**
 * jsdom has no layout, so nothing in the Vitest suite can see a control render off-screen. These
 * run the real components, with the real stylesheets, in a real browser.
 *
 * The first two windows are where every off-screen-control bug this app has shipped was found by
 * hand. The last two are chosen against the stylesheets rather than against a machine: 1024x768
 * is the shortest window the dock still lays a proposal out in, and 960 is exactly the 60rem
 * breakpoint, where the shell stacks and the dock goes full width.
 */
export default defineConfig({
  testDir: "./specs",
  // Failure artefacts belong beside the other build caches, not loose in the source tree.
  outputDir: fileURLToPath(new URL("../node_modules/.playwright-layout", import.meta.url)),
  fullyParallel: true,
  // A guard that may pass on the second go, or quietly run a subset, is not a guard.
  forbidOnly: true,
  retries: 0,
  reporter: [["list"]],
  // The app honours prefers-reduced-motion, so asking for it holds every box still to be measured.
  use: { baseURL: PROBE_ORIGIN, contextOptions: { reducedMotion: "reduce" } },
  projects: [
    { name: "1512x900", use: { browserName: "chromium", viewport: { width: 1512, height: 900 } } },
    { name: "1280x720", use: { browserName: "chromium", viewport: { width: 1280, height: 720 } } },
    { name: "1024x768", use: { browserName: "chromium", viewport: { width: 1024, height: 768 } } },
    { name: "960x1040", use: { browserName: "chromium", viewport: { width: 960, height: 1040 } } },
  ],
  webServer: {
    command: "pnpm exec vite --config layout/vite.config.ts",
    cwd: FRONTEND_ROOT,
    url: PROBE_ORIGIN,
    reuseExistingServer: false,
    timeout: SERVER_START_TIMEOUT_MS,
  },
});
