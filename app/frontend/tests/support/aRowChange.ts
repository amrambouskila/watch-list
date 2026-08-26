import type { RowChange } from "../../src/types/RowChange";

/** A change with only the fields a case is about; the stream omits the rest rather than nulling them. */
export function aRowChange(draft: Partial<RowChange> & Pick<RowChange, "kind">): RowChange {
  return { cells: {}, reason: "", ...draft };
}
