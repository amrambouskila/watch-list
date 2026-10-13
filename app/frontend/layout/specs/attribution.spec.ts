import { expect, test } from "@playwright/test";

import { openProbe } from "../support/openProbe";

const SURFACE = "home";
const MARK = ".attribution__logo";
const WORDMARK = ".sidebar__wordmark";
/** What the stylesheet asks of the mark, asserted to the pixel because the terms are about pixels. */
const MARK_HEIGHT_PX = 12;
/** A rendered box lands on subpixels, so a hundredth of the ratio is rounding rather than a stretch. */
const ASPECT_TOLERANCE = 0.01;

/**
 * TMDB's terms are met in pixels rather than in markup: the mark has to be their own file, unmodified
 * in colour and aspect, and less prominent than this app's own.
 *
 * None of that is visible to jsdom, and none of it is visible to the controls guard either — a 404
 * still has the right `src` and collapses to a box that answers a click, a stretched mark passes
 * every DOM assertion there is, and a filter recolours nothing the DOM can be asked about. So it is
 * measured here, in the real browser, at every window the guard runs.
 */
test("the TMDB mark is their own file, unmodified, and smaller than this app's own", async ({ page }) => {
  await openProbe(page, SURFACE);
  // `openProbe` settles fonts and animations, not images. `complete` turns true whichever way the
  // fetch ended, so waiting on it holds for a decode without ever hiding one that never arrived:
  // that is what `naturalWidth` below is for.
  await expect
    .poll(() => page.locator(MARK).evaluate((node) => (node as HTMLImageElement).complete))
    .toBe(true);

  const mark = await page.evaluate(
    ({ markSelector, wordmarkSelector, tolerance }) => {
      const logo = document.querySelector(markSelector);
      if (!(logo instanceof HTMLImageElement)) throw new Error(`The sidebar foot rendered no ${markSelector}.`);
      const wordmark = document.querySelector(wordmarkSelector);
      if (wordmark === null) throw new Error(`There is no ${wordmarkSelector} for the mark to be less than.`);

      const box = logo.getBoundingClientRect();
      const style = getComputedStyle(logo);
      const intrinsic = logo.naturalWidth / logo.naturalHeight;

      return {
        // A file that never arrived reports complete with no intrinsic size of its own.
        loaded: logo.complete && logo.naturalWidth > 0,
        height: box.height,
        keepsItsAspect: Math.abs(box.width / box.height - intrinsic) < tolerance,
        unrecoloured: style.filter === "none" && style.mixBlendMode === "normal" && style.opacity === "1",
        lessProminent: box.height < parseFloat(getComputedStyle(wordmark).fontSize),
      };
    },
    { markSelector: MARK, wordmarkSelector: WORDMARK, tolerance: ASPECT_TOLERANCE },
  );

  expect(mark).toEqual({
    loaded: true,
    height: MARK_HEIGHT_PX,
    keepsItsAspect: true,
    unrecoloured: true,
    lessProminent: true,
  });
});
