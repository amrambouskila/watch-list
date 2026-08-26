import type { WatchFilter } from "../types/WatchFilter";
import { IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED } from "../types/WatchStatus";

const STATUS_BY_FILTER: Readonly<Record<Exclude<WatchFilter, "all">, string>> = {
  unwatched: UNWATCHED,
  "in-progress": IN_PROGRESS,
  watched: WATCHED,
  skipped: SKIPPED,
};

export function matchesFilter(status: string, filter: WatchFilter): boolean {
  return filter === "all" || STATUS_BY_FILTER[filter] === status;
}
