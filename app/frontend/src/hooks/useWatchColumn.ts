import { useMemo } from "react";

import type { CategoryDetail } from "../types/CategoryDetail";
import type { ColumnSpec } from "../types/ColumnSpec";

export function useWatchColumn(detail: CategoryDetail | null): ColumnSpec | null {
  return useMemo(() => detail?.columns.find((column) => column.role === "watch") ?? null, [detail]);
}
