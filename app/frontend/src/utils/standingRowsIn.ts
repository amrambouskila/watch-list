import type { CategoryDetail } from "../types/CategoryDetail";
import type { StandingRows } from "../types/StandingRows";

/** The cell that identifies a row to a reader: its title, or the first column that is not bookkeeping. */
function identifyingKey(detail: CategoryDetail): string | null {
  const title = detail.columns.find((column) => column.role === "title");
  const other = detail.columns.find((column) => column.role === "other");
  return (title ?? other)?.key ?? null;
}

/** What each row of a category holds right now, keyed by the row number a proposal would name. */
export function standingRowsIn(detail: CategoryDetail): StandingRows {
  const cellsByRow: Record<number, Record<string, string>> = {};
  for (const row of detail.rows) cellsByRow[row.row] = row.cells;
  return { status: "ready", identifyingKey: identifyingKey(detail), cellsByRow };
}
