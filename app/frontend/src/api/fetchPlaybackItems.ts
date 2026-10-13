import type { PlaybackItemRead } from "../types/PlaybackItemRead";
import { requestPages } from "./requestPages";

export function fetchPlaybackItems(entryId: string, signal?: AbortSignal): Promise<PlaybackItemRead[]> {
  return requestPages<PlaybackItemRead>(`/api/playback/entries/${encodeURIComponent(entryId)}/items`, signal);
}
