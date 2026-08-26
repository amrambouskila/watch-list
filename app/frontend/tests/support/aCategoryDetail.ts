import type { CategoryDetail } from "../../src/types/CategoryDetail";
import type { ColumnSpec } from "../../src/types/ColumnSpec";
import type { ReferenceSheet } from "../../src/types/ReferenceSheet";
import type { WatchCounts } from "../../src/types/WatchCounts";
import type { WatchRow } from "../../src/types/WatchRow";
import { WATCH_CYCLE } from "../../src/types/WatchStatus";

/** Nothing here names a workbook of the owner's: a category under test is described, not borrowed. */
interface CategoryDraft {
  readonly id?: string;
  readonly name?: string;
  readonly mtime?: number;
  readonly columns?: ColumnSpec[];
  readonly rows?: WatchRow[];
  readonly counts?: WatchCounts;
  readonly lockedByExcel?: boolean;
  readonly heroUrl?: string | null;
  readonly referenceSheets?: ReferenceSheet[];
}

const DEFAULT_COLUMNS: readonly ColumnSpec[] = [
  { key: "no", label: "No.", index: 0, kind: "text", role: "order", choices: [], width: null },
  { key: "title", label: "Title", index: 1, kind: "text", role: "title", choices: [], width: null },
  { key: "watched", label: "Watched", index: 2, kind: "choice", role: "watch", choices: [...WATCH_CYCLE], width: null },
];

function countsFor(rows: readonly WatchRow[]): WatchCounts {
  return {
    total: rows.length,
    watched: 0,
    in_progress: 0,
    skipped: 0,
    unwatched: rows.length,
    trackable: rows.length,
  };
}

export function aCategoryDetail(draft: CategoryDraft = {}): CategoryDetail {
  const id = draft.id ?? "a-category";
  const rows = draft.rows ?? [];
  return {
    id,
    name: draft.name ?? "A Category",
    file_name: `${id}.xlsx`,
    sheet_title: "Sheet1",
    accent: "#1F2937",
    mtime: draft.mtime ?? 1,
    has_watch_column: true,
    locked_by_excel: draft.lockedByExcel ?? false,
    hero_url: draft.heroUrl ?? null,
    counts: draft.counts ?? countsFor(rows),
    columns: draft.columns ?? [...DEFAULT_COLUMNS],
    rows,
    reference_sheets: draft.referenceSheets ?? [],
  };
}
