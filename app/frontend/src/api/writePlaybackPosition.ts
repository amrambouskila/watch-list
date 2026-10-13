import type { CategoryDetail } from "../types/CategoryDetail";
import type { PositionWrite } from "../types/PositionWrite";
import { request } from "./request";

export function writePlaybackPosition(entryId: string, position: PositionWrite): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/playback/entries/${encodeURIComponent(entryId)}/position`, {
    method: "POST", body: JSON.stringify(position),
  });
}
