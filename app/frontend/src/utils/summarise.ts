import type { WatchCounts } from "../types/WatchCounts";

const ENTRY = (count: number): string => `${count} ${count === 1 ? "entry" : "entries"}`;

/** One-line tally under a category title. */
export function summarise(counts: WatchCounts): string {
  const parts = [ENTRY(counts.total), `${counts.watched} watched`];
  if (counts.in_progress > 0) parts.push(`${counts.in_progress} watching`);
  if (counts.skipped > 0) parts.push(`${counts.skipped} skipped`);
  return parts.join(" · ");
}
