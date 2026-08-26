import type { Proposal } from "../../src/types/Proposal";
import type { RowChange } from "../../src/types/RowChange";
import { anEditBody } from "../../tests/support/aProposalBody";
import { aProposal } from "../../tests/support/aProposal";
import { aRowChange } from "../../tests/support/aRowChange";
import { FIRST_DATA_ROW, NOTES_KEY, ROW_COUNT, TITLE_KEY, YEAR_KEY } from "./aProbeCategory";

const LINE_COUNT = 200;
const REVISED_ROW = FIRST_DATA_ROW;
const MOVED_ROW = FIRST_DATA_ROW + 1;
const REMOVED_ROW = FIRST_DATA_ROW + 2;
const MOVE_ANCHOR = FIRST_DATA_ROW + 8;
const LAST_ROW = FIRST_DATA_ROW + ROW_COUNT - 1;
const A_LONG_REASON =
  "The festival cut and the theatrical cut were listed as one entry, and the commentary track " +
  "belongs to only one of them.";
const A_SOURCE = "https://example.invalid/watch-orders/the-long-way-round/chronology";
/**
 * The other shape a cited source really takes: an API call four times as wide as the chip holding it.
 *
 * The chips are ellipsised on purpose, and a source this long is the only kind that says so loudly
 * enough for the guard's size floor to have to know the difference.
 */
const A_LONG_SOURCE =
  "https://example.invalid/w/api.php?action=query&prop=imageinfo&iiprop=url|extmetadata|mime|size" +
  "&generator=search&gsrnamespace=6&gsrlimit=40&gsrsearch=the%20long%20way%20round%20wordmark" +
  "&format=json&formatversion=2&origin=*&uselang=en&maxlag=5";

/** The three changes that name a row the sheet already holds, in the order the diff shows them. */
function againstStandingRows(): RowChange[] {
  return [
    aRowChange({ kind: "revise", row: REVISED_ROW, cells: { [NOTES_KEY]: "" }, reason: A_LONG_REASON }),
    aRowChange({ kind: "move", row: MOVED_ROW, after_row: MOVE_ANCHOR, reason: "It airs after the festival cut." }),
    aRowChange({ kind: "remove", row: REMOVED_ROW, reason: "A duplicate of the entry above it." }),
  ];
}

function anAddedRow(index: number): RowChange {
  return aRowChange({
    kind: "add",
    after_row: LAST_ROW,
    cells: {
      [TITLE_KEY]: `The Long Way Round, Part ${index}: The Crossing At Dawn`,
      [YEAR_KEY]: String(1960 + index),
      [NOTES_KEY]: `Listed ${index} in the published order, between the two festival cuts.`,
    },
    reason: A_LONG_REASON,
  });
}

/**
 * A diff long enough and wide enough that it has to scroll in both directions inside itself.
 *
 * Its first line blanks a cell the sheet holds a long note in, which is the shape that once
 * rendered as a line changing nothing.
 */
export function aLongEditProposal(): Proposal {
  const standing = againstStandingRows();
  const added = Array.from({ length: LINE_COUNT - standing.length }, (_, index) => anAddedRow(index + 1));
  return aProposal(anEditBody([...standing, ...added]), {
    summary: `Reorders the published run and adds the ${LINE_COUNT - standing.length} entries missing from it.`,
    sources: [A_SOURCE, `${A_SOURCE}/part-two`, `${A_SOURCE}/appendix`, A_LONG_SOURCE],
  });
}
