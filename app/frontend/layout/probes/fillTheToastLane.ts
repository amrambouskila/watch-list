import { notify } from "../../src/stores/uiSlice";
import type { TestStore } from "../../tests/support/aTestStore";
import { untilPresent } from "./untilPresent";

const LANE = ".toasts";
const A_TOAST = ".toast";
const POLL_INTERVAL_MS = 16;
/** A stop, so a lane that somehow never fills cannot spin here forever. */
const MOST_TOASTS = 16;

async function untilRendered(count: number): Promise<HTMLElement> {
  const lane = await untilPresent<HTMLElement>(LANE);
  while (lane.querySelectorAll(A_TOAST).length < count) {
    await new Promise<void>((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
  return lane;
}

/**
 * Fill the toasts' row up to the cap it is allowed to take, and hold it full.
 *
 * The row is laid out above the app rather than over it, so the app has to work at the least height
 * the toasts can ever leave it, and that is where the dock's action row is squeezed hardest. Raising
 * toasts until the lane scrolls finds that point by measuring it, so the surface cannot quietly stop
 * exercising the squeeze the way a message tuned to one font's metrics would.
 */
export async function fillTheToastLane(store: TestStore, message: string): Promise<void> {
  let wanted = 0;
  let raising = false;
  const top = (): void => {
    if (raising) return;
    raising = true;
    while (store.getState().ui.toasts.length < wanted) store.dispatch(notify({ message, tone: "error" }));
    raising = false;
  };
  store.subscribe(top);

  for (wanted = 1; wanted <= MOST_TOASTS; wanted += 1) {
    top();
    const lane = await untilRendered(wanted);
    if (lane.scrollHeight > lane.clientHeight) return;
  }
  throw new Error(`${MOST_TOASTS} toasts did not fill the toast lane.`);
}
