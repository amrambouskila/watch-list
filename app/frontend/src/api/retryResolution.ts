import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import { request } from "./request";

/**
 * Spend one search on one row and answer with what it now says (R71).
 *
 * No body: a retry asks nothing of the reviewer, it asks the provider again on their behalf.
 */
export function retryResolution(entryId: string): Promise<CuratedEntryRead> {
  return request<CuratedEntryRead>(`/api/review/entries/${encodeURIComponent(entryId)}/retry`, { method: "POST" });
}
