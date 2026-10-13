import type { EntryProgress } from "./EntryProgress";
import type { TitleRead } from "./TitleRead";

export type UnitKind = "movie" | "episodes" | "season" | "series" | "special" | "unknown";
export type ResolutionState = "unresolved" | "auto" | "confirmed" | "rejected";

export interface CuratedEntryRead {
  id: string;
  /** The workbook this row belongs to, by the id its filename derives — the queue spans all of them. */
  category_slug: string;
  position: number;
  sheet_row: number | null;
  unit_kind: UnitKind;
  order_type: string | null;
  order_label: string;
  span_start: number | null;
  span_end: number | null;
  resolution_state: ResolutionState;
  resolution_confidence: number | null;
  /** The resolver's sentence, the queue's clause and a reviewer's - why the row sits where it does. */
  resolution_note: string;
  raw_title: string;
  raw_unit: string;
  raw_release: string;
  cells: Record<string, string>;
  title: TitleRead | null;
  progress: EntryProgress;
  availability: Availability;
  jellyfin_item_id: string | null;
}
import type { Availability } from "./Availability";
