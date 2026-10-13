import type { CatalogListing } from "../../src/types/CatalogListing";
import type { CategoryDetail } from "../../src/types/CategoryDetail";
import type { CuratedEntryRead } from "../../src/types/CuratedEntryRead";
import type { PlaybackItemRead } from "../../src/types/PlaybackItemRead";
import { aProbeCategory } from "./aProbeCategory";
import { aProbeListing } from "./aProbeListing";

/** Everything the fake backend answers with: the wall of cards, the category behind them, and the queue. */
export interface ProbeLibrary {
  readonly detail: CategoryDetail;
  readonly listing: CatalogListing;
  /**
   * The review queue, which spans every category at once rather than belonging to the one above.
   *
   * Empty here rather than absent: an empty queue is the normal resting state of that view, so every
   * other surface reads the same shape the unresolved one does and none of them can 404 by accident.
   */
  readonly queue: readonly CuratedEntryRead[];
  readonly entries: readonly CuratedEntryRead[];
  readonly playbackItems: readonly PlaybackItemRead[];
}

/** The library nothing is wrong with, which every surface reads unless it is about something wrong. */
export function aProbeLibrary(): ProbeLibrary {
  const detail = aProbeCategory();
  return { detail, listing: aProbeListing(detail), queue: [], entries: [], playbackItems: [] };
}
