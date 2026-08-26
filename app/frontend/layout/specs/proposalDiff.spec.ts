import { expect, test } from "@playwright/test";

import { openProbe } from "../support/openProbe";

const SURFACE = "edit-proposal";
const DIFF = ".diff";
const REPLACED = ".diff__replaced";
/** A cell's own scroll width lands on subpixels; a pixel over is rounding, not lost text. */
const CLIP_TOLERANCE_PX = 1;

test("a 200-row diff scrolls inside its own container", async ({ page }) => {
  await openProbe(page, SURFACE);

  const scrolling = await page.evaluate((selector) => {
    const diff = document.querySelector(selector);
    if (diff === null) throw new Error(`The proposal rendered no ${selector}.`);
    const before = diff.getBoundingClientRect();
    diff.scrollTop = diff.scrollHeight;
    diff.scrollLeft = diff.scrollWidth;
    const after = diff.getBoundingClientRect();
    return {
      hasMoreThanFits: diff.scrollHeight > diff.clientHeight,
      widerThanFits: diff.scrollWidth > diff.clientWidth,
      scrolledDown: diff.scrollTop > 0,
      scrolledAcross: diff.scrollLeft > 0,
      pageStayedPut: window.scrollY === 0 && window.scrollX === 0,
      stayedInPlace: after.top === before.top && after.left === before.left && after.height === before.height,
      onScreen: after.top >= 0 && after.bottom <= window.innerHeight && after.right <= window.innerWidth,
    };
  }, DIFF);

  expect(scrolling).toEqual({
    hasMoreThanFits: true,
    widerThanFits: true,
    scrolledDown: true,
    scrolledAcross: true,
    pageStayedPut: true,
    stayedInPlace: true,
    onScreen: true,
  });
});

test("a revise shows the value it writes, not only the value it replaces", async ({ page }) => {
  await openProbe(page, SURFACE);

  const cells = await page.evaluate(
    ({ replaced, tolerance }) => {
      const showing = [...document.querySelectorAll("td")].filter((cell) => cell.querySelector(replaced) !== null);
      return {
        count: showing.length,
        clipped: showing
          .filter((cell) => cell.scrollWidth - cell.clientWidth > tolerance)
          .map((cell) => (cell.textContent ?? "").replace(/\s+/g, " ").trim()),
      };
    },
    { replaced: REPLACED, tolerance: CLIP_TOLERANCE_PX },
  );

  expect(cells.count).toBeGreaterThan(0);
  expect(cells.clipped).toEqual([]);
});
