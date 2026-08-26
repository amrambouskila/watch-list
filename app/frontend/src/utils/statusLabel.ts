import { IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED } from "../types/WatchStatus";

const LABELS: Readonly<Record<string, string>> = {
  [UNWATCHED]: "Not started",
  [WATCHED]: "Watched",
  [IN_PROGRESS]: "Watching",
  [SKIPPED]: "Skipped",
};

/** How a watch value reads in the interface, as opposed to how the sheet stores it. */
export function statusLabel(status: string): string {
  return LABELS[status] ?? status;
}
