import type { CuratedEntryRead, ResolutionState, UnitKind } from "../../src/types/CuratedEntryRead";
import type { EntryProgress } from "../../src/types/EntryProgress";
import type { TitleRead } from "../../src/types/TitleRead";

/** Nothing here names a workbook of the owner's: a row under test is described, not borrowed. */
interface EntryDraft {
  readonly id?: string;
  readonly categorySlug?: string;
  readonly position?: number;
  readonly unitKind?: UnitKind;
  readonly state?: ResolutionState;
  readonly confidence?: number | null;
  readonly note?: string;
  readonly rawTitle?: string;
  readonly rawUnit?: string;
  readonly rawRelease?: string;
  readonly cells?: Record<string, string>;
  readonly title?: TitleRead | null;
}

const NOTHING_WATCHED: EntryProgress = {
  kind: "unset",
  episode_total: 0,
  episode_completed: 0,
  episode_skipped: 0,
  episode_started: 0,
  as_of: null,
};

export function aCuratedEntryRead(draft: EntryDraft = {}): CuratedEntryRead {
  const rawTitle = draft.rawTitle ?? "A Row Nothing Answered For";
  return {
    id: draft.id ?? "00000000-0000-4000-8000-000000000001",
    category_slug: draft.categorySlug ?? "a-watch-order",
    position: draft.position ?? 1,
    sheet_row: (draft.position ?? 1) + 1,
    unit_kind: draft.unitKind ?? "unknown",
    order_type: null,
    order_label: "",
    span_start: null,
    span_end: null,
    resolution_state: draft.state ?? "unresolved",
    resolution_confidence: draft.confidence ?? null,
    resolution_note: draft.note ?? "",
    raw_title: rawTitle,
    raw_unit: draft.rawUnit ?? "",
    raw_release: draft.rawRelease ?? "",
    cells: draft.cells ?? { title: rawTitle },
    title: draft.title ?? null,
    progress: NOTHING_WATCHED,
    availability: "not_in_library",
    jellyfin_item_id: null,
  };
}
