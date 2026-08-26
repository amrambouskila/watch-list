import type { RowChange } from "../types/RowChange";
import type { StandingRows } from "../types/StandingRows";
import { identifyRow } from "./identifyRow";

const MISSING_ROW = "—";
// A move seats its row directly after the one it names, so naming the sheet's header means the top.
const HEADER_ROW = 1;
const TO_THE_TOP = "to the top";
const MOVES_TO = " → ";
const NAMES = " · ";

function rowLabel(row: number | null): string {
  return row === null ? MISSING_ROW : String(row);
}

/**
 * Where a move would seat its row, with the anchor named rather than left as a bare number.
 *
 * A destination is only meaningful as the row it sits behind, and that row is identified the same
 * way the "Now" column identifies the row being moved.
 */
function seatedAfter(standing: StandingRows, after: number): string {
  if (after === HEADER_ROW) return TO_THE_TOP;
  const named = identifyRow(standing, after);
  return named === "" ? `after ${after}` : `after ${after}${NAMES}${named}`;
}

/** Where a change lands: an ordinal for a new sheet, a named row reference for an edit. */
export function anchorOf(change: RowChange, standing: StandingRows): string {
  const target = change.row ?? null;
  const after = change.after_row ?? null;
  if (change.kind === "add") return after === null ? "at the end" : `after ${after}`;
  if (change.kind === "move") {
    return `${rowLabel(target)}${MOVES_TO}${after === null ? MISSING_ROW : seatedAfter(standing, after)}`;
  }
  return rowLabel(target);
}
