import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import { requestPages } from "./requestPages";

/**
 * Every row a heuristic could not settle, across every category, worst first.
 *
 * Paged rather than fetched once: §10.3 says this view lists **every** unresolved and auto entry, and a
 * bootstrap run with no TMDB token leaves all 996 rows unresolved — four times what one page holds. A
 * single request would have truncated that silently, which is the one thing a review queue may not do.
 *
 * A short page is the last page, so the walk stops without a count the server does not send. One request
 * rather than nineteen is still the shape: the queue spans the whole library, and the pages are its own.
 */
export function fetchReviewQueue(): Promise<CuratedEntryRead[]> {
  return requestPages<CuratedEntryRead>("/api/review/entries");
}
