import { request } from "./request";

/** The shared entries/queue endpoint ceiling, matching MAX_ENTRIES_PAGE_SIZE on the server. */
const ENTRIES_PAGE_SIZE = 500;

export async function requestPages<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = [];
  for (;;) {
    signal?.throwIfAborted();
    const query = new URLSearchParams({ limit: String(ENTRIES_PAGE_SIZE), offset: String(items.length) });
    const page = await request<T[]>(`${path}?${query}`, signal === undefined ? {} : { signal });
    items.push(...page);
    if (page.length < ENTRIES_PAGE_SIZE) return items;
  }
}
