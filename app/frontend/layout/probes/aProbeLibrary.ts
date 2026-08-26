import type { CatalogListing } from "../../src/types/CatalogListing";
import type { CategoryDetail } from "../../src/types/CategoryDetail";
import { aProbeCategory } from "./aProbeCategory";
import { aProbeListing } from "./aProbeListing";

/** Everything the fake backend answers with: the wall of cards, and the one category behind them. */
export interface ProbeLibrary {
  readonly detail: CategoryDetail;
  readonly listing: CatalogListing;
}

/** The library nothing is wrong with, which every surface reads unless it is about something wrong. */
export function aProbeLibrary(): ProbeLibrary {
  const detail = aProbeCategory();
  return { detail, listing: aProbeListing(detail) };
}
