import type { CategoryDetail } from "../types/CategoryDetail";
import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import type { WatchRow } from "../types/WatchRow";

/** A stale projection must never attach playback to the row that moved into its old sheet position. */
export function entryForRow(
  entries: readonly CuratedEntryRead[], detail: CategoryDetail, row: WatchRow,
): CuratedEntryRead | null {
  const candidates = entries.filter((entry) => entry.category_slug === detail.id && entry.sheet_row === row.row);
  const entry = candidates[0];
  if (candidates.length !== 1 || entry === undefined) return null;
  const matches = detail.columns.every((column) =>
    column.role === "watch" || (entry.cells[column.key] ?? "") === (row.cells[column.key] ?? ""),
  );
  return matches ? entry : null;
}
