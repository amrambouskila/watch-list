import type { WatchEventKind } from "./EntryProgress";

export type WatchSubjectKind = "episode" | "title" | "curated_entry";

export interface WatchEventCreate {
  subject_kind: WatchSubjectKind;
  subject_id: string;
  kind: WatchEventKind;
  category_id?: string | null;
  occurred_at?: string | null;
  position_seconds?: number | null;
  runtime_seconds?: number | null;
  device?: string | null;
  note?: string | null;
}
