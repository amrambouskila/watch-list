import { useMemo } from "react";

import type { ColumnSpec } from "../types/ColumnSpec";

const INLINE_COLUMN_LIMIT = 4;

export interface RowColumns {
  readonly order: ColumnSpec | null;
  readonly title: ColumnSpec | null;
  /** The few extra columns dense enough to show on the row itself. */
  readonly inline: readonly ColumnSpec[];
}

/** Pick what a collapsed row shows; everything else lives in the expanded panel. */
export function useRowColumns(columns: readonly ColumnSpec[]): RowColumns {
  return useMemo(() => {
    const order = columns.find((column) => column.role === "order") ?? null;
    const title = columns.find((column) => column.role === "title") ?? null;
    const inline = columns
      .filter((column) => column.role === "other")
      .filter((column) => (column.width ?? 0) < 40)
      .slice(0, INLINE_COLUMN_LIMIT);
    return { order, title, inline };
  }, [columns]);
}
