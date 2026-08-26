import type { CatalogListing } from "../../src/types/CatalogListing";
import type { CategoryDetail } from "../../src/types/CategoryDetail";
import type { CategorySummary } from "../../src/types/CategorySummary";

const LIBRARY_DIR = "the probe library";

/** The listing carries cards, not sheets, so the rows of the open category do not travel with it. */
function summaryOf(detail: CategoryDetail): CategorySummary {
  return {
    id: detail.id,
    name: detail.name,
    file_name: detail.file_name,
    sheet_title: detail.sheet_title,
    accent: detail.accent,
    mtime: detail.mtime,
    has_watch_column: detail.has_watch_column,
    locked_by_excel: detail.locked_by_excel,
    hero_url: detail.hero_url ?? null,
    counts: detail.counts,
  };
}

/** The wall the dock sits over: one card, for the category the probes read. */
export function aProbeListing(detail: CategoryDetail): CatalogListing {
  return { categories: [summaryOf(detail)], unreadable: [], shadowed: [], library_dir: LIBRARY_DIR };
}
