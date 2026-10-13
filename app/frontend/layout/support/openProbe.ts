import { expect, type Page } from "@playwright/test";

import { PROBE_ORIGIN } from "../probeServer";
import type { SurfaceName } from "../surfaces";

const READY_SELECTOR = 'body[data-probe="ready"]';
const READY_TIMEOUT_MS = 30_000;

/**
 * Put one surface on screen and wait until measuring it means anything.
 *
 * Fonts decide text metrics and animations move boxes, so both have to have finished. Anything
 * addressed off this origin is refused and reported: a guard run touches no network at all.
 */
export async function openProbe(page: Page, surface: SurfaceName): Promise<void> {
  const refused: string[] = [];
  // Native media requests bypass window.fetch, so intercept them at the browser boundary too.
  await page.route("**/api/playback/*/stream", (route) => route.fulfill({ status: 200, contentType: "video/mp4", body: "" }));
  await page.route(
    (url) => url.origin !== PROBE_ORIGIN,
    async (route) => {
      refused.push(route.request().url());
      await route.abort();
    },
  );

  await page.goto(`${PROBE_ORIGIN}/?surface=${surface}`);
  await page.waitForSelector(READY_SELECTOR, { timeout: READY_TIMEOUT_MS });
  await page.evaluate(async () => {
    await document.fonts.ready;
    // Settled rather than fulfilled: a cancelled transition rejects `finished` with AbortError, and
    // a cancelled transition is exactly one that has stopped moving the box this is waiting on.
    await Promise.allSettled(document.getAnimations().map((animation) => animation.finished));
  });

  expect(refused, "the probe addressed something off its own origin").toEqual([]);
}
