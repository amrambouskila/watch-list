import { notify } from "../../src/stores/uiSlice";
import type { TestStore } from "../../tests/support/aTestStore";

/**
 * Keep exactly one toast up for as long as the surface is being measured.
 *
 * The app clears a toast a few seconds after it appears, which is right for a person and far too
 * short for a guard that has to hold a screen still. Raising a fresh one the instant the last is
 * gone leaves one on screen at every moment, with no timer of the probe's own to race.
 */
export function holdAToastOnScreen(store: TestStore, message: string): void {
  const raiseIfNone = (): void => {
    if (store.getState().ui.toasts.length === 0) store.dispatch(notify({ message, tone: "error" }));
  };
  store.subscribe(raiseIfNone);
  raiseIfNone();
}
