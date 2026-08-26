export const WATCH_FILTERS = ["all", "unwatched", "in-progress", "watched", "skipped"] as const;

export type WatchFilter = (typeof WATCH_FILTERS)[number];

export const WATCH_FILTER_LABELS: Readonly<Record<WatchFilter, string>> = {
  all: "All",
  unwatched: "Not started",
  "in-progress": "Watching",
  watched: "Watched",
  skipped: "Skipped",
};
