import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import type { ResolutionUpdate } from "../types/ResolutionUpdate";
import { request } from "./request";

/** One human decision about one curated row; the answer is the row as it now stands. */
export function reviewEntry(entryId: string, update: ResolutionUpdate): Promise<CuratedEntryRead> {
  return request<CuratedEntryRead>(`/api/review/entries/${encodeURIComponent(entryId)}`, {
    method: "POST",
    body: JSON.stringify(update),
  });
}
