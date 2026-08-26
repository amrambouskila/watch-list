import { expect, test } from "@playwright/test";

import { SURFACES } from "../surfaces";
import {
  measureControls,
  MIN_CLICKABLE_FRACTION,
  MIN_VISIBLE_FRACTION,
  type ControlReach,
} from "../support/measureControls";
import { openProbe } from "../support/openProbe";

const NO_SIDEWAYS_SCROLL = { page: 0, body: 0 };
const TOASTS = ".toasts";
const A_TOAST = ".toast";
const PER_CENT = 100;

function reaches(control: ControlReach): boolean {
  const clear = control.obstructions.length === 0;
  return (
    control.onScreen &&
    clear &&
    control.visibleFraction >= MIN_VISIBLE_FRACTION &&
    control.clickableFraction >= MIN_CLICKABLE_FRACTION
  );
}

/** One line per control a person could not click, said the way the person would have found it. */
function outOfReach(controls: readonly ControlReach[]): string[] {
  return controls
    .filter((control) => !reaches(control))
    .map(
      (control) =>
        `"${control.name}" — ${Math.round(control.width)}x${Math.round(control.height)} visible, ` +
        `${control.onScreen ? "on screen" : "off screen"}, ` +
        `${Math.round(control.visibleFraction * PER_CENT)}% of the shortest axis it promised is there, ` +
        `${Math.round(control.clickableFraction * PER_CENT)}% of it answers a click` +
        (control.obstructions.length === 0 ? "" : `, ${control.obstructions.join(", ")}`),
    );
}

for (const surface of SURFACES) {
  test(`every control on the ${surface.name} surface can be clicked`, async ({ page }) => {
    await openProbe(page, surface.name);
    await expect(page.locator(surface.root)).toHaveCount(1);
    // How many is the arrangement's business -- one refusal, or one per queued write; that there
    // is one at all is this surface's promise, and a surface that lost it would pass on nothing.
    if (surface.withToast) await expect(page.locator(A_TOAST)).not.toHaveCount(0);
    else await expect(page.locator(A_TOAST)).toHaveCount(0);

    const controls = await measureControls(page, surface.root);
    const names = controls.map((control) => control.name);
    for (const expected of surface.expects) expect(names).toContain(expected);

    expect(outOfReach(controls)).toEqual([]);
    // A toast the app will not let you see or dismiss is worse than one that covers a button.
    if (surface.withToast) expect(outOfReach(await measureControls(page, TOASTS))).toEqual([]);
  });

  test(`the ${surface.name} surface never scrolls the page sideways`, async ({ page }) => {
    await openProbe(page, surface.name);

    const overflow = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
    }));

    expect(overflow).toEqual(NO_SIDEWAYS_SCROLL);
  });
}
