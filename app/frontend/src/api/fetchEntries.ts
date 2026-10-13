import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import { requestPages } from "./requestPages";

export function fetchEntries(categoryId: string, signal?: AbortSignal): Promise<CuratedEntryRead[]> {
  return requestPages<CuratedEntryRead>(`/api/categories/${encodeURIComponent(categoryId)}/entries`, signal);
}
