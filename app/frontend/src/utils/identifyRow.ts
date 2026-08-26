import type { StandingRows } from "../types/StandingRows";

const READING_SHEET = "reading the sheet…";
const UNREADABLE_SHEET = "could not read the sheet";
const VANISHED_ROW = "no such row now";

/** What identifies one row of the sheet to a reader today, or a plain word about why that is not known. */
export function identifyRow(standing: StandingRows, row: number): string {
  if (standing.status === "loading") return READING_SHEET;
  if (standing.status === "failed") return UNREADABLE_SHEET;
  const cells = standing.cellsByRow[row];
  if (cells === undefined) return VANISHED_ROW;
  return standing.identifyingKey === null ? "" : (cells[standing.identifyingKey] ?? "");
}
