import type { CategorySummary } from "./CategorySummary";
import type { ColumnSpec } from "./ColumnSpec";
import type { ReferenceSheet } from "./ReferenceSheet";
import type { WatchRow } from "./WatchRow";

export interface CategoryDetail extends CategorySummary {
  columns: ColumnSpec[];
  rows: WatchRow[];
  reference_sheets: ReferenceSheet[];
}
