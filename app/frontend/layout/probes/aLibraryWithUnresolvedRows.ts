import type { CuratedEntryRead } from "../../src/types/CuratedEntryRead";
import { aCuratedEntryRead } from "../../tests/support/aCuratedEntryRead";
import { aProbeLibrary, type ProbeLibrary } from "./aProbeLibrary";

/**
 * A resolver note of the length the real ones reach, which is what the row has to hold without
 * pushing its own Confirm and Retry off the screen.
 */
const A_LONG_NOTE =
  'this row\'s title sits inside TMDB\'s "One Piece Film: Dead End Adventure" (2003), found by searching ' +
  'the franchise form "One Piece: Dead End Adventure", and three further hits score within a tenth of it';
const A_SHORT_NOTE = "TMDB answered with nothing that matches this row";
/** Below the confirmed mark and above nothing at all: the number a reviewer is asked to judge. */
const A_MIDDLING_CONFIDENCE = 0.65;

/** One row a heuristic guessed at, and one it could not touch - the two states the queue holds. */
function aQueue(): readonly CuratedEntryRead[] {
  return [
    aCuratedEntryRead({
      id: "00000000-0000-4000-8000-0000000000f1",
      position: 4,
      categorySlug: "misc-movies",
      // Only Order and Title: every one of Misc_Movies' rows really is that sparse, and a row with
      // almost nothing in it is the one whose controls have the least above them holding them down.
      cells: { no: "4", title: "The Consultant" },
      rawTitle: "The Consultant",
      note: A_SHORT_NOTE,
    }),
    aCuratedEntryRead({
      id: "00000000-0000-4000-8000-0000000000f2",
      position: 9,
      categorySlug: "one-piece",
      state: "auto",
      confidence: A_MIDDLING_CONFIDENCE,
      cells: {
        no: "9",
        title: "Dead End Adventure",
        watched: "",
        year: "2003",
        notes: "Sits between the two festival cuts; nobody could remember which the commentary belongs to.",
      },
      rawTitle: "Dead End Adventure",
      rawUnit: "Season 1",
      rawRelease: "2003",
      note: A_LONG_NOTE,
    }),
    aCuratedEntryRead({
      id: "00000000-0000-4000-8000-0000000000f3",
      position: 22,
      categorySlug: "a-long-watch-order",
      state: "auto",
      confidence: 0.8,
      cells: { no: "22", title: "The Long Way Round, Part 3", year: "1962" },
      rawTitle: "The Long Way Round, Part 3",
      note: A_SHORT_NOTE,
    }),
  ];
}

/** The ordinary library, plus the review queue the unresolved view reads across all of it. */
export function aLibraryWithUnresolvedRows(): ProbeLibrary {
  return { ...aProbeLibrary(), queue: aQueue() };
}
