import { WATCH_CYCLE } from "../types/WatchStatus";

/** Advance one step through the sheet's own dropdown order, wrapping at the end. */
export function nextWatchStatus(current: string, choices: readonly string[]): string {
  const cycle = choices.length > 0 ? choices : WATCH_CYCLE;
  const position = cycle.indexOf(current);
  return cycle[(position + 1) % cycle.length] ?? cycle[0] ?? "";
}
