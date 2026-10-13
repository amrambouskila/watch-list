export type WatchEventKind = "started" | "progressed" | "completed" | "skipped" | "unset";

export interface EntryProgress {
  kind: WatchEventKind;
  episode_total: number;
  episode_completed: number;
  episode_skipped: number;
  episode_started: number;
  as_of: string | null;
}
