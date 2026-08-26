import type { RowChange } from "./RowChange";

export interface ProposalEdit {
  kind: "edit";
  category_id: string;
  /** The workbook mtime the row numbers were resolved against; the approve write is guarded on it. */
  read_mtime: number;
  changes: RowChange[];
}
