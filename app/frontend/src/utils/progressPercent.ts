import type { WatchCounts } from "../types/WatchCounts";

/** Share of the non-skipped entries that are finished, 0–100. */
export function progressPercent(counts: WatchCounts): number {
  if (counts.trackable === 0) return 0;
  return Math.round((counts.watched / counts.trackable) * 100);
}
