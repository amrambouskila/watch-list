import { useMemo } from "react";

import type { CategoryDetail } from "../types/CategoryDetail";
import type { ColumnSpec } from "../types/ColumnSpec";
import type { WatchFilter } from "../types/WatchFilter";
import type { WatchRow } from "../types/WatchRow";
import { matchesFilter } from "../utils/matchesFilter";

export function useVisibleRows(
  detail: CategoryDetail | null,
  watch: ColumnSpec | null,
  filter: WatchFilter,
  query: string,
): readonly WatchRow[] {
  return useMemo(() => {
    if (detail === null) return [];
    const needle = query.trim().toLowerCase();
    return detail.rows.filter((row) => {
      const status = watch === null ? "" : (row.cells[watch.key] ?? "");
      if (!matchesFilter(status, filter)) return false;
      if (needle === "") return true;
      return Object.values(row.cells).some((value) => value.toLowerCase().includes(needle));
    });
  }, [detail, watch, filter, query]);
}
