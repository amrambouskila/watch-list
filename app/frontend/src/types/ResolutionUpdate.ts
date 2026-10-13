import type { UnitKind } from "./CuratedEntryRead";
import type { MediaType } from "./TitleRead";

export type ReviewAction = "confirm" | "correct" | "reject";

/**
 * The body of `POST /api/review/entries/{entry_id}`: one human decision about one curated row.
 *
 * `confirm` and `reject` carry nothing but the action and an optional note; `correct` requires
 * `media_type` and `tmdb_id` and takes the span fields optionally. The backend refuses any other
 * combination, so a form that can build one of those is a form that can build a 422.
 */
export interface ResolutionUpdate {
  action: ReviewAction;
  media_type?: MediaType | null;
  tmdb_id?: number | null;
  unit_kind?: UnitKind | null;
  /** An open string: TheTVDB's season types are read at runtime and are never a closed set here. */
  order_type?: string | null;
  span_start?: number | null;
  span_end?: number | null;
  season_number?: number | null;
  note?: string;
}
