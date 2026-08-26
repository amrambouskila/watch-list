import type { CategoryDetail } from "../../src/types/CategoryDetail";
import type { ColumnSpec } from "../../src/types/ColumnSpec";
import type { ReferenceSheet } from "../../src/types/ReferenceSheet";
import type { WatchRow } from "../../src/types/WatchRow";
import { WATCH_CYCLE } from "../../src/types/WatchStatus";
import { aCategoryDetail } from "../../tests/support/aCategoryDetail";

export const FIRST_DATA_ROW = 2;
export const ROW_COUNT = 60;
export const NOTES_KEY = "notes";
export const YEAR_KEY = "year";
export const TITLE_KEY = "title";

/**
 * The note the revise in the long diff blanks.
 *
 * Long on purpose: the cell that shows it ellipsises, and the outcome of the revise has to survive
 * that. It once did not, and the diff read as a line that changed nothing.
 */
export const A_STANDING_NOTE =
  "Carried over from the earlier order, where this sat between the two festival cuts and nobody " +
  "could remember which of them the commentary belonged to.";

const COLUMNS: readonly ColumnSpec[] = [
  { key: "no", label: "No.", index: 0, kind: "text", role: "order", choices: [], width: null },
  { key: TITLE_KEY, label: "Title", index: 1, kind: "text", role: "title", choices: [], width: null },
  { key: "watched", label: "Watched?", index: 2, kind: "choice", role: "watch", choices: [...WATCH_CYCLE], width: null },
  { key: YEAR_KEY, label: "Year", index: 3, kind: "text", role: "other", choices: [], width: null },
  { key: NOTES_KEY, label: "Notes", index: 4, kind: "text", role: "other", choices: [], width: null },
];

function aStandingRow(offset: number): WatchRow {
  const row = FIRST_DATA_ROW + offset;
  return {
    row,
    cells: {
      no: String(offset + 1),
      [TITLE_KEY]: `The Long Way Round, Part ${offset + 1}`,
      watched: "",
      [YEAR_KEY]: String(1960 + offset),
      [NOTES_KEY]: offset === 0 ? A_STANDING_NOTE : "",
    },
  };
}

/**
 * The supporting sheet the drawer shows: long cells and a link, which is what has to stay readable
 * in a panel narrow enough to overlay the app rather than replace it.
 */
const REFERENCE_SHEETS: readonly ReferenceSheet[] = [
  {
    title: "Sources",
    header: ["Part", "Where the order came from", "Link"],
    rows: [
      ["Part 1", "The published chronology, second edition", "https://example.invalid/watch-orders/the-long-way-round"],
      ["Part 2", "Broadcast order, as aired", "https://example.invalid/watch-orders/the-long-way-round/part-two"],
      ["Appendix", "The two festival cuts and where they sit", "https://example.invalid/watch-orders/appendix"],
    ],
  },
];

/** The sheet every probe surface reads: wide enough that its diff has to scroll both ways. */
export function aProbeCategory(): CategoryDetail {
  return aCategoryDetail({
    name: "A Long Watch Order",
    columns: [...COLUMNS],
    rows: Array.from({ length: ROW_COUNT }, (_, offset) => aStandingRow(offset)),
    referenceSheets: REFERENCE_SHEETS.map((sheet) => ({ ...sheet })),
  });
}
