export const UNWATCHED = "";
export const WATCHED = "Watched";
export const IN_PROGRESS = "In progress";
export const SKIPPED = "Skip";

export const WATCH_CYCLE: readonly string[] = [UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED];

export type WatchStatus = (typeof WATCH_CYCLE)[number];
