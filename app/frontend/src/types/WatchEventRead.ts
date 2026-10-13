import type { EntryProgress, WatchEventKind } from "./EntryProgress";
import type { WatchSubjectKind } from "./WatchEventCreate";

export type WatchEventSource = "ui" | "excel_mirror" | "player";

export interface WatchEventRead {
  id: string;
  occurred_at: string;
  recorded_at: string;
  subject_kind: WatchSubjectKind;
  kind: WatchEventKind;
  source: WatchEventSource;
  tmdb_key: string | null;
  curated_entry_id: string | null;
  category_id: string | null;
  position_seconds: number | null;
  runtime_seconds: number | null;
  progress: EntryProgress | null;
}
