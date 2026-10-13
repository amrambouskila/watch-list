import type { WatchEventCreate } from "../types/WatchEventCreate";
import type { WatchEventRead } from "../types/WatchEventRead";
import { request } from "./request";

export function recordPlaybackEvent(entryId: string, fileId: string, event: WatchEventCreate): Promise<WatchEventRead> {
  const query = new URLSearchParams({ playback_entry_id: entryId, jellyfin_item_id: fileId });
  return request<WatchEventRead>(`/api/watch-events?${query}`, { method: "POST", body: JSON.stringify(event) });
}
